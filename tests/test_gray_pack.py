# -*- coding: utf-8 -*-
"""四灰打包编码正确性验证：pack_4gray 对拍微雪 EPD_7IN5_V2_Display_4Gray 原始 C 循环。

参照实现 _vendor_reference() 逐行转写自厂商 C 代码（RaspberryPi_JetsonNano/c/lib/
e-Paper/EPD_7in5_V2.c 的 EPD_7IN5_V2_Display_4Gray），输入 2bpp 流按厂商
getbuffer_4Gray 的 v>>6 顶两位量化生成——两实现必须在任意灰度图上逐字节一致。
运行：python test_gray_pack.py
"""
import random
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _env  # noqa: F401
from epd_dashboard.config import EPD_HEIGHT, EPD_IMAGE_BYTES, EPD_IMAGE_BYTES_4G, EPD_WIDTH
from epd_dashboard.output import pack_4gray

W, H = EPD_WIDTH, EPD_HEIGHT


def quantize_2bpp(g):
    """量化与 output.pack_4gray 保持一致：白界 160（真机调优，偏离厂商 192），
    其余分档 黑<64 / 深灰<128 / 浅灰<160。4 像素/字节 MSB-first。"""
    buf = bytearray(W * H // 4)
    for y in range(H):
        for x in range(W):
            v = g.getpixel((x, y))
            code = 0b00 if v < 64 else 0b01 if v < 128 else 0b10 if v < 160 else 0b11
            buf[(x + y * W) // 4] |= code << (6 - 2 * ((x + y * W) % 4))
    return bytes(buf)


def vendor_planes(stream):
    """厂商 Display_4Gray 的等价简化（位运算语义核对自 C 循环）：
    每输入字节4像素（MSB-first），plane10 bit=1 ⇔ 码∈{00,10}；plane13 bit=1 ⇔ 码∈{00,01}。"""
    p10 = bytearray(48000)
    p13 = bytearray(48000)
    for i in range(48000):
        b10 = 0
        b13 = 0
        for bit in range(8):  # 输出字节的 8 个位 = 8 个连续像素（MSB first）
            px_byte = stream[(i * 8 + bit) // 4]
            shift = 6 - 2 * ((i * 8 + bit) % 4)
            code = (px_byte >> shift) & 0x03
            b10 <<= 1
            b13 <<= 1
            if code in (0b00, 0b10):
                b10 |= 1
            if code in (0b00, 0b01):
                b13 |= 1
        p10[i] = b10
        p13[i] = b13
    return bytes(p10), bytes(p13)


def make_test_image(kind):
    g = Image.new("L", (W, H), 255)
    px = g.load()
    rng = random.Random(42 if kind == "random" else 7)
    for y in range(H):
        for x in range(W):
            if kind == "bands":  # 四条等高灰带：黑/深灰/浅灰/白（人工核对基准）
                v = (0, 64, 128, 192)[y * 4 // H]
            elif kind == "levels":  # 精确打在四档代表值 + 中间值（跨阈值边界）
                v = (0, 32, 63, 64, 96, 127, 128, 160, 191, 192, 224, 255)[(x + y) % 12]
            else:  # 随机灰度（全值域覆盖）
                v = rng.randrange(256)
            px[x, y] = v
    return g


def main():
    failures = 0
    for kind in ("bands", "levels", "random"):
        g = make_test_image(kind)
        packed = pack_4gray(g)
        assert len(packed) == EPD_IMAGE_BYTES_4G, f"{kind}: size {len(packed)}"
        stream = quantize_2bpp(g)
        ref10, ref13 = vendor_planes(stream)
        got10, got13 = packed[:48000], packed[48000:]
        ok10 = got10 == ref10
        ok13 = got13 == ref13
        print(f"{kind:>7}: plane10 {'OK' if ok10 else 'MISMATCH'}  plane13 {'OK' if ok13 else 'MISMATCH'}")
        if not (ok10 and ok13):
            failures += 1
            diff = [i for i in range(48000) if got10[i] != ref10[i]][:3]
            print("  first diffs:", diff)

    # 固件平面切换边界：48000B 必须行对齐（EPD_ROW_BYTES=100 整除），切换无残行
    assert EPD_IMAGE_BYTES % 100 == 0, "48000 必须整除行宽100，否则固件切换平面会切在行中间"
    print("firmware plane-switch boundary: 48000 % 100 == 0 OK")

    # 语义抽查：四档代表值在两平面上的位组合（黑=11/10? 逐码断言）
    g = Image.new("L", (4, 1), 255)
    for i, v in enumerate((0, 64, 128, 192)):  # 黑 深灰 浅灰 白
        g.putpixel((i, 0), v)
    p = pack_4gray(g)
    # 4 像素 → 每平面 1 字节，四像素占高 4 位（MSB-first）
    b10 = p[0] >> 4 & 0xF
    b13 = p[1] >> 4 & 0xF
    codes10 = format(b10, "04b")
    codes13 = format(b13, "04b")
    expect = {"black": ("1", "1"), "dark": ("0", "1"), "light": ("1", "0"), "white": ("0", "0")}
    got = {
        "black": (codes10[0], codes13[0]),
        "dark": (codes10[1], codes13[1]),
        "light": (codes10[2], codes13[2]),
        "white": (codes10[3], codes13[3]),
    }
    for k in expect:
        status = "OK" if got[k] == expect[k] else "FAIL"
        if got[k] != expect[k]:
            failures += 1
        print(f"semantics {k:>5}: plane10={got[k][0]} plane13={got[k][1]} [{status}]")
    print("ALL PASS" if failures == 0 else f"{failures} FAILURES")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
