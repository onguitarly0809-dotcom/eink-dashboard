"""串口推送 dashboard.bin 到 ESP8266 固件。

握手序列（与 send_dashboard.ps1 / dashboard_serial.ino 一致）：
PING/PONG → BEGIN <n> → EPD INIT → READY → 分块数据+ACK <累计字节> →
DATA OK → REFRESH → REFRESHING → DONE。

波特率自动协商：先探 921600/512B（新固件），不通再探 115200/128B（旧固件），
固件重刷前后 PC 端都无需改配置。--baud/--chunk 可强制指定跳过协商。
"""
import time
from pathlib import Path

import serial
import serial.tools.list_ports

from epd_dashboard.config import BASE_DIR, EPD_IMAGE_BYTES, EPD_SERIAL_PORT

DEFAULT_BINARY = BASE_DIR / "dashboard.bin"

# (baud, chunk)：与固件 dashboard_serial.ino 的 Serial.begin / kChunkSize 对应
BAUD_CANDIDATES = ((921600, 512), (115200, 128))

# NodeMCU 板载 CP210x USB 转串桥的 USB 身份：用户会拔插 USB，Windows 换口重枚举后
# COM 号可能变化，按 VID:PID 自动找回设备，端口号不再写死
DEVICE_VID_PID = ("10C4", "EA60")


class PushError(RuntimeError):
    pass


class DeviceUnavailable(PushError):
    """确定性失败：端口不存在（已拔出）或被其他程序占用。重试无意义，调用方应立即放弃。"""


def find_device_port(exclude=None):
    """按 USB VID:PID 扫描 CP210x 桥，返回端口号；找不到返回 None。"""
    for p in serial.tools.list_ports.comports():
        if p.device == exclude:
            continue
        if f"VID:PID={DEVICE_VID_PID[0]}:{DEVICE_VID_PID[1]}" in (p.hwid or "").upper():
            return p.device
    return None


def _resolve_port(port, log):
    """恢复策略：配置端口不存在（USB 拔出/换口）时按 VID:PID 自动找回；彻底没有则快速失败。"""
    present = {p.device for p in serial.tools.list_ports.comports()}
    if port in present:
        return port
    found = find_device_port(exclude=port)
    if found:
        log(f"port {port} absent (USB moved?), auto-discovered device on {found}")
        return found
    raise DeviceUnavailable(
        f"设备未连接：串口 {port} 不存在且未发现 CP210x 设备（USB 已拔出？）"
        "插回后下一轮轮播会自动恢复"
    )


def _open_port(port, baud):
    try:
        return serial.Serial(port, baud, bytesize=8, parity=serial.PARITY_NONE,
                             stopbits=serial.STOPBITS_ONE, timeout=2, write_timeout=5)
    except serial.SerialException as exc:
        msg = str(exc)
        if "PermissionError" in msg or "拒绝访问" in msg or "Access is denied" in msg:
            raise DeviceUnavailable(
                f"串口 {port} 被其他程序占用（串口监视器/烧录工具开着？关闭后重试）"
            ) from exc
        raise


def _read_line(ser, timeout_hint=""):
    line = ser.readline()
    if not line:
        raise PushError(f"serial read timeout{(' ' + timeout_hint) if timeout_hint else ''}")
    return line.decode("ascii", errors="replace").strip()


def _expect(ser, expected, timeout_hint=""):
    resp = _read_line(ser, timeout_hint)
    while not resp:
        resp = _read_line(ser, timeout_hint)
    if resp != expected:
        raise PushError(f"Expected '{expected}', received '{resp}'")
    return resp


def _probe(port, baud, probe_timeout=1.5):
    """以指定波特率 PING 固件；在监听则返回已打开的 Serial，否则关闭并返回 None。"""
    try:
        ser = serial.Serial(port, baud, bytesize=8, parity=serial.PARITY_NONE,
                            stopbits=serial.STOPBITS_ONE, timeout=0.2, write_timeout=5)
    except serial.SerialException as exc:
        msg = str(exc)
        if "PermissionError" in msg or "拒绝访问" in msg or "Access is denied" in msg:
            raise DeviceUnavailable(
                f"串口 {port} 被其他程序占用（串口监视器/烧录工具开着？关闭后重试）"
            ) from exc
        raise
    ser.dtr = False
    ser.rts = False
    try:
        time.sleep(0.4)
        ser.write(b"\r\n")
        ser.reset_input_buffer()
        ser.write(b"PING\n")
        deadline = time.monotonic() + probe_timeout
        while time.monotonic() < deadline:
            line = ser.readline()
            if line and line.decode("ascii", errors="replace").strip() == "PONG":
                ser.timeout = 2
                return ser
    except (serial.SerialException, OSError):
        pass
    ser.close()
    return None


def push(binary_path=None, port=None, baud=None, chunk=None, done_timeout=30, log=print):
    """推送一帧图像并等待物理刷新完成；失败抛 PushError。"""
    binary_path = Path(binary_path or DEFAULT_BINARY)
    port = _resolve_port(port or EPD_SERIAL_PORT, log)

    data = binary_path.read_bytes()
    if len(data) != EPD_IMAGE_BYTES:
        raise PushError(f"Invalid binary size: expected {EPD_IMAGE_BYTES}, got {len(data)}")

    started = time.monotonic()
    if baud:
        ser = _probe(port, baud)
        if ser is None:
            raise PushError(f"No PONG from ESP8266 at {baud} baud on {port}. "
                            "Upload dashboard_serial.ino first, or press RESET and retry.")
        chunk = chunk or 128
    else:
        ser = None
        for cand_baud, cand_chunk in BAUD_CANDIDATES:
            ser = _probe(port, cand_baud)
            if ser is not None:
                baud, chunk = cand_baud, cand_chunk
                break
        if ser is None:
            raise PushError(
                f"No PONG from ESP8266 on {port} at any baud "
                f"({'/'.join(str(b) for b, _ in BAUD_CANDIDATES)}). "
                "Upload dashboard_serial.ino first, or press RESET and retry."
            )

    try:
        ser.write(f"BEGIN {len(data)}\n".encode("ascii"))
        _expect(ser, "EPD INIT")
        # 新固件跳过旧帧白屏预清，READY 即时；旧固件冷初始化需数秒
        ser.timeout = 20
        _expect(ser, "READY", "waiting for READY")
        ser.timeout = 2

        offset = 0
        while offset < len(data):
            count = min(chunk, len(data) - offset)
            ser.write(data[offset:offset + count])
            resp = _read_line(ser, f"waiting for ACK at offset {offset}")
            if not resp.startswith("ACK "):
                raise PushError(f"Expected ACK at offset {offset}, received '{resp}'")
            if int(resp[4:]) != offset + count:
                raise PushError(f"ACK mismatch: expected {offset + count}, received {resp[4:]}")
            offset += count

        _expect(ser, "DATA OK")
        ser.write(b"REFRESH\n")
        _expect(ser, "REFRESHING")
        ser.timeout = done_timeout
        _expect(ser, "DONE", "waiting for e-paper refresh")
    finally:
        ser.close()
    log(f"push complete in {time.monotonic() - started:.1f}s ({baud} baud, {chunk}B chunks)")


def push_with_retry(retries=3, retry_delay=2.0, **kwargs):
    """带重试的推送；全部失败抛最后一次的 PushError。

    DeviceUnavailable（端口不存在/被占用）是确定性失败：重试不会改变结果，立即向上抛。
    """
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            push(**kwargs)
            return
        except DeviceUnavailable:
            raise
        except (PushError, serial.SerialException, OSError) as exc:
            last_exc = exc
            if attempt < retries:
                print(f"WARN push attempt {attempt}/{retries} failed: {exc}", flush=True)
                time.sleep(retry_delay)
    raise PushError(
        f"push failed after {retries} attempts: {last_exc} "
        f"(check USB cable / firmware / port {kwargs.get('port') or EPD_SERIAL_PORT})"
    )
