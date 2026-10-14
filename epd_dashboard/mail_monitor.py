"""IMAP IDLE 新邮件监控守护进程（QQ 邮箱，Gmail 经转发接入）。

收到新邮件 → 写 mail_inbox.json → 调 dashboard_control.ps1 mail（-Wait 排队）→
墨水屏在当前页之上叠加"邮件提醒弹窗卡"（手机二级菜单式，底图存 mail_base.png）。
overlay_seconds（默认 10 分钟）后调 mailoff 把底图原样推回，像素级还原被覆盖页；
弹窗期间若轮播/手动动作已切页（页状态变化）则跳过还原，屏幕交给新页面。

运行方式（与 Web 控制台同款）：运营目录薄入口 mail_monitor.py（设 EPD_VARIANT/
EPD_BASE_DIR 后 import 本模块），pythonw 隐藏后台跑，开机自启见
ops/setup_mail_autostart.ps1。

凭据：BASE_DIR/mail_config.json（.gitignore 已排除，严禁入库）：
  {"account": "xxx@qq.com", "auth_code": "QQ邮箱16位授权码", ...}
授权码获取：QQ邮箱网页版 设置→账号 开启 IMAP/SMTP 服务时生成。

可靠性设计：
- IDLE 长连接秒级感知（RFC 2177：每 25 分钟重发）；服务器不支持时自动降级 30s 轮询
- 断线自动重连（指数退避 30s→5min），重连后按 UID 水位补查断线期间漏掉的新邮件
- 状态持久化（mail_state.json：UID 水位 + 弹窗还原状态）：进程重启不重复通知旧
  邮件；弹窗期间重启也能按时收起还原。首次启动只记水位基线不通知
- 防刷屏：批量合并（到件后等 batch_window 收拢突发）、最小推送间隔 min_push_gap、
  持续滴灌超过 max_pending 强制推一次
- 单实例：pid 锁文件防重复启动双推
"""
import ctypes
import json
import socket
import subprocess
import sys
import time
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from epd_dashboard.config import (
    BASE_DIR,
    MAIL_CONFIG_FILE,
    MAIL_INBOX_FILE,
    MAIL_LOG_FILE,
    MAIL_STATE_FILE,
    PAGE_STATE_FILE,
)

IDLE_MAX_SECONDS = 25 * 60   # RFC 2177：单次 IDLE 上限 29 分钟，25 分钟重发
IDLE_WAKE_SECONDS = 20       # IDLE 等待中的 socket 唤醒粒度
POLL_FALLBACK_SECONDS = 30   # 服务器不支持 IDLE 时的轮询周期
FETCH_BATCH = 20             # 单周期最多取信头数（防长时间占连接，下周期继续）
PUSH_WAIT_SECONDS = 160      # control.ps1 排队参数：覆盖一轮轮播 1.5~2.5 分钟
PUSH_TIMEOUT_SECONDS = 600

DEFAULT_CONFIG = {
    "host": "imap.qq.com",
    "port": 993,
    "min_push_gap_seconds": 180,   # 两次推屏最小间隔（防刷屏）
    "batch_window_seconds": 25,    # 到件后等待合并窗口（收拢突发多封）
    "max_pending_seconds": 300,    # 持续滴灌下的最长积压（保证 5 分钟内必推）
    "max_show": 3,                 # 弹窗卡最多显示封数
    "overlay_seconds": 600,        # 弹窗停留时长（到点 mailoff 还原被覆盖页）
}


def _log_write(line):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(MAIL_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {line}\n")
        if MAIL_LOG_FILE.stat().st_size > 1024 * 1024:
            lines = MAIL_LOG_FILE.read_text(encoding="utf-8").splitlines()
            MAIL_LOG_FILE.write_text("\n".join(lines[len(lines) // 2:]) + "\n", encoding="utf-8")
    except OSError:
        pass


class MailMonitor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.account = cfg["account"]
        self.imap = None
        self.polling = False
        state = self._load_state()
        self.watermark = int(state.get("watermark") or 0)
        self.baselined = self.watermark > 0
        # 弹窗还原状态（重启续期：守护进程挂掉期间到点，重启后照常收起）
        self.overlay_until = float(state.get("overlay_until") or 0)
        self.overlay_page = state.get("overlay_page")
        self.pending = []           # [{"uid", "from", "subject", "time"}]
        self.first_pending = 0.0
        self.last_arrival = 0.0
        self.last_push = 0.0
        self.backoff = 30

    # ---------- 基础件 ----------
    def log(self, msg):
        _log_write(msg)
        print(msg, file=sys.stderr)

    def _load_state(self):
        try:
            return json.loads(MAIL_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _save_state(self):
        tmp = MAIL_STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "watermark": self.watermark,
            "overlay_until": self.overlay_until,
            "overlay_page": self.overlay_page,
        }), encoding="utf-8")
        tmp.replace(MAIL_STATE_FILE)

    def _read_page_state(self):
        """当前轮播页状态（ops/control.ps1 维护的 page_state.json）。"""
        try:
            state = json.loads(PAGE_STATE_FILE.read_text(encoding="utf-8"))
            page = int(state.get("page", 0))
            return page if page in (1, 2, 3, 4, 5) else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    # ---------- IMAP 连接 ----------
    def connect(self):
        import imaplib
        import ssl
        ctx = ssl.create_default_context()
        self.log(f"连接 {self.cfg['host']}:{self.cfg['port']} ...")
        self.imap = imaplib.IMAP4_SSL(self.cfg["host"], self.cfg["port"], ssl_context=ctx)
        self.imap.login(self.account, self.cfg["auth_code"])
        status, _ = self.imap.select("INBOX")
        if status != "OK":
            raise RuntimeError("SELECT INBOX 失败")
        self.polling = False
        self.log("IMAP 登录成功（IDLE 模式）")

    def close_quietly(self):
        if self.imap is not None:
            try:
                self.imap.logout()
            except Exception:
                pass
            self.imap = None

    # ---------- 新邮件抓取 ----------
    def catchup(self):
        """按 UID 水位补查新邮件（连接建立后/IDLE 事件后/断线重连后调用）。"""
        if self.imap is None:
            return
        # IDLE 结束后重新 SELECT 刷新服务器端邮件视图，再按水位搜索
        status, _ = self.imap.select("INBOX")
        if status != "OK":
            raise RuntimeError("SELECT INBOX 失败")
        if not self.baselined:
            self.watermark = self._uid_max()
            self.baselined = True
            self._save_state()
            self.log(f"首次启动：基线水位 UID={self.watermark}（不通知存量邮件）")
            return
        status, data = self.imap.uid("SEARCH", None, "UID", f"{self.watermark + 1}:*")
        if status != "OK" or not data or not data[0]:
            return
        uids = sorted(int(u) for u in data[0].split())
        uids = [u for u in uids if u > self.watermark][:FETCH_BATCH]
        now_str = time.strftime("%H:%M")
        got = 0
        # FETCH 抛异常 = 传输层故障 → 直接上抛触发重连（水位未推进，重连后补查）；
        # 单封解析失败给占位记录，水位照常推进，不留永久卡位
        for uid in uids:
            status, data = self.imap.uid("FETCH", str(uid),
                                         "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            record = self._parse_fetch(uid, status, data, now_str)
            self.pending.append(record)
            got += 1
        if uids:
            self.watermark = max(self.watermark, max(uids))
            self._save_state()
        if got:
            self.last_arrival = time.time()
            if not self.first_pending:
                self.first_pending = self.last_arrival
            self.log(f"新邮件 {got} 封（水位→{self.watermark}）："
                     + "；".join(r["subject"][:30] for r in self.pending[-got:]))

    def _uid_max(self):
        status, data = self.imap.uid("SEARCH", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return 0
        uids = [int(u) for u in data[0].split()]
        return max(uids) if uids else 0

    def _parse_fetch(self, uid, status, data, now_str):
        if status != "OK" or not data or not isinstance(data[0], tuple):
            return {"uid": uid, "from": "(无法解析)", "subject": "(无法解析)", "time": now_str}
        try:
            msg = message_from_bytes(data[0][1])
        except Exception:
            return {"uid": uid, "from": "(无法解析)", "subject": "(无法解析)", "time": now_str}
        sender = self._decode(msg.get("From", ""))
        name, addr = parseaddr(sender)
        display = name or addr or "(未知发件人)"
        subject = self._decode(msg.get("Subject", "")) or "(无主题)"
        arrive = now_str
        try:
            arrive = parsedate_to_datetime(msg.get("Date")).astimezone().strftime("%H:%M")
        except (TypeError, ValueError):
            pass
        return {"uid": uid, "from": display, "subject": subject, "time": arrive}

    @staticmethod
    def _decode(value):
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return str(value)

    # ---------- IDLE 等待 ----------
    def _idle_begin(self):
        """返回 IDLE 标签；服务器拒绝 IDLE（无 '+' 续行）时转轮询模式。"""
        tag = self.imap._new_tag().decode()
        self.imap.send(f"{tag} IDLE\r\n".encode())
        self.imap.socket().settimeout(30)
        line = self.imap.readline()
        if not line.startswith(b"+"):
            self.polling = True
            self.log(f"服务器不支持 IDLE（{line[:40]!r}），降级 {POLL_FALLBACK_SECONDS}s 轮询")
            return None
        return tag

    def _idle_end(self, tag):
        self.imap.send(b"DONE\r\n")
        self.imap.socket().settimeout(60)
        while True:
            line = self.imap.readline()
            if not line or line.startswith(tag.encode()):
                break

    def wait_events(self, max_wait):
        """等待新邮件事件，最长 max_wait 秒。返回 True=有事件/该查了。"""
        if max_wait < 2:
            return True   # 推送时机已到：跳过 IDLE 往返，直接回主循环
        if self.polling:
            time.sleep(min(POLL_FALLBACK_SECONDS, max_wait))
            return True
        tag = self._idle_begin()
        if tag is None:
            time.sleep(POLL_FALLBACK_SECONDS)
            return True
        deadline = time.time() + max_wait
        buf = b""
        sock = self.imap.socket()
        hit = False
        try:
            while time.time() < deadline and not hit:
                sock.settimeout(IDLE_WAKE_SECONDS)
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        raise ConnectionError("IDLE 连接被服务器关闭")
                    buf = (buf + chunk)[-512:]
                    if b"EXISTS" in buf or b"RECENT" in buf:
                        hit = True
                except TimeoutError:
                    pass   # 唤醒粒度（socket.timeout 即 TimeoutError）到了，继续等
                except OSError as exc:
                    # 连接级故障：立刻上抛触发重连，不在残连接上忙等到 deadline
                    raise ConnectionError(f"IDLE 连接异常: {exc!r}") from exc
        finally:
            try:
                self._idle_end(tag)
            except Exception as exc:
                raise ConnectionError(f"IDLE 结束阶段连接异常: {exc!r}") from exc
        return hit

    # ---------- 推送与收起 ----------
    def _run_control(self, command):
        """调 dashboard_control.ps1 命令（-Wait 排队等轮播让锁）。返回是否成功。"""
        control = BASE_DIR / "dashboard_control.ps1"
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(control), command, "-Wait", str(PUSH_WAIT_SECONDS)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=PUSH_TIMEOUT_SECONDS,
                cwd=str(BASE_DIR),
            )
        except subprocess.TimeoutExpired:
            self.log(f"ERROR control.ps1 {command} 超时")
            return False
        if result.returncode == 0:
            return True
        tail = (result.stdout or result.stderr or "").strip().splitlines()[-3:]
        self.log(f"ERROR control.ps1 {command} 退出码 {result.returncode} :: {' | '.join(tail)}")
        return False

    def _push_due_in(self):
        """距离"可以推屏"还有多少秒。

        正常到期 = 合并窗口（最后一封到达后再等 batch_window 收拢突发）与最小推送
        间隔（距上次成功推送 min_push_gap，防刷屏）中较晚者；最长积压 max_pending
        是硬上限（持续滴灌时强制推，可越过最小间隔），两者取较早。
        """
        if not self.pending:
            return float(IDLE_MAX_SECONDS)
        now = time.time()
        normal_due = max(self.last_arrival + self.cfg["batch_window_seconds"],
                         self.last_push + self.cfg["min_push_gap_seconds"])
        hard_deadline = self.first_pending + self.cfg["max_pending_seconds"]
        return max(0.0, min(normal_due, hard_deadline) - now)

    def maybe_push(self):
        if not self.pending or self._push_due_in() > 0:
            return
        payload = {
            "account": self.account,
            "total_new": len(self.pending),
            "mails": self.pending[-self.cfg["max_show"]:][::-1],  # 最新在前
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        tmp = MAIL_INBOX_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(MAIL_INBOX_FILE)
        self.log(f"推送邮件弹窗：{len(self.pending)} 封（展示 {len(payload['mails'])}）")
        # 失败也刷新 last_push：重试按最小推送间隔节流，不连续轰击
        if self._run_control("mail"):
            self.log("弹窗上屏完成")
            self.pending = []
            self.first_pending = 0.0
            self.last_push = time.time()
            self._arm_dismiss()
        else:
            self.last_push = time.time()
            self.log(f"队列保留、{self.cfg['min_push_gap_seconds']}s 后重试")

    def _arm_dismiss(self):
        """弹窗上屏后布防收起：记录还原基准页（mail 不写页状态，读取即基准）。"""
        self.overlay_until = time.time() + self.cfg["overlay_seconds"]
        self.overlay_page = self._read_page_state()
        self._save_state()
        self.log(f"弹窗将于 {self.cfg['overlay_seconds']}s 后收起（还原基准=页{self.overlay_page}）")

    def maybe_dismiss(self):
        """到点收起弹窗：页状态未变才还原（变了说明轮播/手动已接管屏幕，不倒退）。"""
        if not self.overlay_until or time.time() < self.overlay_until:
            return
        current = self._read_page_state()
        if current != self.overlay_page:
            self.log(f"弹窗期间页面已流转（{self.overlay_page}→{current}），跳过还原")
        elif self._run_control("mailoff"):
            self.log("弹窗已收起，被覆盖页还原完成")
        else:
            self.log("mailoff 失败，下个周期重试收起")
            return
        self.overlay_until = 0.0
        self.overlay_page = None
        self._save_state()

    # ---------- 主循环 ----------
    def run(self):
        self.log(f"邮件监控启动 account={self.account} watermark={self.watermark}"
                 + (f" 续期弹窗(至{time.strftime('%H:%M:%S', time.localtime(self.overlay_until))}"
                    f" 基准页{self.overlay_page})" if self.overlay_until else ""))
        while True:
            try:
                if self.imap is None:
                    self.connect()
                    self.catchup()
                # 唤醒上限取三者最小：IDLE 协议上限 / 下次可推送时刻 / 弹窗收起时刻
                wake_in = self._push_due_in()
                if self.overlay_until:
                    wake_in = min(wake_in, max(1.0, self.overlay_until - time.time()))
                self.wait_events(min(IDLE_MAX_SECONDS, wake_in))
                self.catchup()
                self.backoff = 30
            except KeyboardInterrupt:
                self.log("收到退出信号，邮件监控停止")
                self.close_quietly()
                return
            except Exception as exc:
                self.log(f"IMAP 异常: {exc!r}，{self.backoff}s 后重连")
                self.close_quietly()
                time.sleep(self.backoff)
                self.backoff = min(self.backoff * 2, 300)
                continue
            self.maybe_push()
            self.maybe_dismiss()


# ---------- 单实例 pid 锁 ----------
def _pid_alive(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


class _PidLock:
    """mail_monitor.lock：存在且 pid 存活则拒绝启动；残留死锁自动接管。"""

    def __init__(self, path):
        self.path = path
        self.acquired = False

    def __enter__(self):
        pid = 0
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip())
            except ValueError:
                pid = 0
            if pid and _pid_alive(pid):
                print(f"已有监控实例在运行（pid={pid}），本次启动退出", file=sys.stderr)
                sys.exit(0)
        self.path.write_text(str(_my_pid()))
        self.acquired = True
        return self

    def __exit__(self, *exc):
        if self.acquired:
            try:
                self.path.unlink()
            except OSError:
                pass


def _my_pid():
    import os
    return os.getpid()


def load_config():
    if not MAIL_CONFIG_FILE.exists():
        note = (
            f"缺少配置文件 {MAIL_CONFIG_FILE}\n"
            "请创建（UTF-8）：{\"account\": \"你的QQ邮箱@qq.com\", \"auth_code\": \"16位授权码\"}\n"
            "授权码获取：QQ邮箱网页版 设置 → 账号 → 开启 IMAP/SMTP 服务 → 生成授权码"
        )
        print(note, file=sys.stderr)
        _log_write("启动失败：" + note.replace("\n", " "))
        sys.exit(1)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(json.loads(MAIL_CONFIG_FILE.read_text(encoding="utf-8")))
    for key in ("account", "auth_code"):
        if not cfg.get(key):
            print(f"mail_config.json 缺少 {key}", file=sys.stderr)
            sys.exit(1)
    return cfg


def main():
    cfg = load_config()
    with _PidLock(BASE_DIR / "mail_monitor.lock"):
        MailMonitor(cfg).run()


if __name__ == "__main__":
    main()
