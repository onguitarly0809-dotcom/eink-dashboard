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
- 推送/收起被挡（锁屏闸门、设备未连接）时按固定周期重查、不做忙等；解锁或插回后自动补
"""
import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parseaddr

from epd_dashboard.config import (
    BASE_DIR,
    MAIL_BASE_PNG,
    MAIL_CONFIG_FILE,
    MAIL_INBOX_FILE,
    MAIL_LOG_FILE,
    MAIL_STATE_FILE,
    PAGE_STATE_FILE,
    PAUSE_BASE_PNG,
)

IDLE_MAX_SECONDS = 25 * 60   # RFC 2177：单次 IDLE 上限 29 分钟，25 分钟重发
IDLE_WAKE_SECONDS = 20       # IDLE 等待中的 socket 唤醒粒度
IDLE_KEEPALIVE_SECONDS = 240 # IDLE 会话保活：静默连接定期重开（QQ 对长 IDLE 会静默哑火）
COMMAND_TIMEOUT_SECONDS = 120  # IMAP 命令阶段（SELECT/SEARCH/FETCH）的 socket 超时：
                               # imaplib 默认无限阻塞，连接假死时守护会卡死无日志
POLL_FALLBACK_SECONDS = 30   # 服务器不支持 IDLE 时的轮询周期
FETCH_BATCH = 20             # 单周期最多取信头数（防长时间占连接，下周期继续）
PUSH_WAIT_SECONDS = 160      # control.ps1 排队参数：覆盖一轮轮播 1.5~2.5 分钟
PUSH_TIMEOUT_SECONDS = 600
LOCKED_DEFER_WAKE_S = 20     # 锁屏推迟期间的重查间隔（秒）：仍锁定就继续等，解锁即补推
CONTROL_RETRY_S = 30         # 推送/收起真失败（如设备未连接）后的重试间隔（秒）

# Toolhelp 进程快照（锁屏检测用，见 _process_running）
TH32CS_SNAPPROCESS = 0x00000002


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


_kernel32 = None


def _get_kernel32():
    """kernel32 的 ctypes 句柄，补齐原型（默认把 64 位句柄截成 int，必须显式声明）。"""
    global _kernel32
    if _kernel32 is None:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        for name in ("Process32FirstW", "Process32NextW"):
            fn = getattr(k32, name)
            fn.restype = wintypes.BOOL
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        _kernel32 = k32
    return _kernel32

DEFAULT_CONFIG = {
    "host": "imap.qq.com",
    "port": 993,
    "min_push_gap_seconds": 180,   # 两次推屏最小间隔（防刷屏）
    "batch_window_seconds": 5,     # 到件后等待合并窗口（收拢突发；单封为主的场景窗口越小延迟越低）
    "max_pending_seconds": 300,    # 持续滴灌下的最长积压（保证 5 分钟内必推）
    "max_show": 3,                 # 弹窗卡最多显示封数
    "overlay_seconds": 600,        # 弹窗停留时长（到点 mailoff 还原被覆盖页）
    # 广告过滤（子串匹配、不区分大小写；命中任一规则即不推屏，水位照常推进）
    "filters": {
        "block_senders": [],       # 发件人显示名或地址；"@域名" 即域名后缀
        "block_subject_keywords": [],
        "block_from_keywords": [],
    },
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


def _iter_processes():
    """枚举系统进程，产出 (pid, 映像名)；快照 API 失败抛异常，由调用方各自兜底。"""
    k32 = _get_kernel32()
    snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise OSError("CreateToolhelp32Snapshot failed")
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        more = k32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            yield entry.th32ProcessID, entry.szExeFile
            more = k32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snapshot)


def _process_running(image_name):
    """指定映像名的进程是否在运行（Toolhelp 进程快照，实测约 15 毫秒）。

    锁屏监视线程每 2 秒查一次 LogonUI.exe：原先每次拉起 tasklist（实测约 570 毫秒，
    7×24 不停），现在直接枚举进程、不起子进程。快照 API 不可用时退回 tasklist。"""
    try:
        return any(name.upper() == image_name.upper() for _pid, name in _iter_processes())
    except Exception:
        return _process_running_tasklist(image_name)


def _process_image(pid):
    """指定 pid 的映像名（如 python.exe）；进程不存在返回空串，快照 API 失败返回 None。"""
    try:
        for found_pid, name in _iter_processes():
            if found_pid == pid:
                return name
        return ""
    except Exception:
        return None


def _process_running_tasklist(image_name):
    """tasklist 兜底（原实现）：快照 API 不可用时仍能判定。"""
    try:
        # 不做文本解码：tasklist 在中文系统输出 GBK，按 UTF-8 解码会抛异常
        # 把监视线程打死（实测踩坑）；进程名纯 ASCII，按字节匹配跨编码稳定
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
            capture_output=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return image_name.encode("ascii") in out


class MailMonitor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.account = cfg["account"]
        self.imap = None
        self.polling = False
        state = self._load_state()
        self.watermark = int(state.get("watermark") or 0)
        self.baselined = self.watermark > 0
        # 邮箱 UIDVALIDITY（见 _check_uidvalidity）；旧状态文件没有该字段时为 None
        self.uidvalidity = _to_int(state.get("uidvalidity"))
        # 弹窗还原状态（重启续期：守护进程挂掉期间到点，重启后照常收起）
        self.overlay_until = float(state.get("overlay_until") or 0)
        self.overlay_page = state.get("overlay_page")
        self.pending = []           # [{"uid", "from", "subject", "time"}]
        self.first_pending = 0.0
        self.last_arrival = 0.0
        self.last_push = 0.0
        self.backoff = 30
        # 推迟重试：推送/收起没做成后不立刻重来，主循环按 defer_until 等待（防忙循环）。
        # deferred_locked=True 表示推迟原因是锁屏——解锁即可提前结束等待
        self.defer_until = 0.0
        self.deferred_locked = False

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
            "uidvalidity": self.uidvalidity,
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
        # 连接/登录/SELECT 也带超时：此前只有命令阶段（catchup）设了 socket 超时，
        # 连接假死时守护会无日志地卡在登录这一步（imaplib 默认无限阻塞）
        self.imap = imaplib.IMAP4_SSL(self.cfg["host"], self.cfg["port"], ssl_context=ctx,
                                      timeout=COMMAND_TIMEOUT_SECONDS)
        self.imap.socket().settimeout(COMMAND_TIMEOUT_SECONDS)
        self.imap.login(self.account, self.cfg["auth_code"])
        status, _ = self.imap.select("INBOX")
        if status != "OK":
            raise RuntimeError("SELECT INBOX 失败")
        self._check_uidvalidity()
        self.polling = False
        self.log("IMAP 登录成功（IDLE 模式）")

    def _uidvalidity(self):
        """SELECT 返回的 UIDVALIDITY（整数）；服务器没给或解析不了返回 None。"""
        try:
            return int(self.imap.response("UIDVALIDITY")[1][0])
        except (AttributeError, IndexError, TypeError, ValueError):
            return None

    def _check_uidvalidity(self):
        """UIDVALIDITY 变了说明服务器给邮件重新编了号，旧水位从此失去意义：
        新邮件的 UID 追不上旧水位，弹窗会一直哑掉——改为重新基线（不通知存量邮件）。"""
        current = self._uidvalidity()
        if current is None:
            return
        if self.uidvalidity is not None and self.uidvalidity != current:
            self.log(f"邮箱 UIDVALIDITY 变化（{self.uidvalidity}→{current}），重新基线水位")
            self.baselined = False
            self.watermark = 0
        self.uidvalidity = current
        self._save_state()

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
        # IDLE 结束后重新 SELECT 刷新服务器端邮件视图，再按水位搜索。
        # 命令阶段设 socket 超时：连接假死时命令超时上抛 → 重连补查，而非永久卡死
        self.imap.socket().settimeout(COMMAND_TIMEOUT_SECONDS)
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
        blocked = 0
        # FETCH 抛异常 = 传输层故障 → 直接上抛触发重连（水位未推进，重连后补查）；
        # 单封解析失败给占位记录，水位照常推进，不留永久卡位
        for uid in uids:
            status, data = self.imap.uid("FETCH", str(uid),
                                         "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT"
                                         " X-FORWARDED-TO X-FORWARDED-FOR DELIVERED-TO)])")
            record = self._parse_fetch(uid, status, data, now_str)
            try:
                is_blocked = self._is_blocked(record)
            except Exception as exc:
                # 过滤规则自身出错不能卡住水位（会无限重连、反复取到同一封）：按不过滤处理
                is_blocked = False
                self.log(f"WARN 过滤规则执行出错，按不过滤处理: {exc!r}")
            if is_blocked:
                blocked += 1
                self.log(f"已过滤 uid={uid}: {record['subject'][:36]} <{record['addr'][:40]}>")
                continue
            self.pending.append(record)
            got += 1
        if uids:
            self.watermark = max(self.watermark, max(uids))
            self._save_state()
        if blocked and not got:
            self.log(f"本批 {blocked} 封全部命中过滤规则，不推屏")
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
            return {"uid": uid, "from": "(无法解析)", "addr": "", "subject": "(无法解析)", "time": now_str}
        try:
            msg = message_from_bytes(data[0][1])
        except Exception:
            return {"uid": uid, "from": "(无法解析)", "addr": "", "subject": "(无法解析)", "time": now_str}
        sender = self._decode(msg.get("From", ""))
        name, addr = parseaddr(sender)
        display = name or addr or "(未知发件人)"
        subject = self._decode(msg.get("Subject", "")) or "(无主题)"
        # arrive = 到达（被守护检测到）时间，即用户口径的"收到时间"。
        # 不用邮件 Date 头：那是发件方的撰写/定时时间且时钟常错——实测某营销
        # 平台 Date 写 16:02 GMT（=北京 00:02），实际到达却是 15:02，照头显示
        # 像时光倒流；检测时间永远与用户感知一致
        arrive = now_str
        # addr 单独保留：过滤按"显示名+地址"联合匹配，只按显示名会误杀
        # （如某银行营销号与账单号显示名相同、地址不同）
        # via：转发来源识别——综合转发头（X-Forwarded-To/For、Delivered-To）里的
        # 原始收件域名分类（gmail/163·126/其他），直收件无这些头。按域名识别
        # 不含个人地址；若某转发服务（如 Coremail）不添加任何转发头，会归直收
        fwd_trace = " ".join(filter(None, [
            msg.get("X-Forwarded-To", "") or "", msg.get("X-Forwarded-For", "") or "",
            msg.get("Delivered-To", "") or ""])).lower()
        if "gmail.com" in fwd_trace:
            via = "gmail"
        elif "163.com" in fwd_trace or "126.com" in fwd_trace:
            via = "163"
        elif fwd_trace.strip():
            via = "fwd"
        else:
            via = ""
        return {"uid": uid, "from": display, "addr": addr, "subject": subject,
                "time": arrive, "via": via}

    def _is_blocked(self, mail):
        """广告过滤：mail_config.json 的 filters 配置（不区分大小写）。

        block_senders            发件人黑名单：普通条目按"显示名+地址"子串匹配；
                                 "@域名" 形式=域名后缀匹配（该域名及其任意子域，
                                 如 @lists.example-marketing.com 命中
                                 service@mail34.lists.example-marketing.com——
                                 子串实现匹配不到子域，批量营销邮件漏网的根因）
        block_subject_keywords   主题关键词黑名单
        block_from_keywords      发件人显示名关键词黑名单
        命中任一规则即拦截（不推屏，但水位照常推进，不会重复检查）。
        """
        flt = self.cfg.get("filters")
        flt = flt if isinstance(flt, dict) else {}

        def _rules(name):
            # 规则里的非字符串条目（手改 JSON 的笔误）直接忽略，不让一条坏规则卡死水位
            value = flt.get(name)
            return [k for k in value if isinstance(k, str) and k] if isinstance(value, list) else []

        frm = f"{mail.get('from', '')} {mail.get('addr', '')}".lower()
        subj = (mail.get("subject") or "").lower()
        host = mail.get("addr", "").lower().partition("@")[2]
        for rule in _rules("block_senders"):
            r = rule.strip().lower()
            if r.startswith("@"):
                domain = r[1:]
                if host == domain or host.endswith("." + domain):
                    return True
            elif r in frm:
                return True
        if any(k.lower() in subj for k in _rules("block_subject_keywords")):
            return True
        if any(k.lower() in frm for k in _rules("block_from_keywords")):
            return True
        return False

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
        """等待新邮件事件。返回 True=有事件/该查了，False=到等待上限。

        单次 IDLE 会话上限压到 IDLE_KEEPALIVE_SECONDS：到点无事件就返回主循环，
        由 catchup 做一次兜底 UID 查询后再进新 IDLE 会话——QQ 的 IDLE 推送
        会整段哑火（连接活着、命令正常、EXISTS 不送达，实测两次均发生在
        守护重启后的新连接上），保活周期同时就是漏件的最长等待上界。
        """
        if max_wait < 2:
            return True   # 推送时机已到：跳过 IDLE 往返，直接回主循环
        if self.polling:
            time.sleep(min(POLL_FALLBACK_SECONDS, max_wait))
            return True
        deadline = time.time() + min(max_wait, IDLE_KEEPALIVE_SECONDS)
        hit = self._idle_session(deadline)
        if not hit:
            self.log("IDLE 会话保活周期到，兜底查询后重开")
        return hit

    def _idle_session(self, outer_deadline):
        """一个 IDLE 会话周期。返回 True=命中事件；False=到本会话上限未命中。"""
        tag = self._idle_begin()
        if tag is None:
            time.sleep(POLL_FALLBACK_SECONDS)
            return True
        session_deadline = min(outer_deadline, time.time() + IDLE_KEEPALIVE_SECONDS)
        buf = b""
        sock = self.imap.socket()
        hit = False
        try:
            while time.time() < session_deadline and not hit:
                # 超时按剩余时间收窄：无事件时 recv 最多阻塞到 deadline 即醒，
                # 否则会睡满 IDLE_WAKE_SECONDS（20s）把合并窗口/收起时限撑爆
                remaining = session_deadline - time.time()
                sock.settimeout(max(0.5, min(IDLE_WAKE_SECONDS, remaining)))
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
        """调 dashboard_control.ps1 命令（-Wait 排队等轮播让锁）。

        返回 True=成功；"locked"=会话锁定被闸门跳过（静默推迟，不算错误）；
        "device"=设备未连接（渲染前预检，不算错误，插回后重试）；False=真失败。
        """
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
        if result.returncode == 3:
            return "locked"   # control.ps1 锁屏闸门：屏幕暂停，解锁后补
        if result.returncode == 4:
            return "device"   # 渲染前预检发现设备未连接：不必按失败刷错误日志
        tail = (result.stdout or result.stderr or "").strip().splitlines()[-3:]
        self.log(f"ERROR control.ps1 {command} 退出码 {result.returncode} :: {' | '.join(tail)}")
        return False

    @staticmethod
    def _session_locked():
        """锁屏检测：LogonUI.exe 仅在锁屏/登录界面运行（与 control.ps1 同判据）。"""
        if os.environ.get("EPD_FORCE_LOCKED"):
            return True   # 自动化测试钩子：与 control.ps1 Test-SessionLocked 同源
        return _process_running("LogonUI.exe")

    def _watch_lock(self):
        """锁屏监视线程（独立于 IMAP 主循环，2s 轮询）。

        锁定瞬间推"显示已暂停"大弹窗（pauselock，闸门豁免）盖住当前画面；
        解锁瞬间推回 pause_base.png 像素级还原。状态以底图文件存在性为唯一
        事实源（每轮直接查文件）——手动/旁路调用 pauselock、守护重启、崩溃
        中断等任何路径造成的漂移都会在下一轮自动纠正，维持不变式
        "锁定⇒覆盖层在屏；未锁定⇒底图不存在"。失败按 2s→60s 退避重试。
        """
        fails = 0
        announced_lock = False
        while True:
            time.sleep(min(60.0, 2.0 * (fails + 1)) if fails else 2.0)
            try:
                locked = self._session_locked()
                overlay_on_screen = PAUSE_BASE_PNG.exists()
                if locked and not overlay_on_screen:
                    if not announced_lock:
                        self.log("检测到锁屏：推送暂停覆盖层")
                        announced_lock = True
                    if self._run_control("pauselock") is True:
                        fails = 0
                        self.log("锁屏暂停覆盖层已上屏")
                    else:
                        fails += 1
                elif not locked and overlay_on_screen:
                    announced_lock = False
                    if self._run_control("resume") is True:
                        fails = 0
                        self.log("已解锁：锁屏前画面已还原")
                    else:
                        fails += 1
                else:
                    fails = 0
                    if not locked:
                        announced_lock = False
            except Exception as exc:
                self.log(f"锁屏监视异常: {exc!r}")
                fails += 1

    def _defer(self, seconds):
        """推迟 seconds 后再试：主循环按 defer_until 等待，不做忙等。"""
        self.defer_until = time.monotonic() + seconds

    def _defer_locked(self, message):
        """锁屏导致的推迟：仍锁定时按 LOCKED_DEFER_WAKE_S 周期重查，解锁即结束等待。
        一次锁屏只记一条日志。

        背景（2026-11 实测）：旧实现被闸门拒绝后保留队列但不等待，而 wait_events 在
        推送/收起到期时直接短路返回，两者叠加成约每秒一轮的忙循环——每轮拉起
        powershell 并对 IMAP 做 SELECT+SEARCH，锁屏多久跑多久（4 天 7018 次）。"""
        if not self.deferred_locked:
            self.log(message)
        self.deferred_locked = True
        self._defer(LOCKED_DEFER_WAKE_S)

    def deferred_in(self):
        """距离可以重试推送/收起还有多少秒（到点为 0）。锁屏导致的推迟在解锁瞬间结束。"""
        if self.deferred_locked and not self._session_locked():
            self.deferred_locked = False
            self.defer_until = 0.0
        return max(0.0, self.defer_until - time.monotonic())

    def _push_due_in(self):
        """距离"可以推屏"还有多少秒。

        正常到期 = 合并窗口（最后一封到达后再等 batch_window 收拢突发）与最小推送
        间隔（距上次成功推送 min_push_gap，防刷屏）中较晚者；最长积压 max_pending
        是硬上限（持续滴灌时强制推，可越过最小间隔），两者取较早。
        推迟重试中（锁屏/失败）不早于 defer_until。
        """
        if not self.pending:
            return float(IDLE_MAX_SECONDS)
        now = time.time()
        normal_due = max(self.last_arrival + self.cfg["batch_window_seconds"],
                         self.last_push + self.cfg["min_push_gap_seconds"])
        hard_deadline = self.first_pending + self.cfg["max_pending_seconds"]
        return max(0.0, min(normal_due, hard_deadline) - now, self.deferred_in())

    def maybe_push(self):
        if not self.pending or self._push_due_in() > 0:
            return
        if self._session_locked():
            # 锁屏闸门会拒绝渲染推送：本地先判，不白起 powershell；解锁后自动补推
            self._defer_locked("会话锁定中，弹窗推迟（解锁后自动补推）")
            return
        payload = {
            "account": self.account,
            "total_new": len(self.pending),
            "mails": self.pending[-self.cfg["max_show"]:][::-1],  # 最新在前
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "overlay_seconds": int(self.cfg.get("overlay_seconds") or 600),  # 弹窗页脚据此显示收起时间
        }
        tmp = MAIL_INBOX_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(MAIL_INBOX_FILE)
        self.log(f"推送邮件弹窗：{len(self.pending)} 封（展示 {len(payload['mails'])}）")
        result = self._run_control("mail")
        if result is True:
            self.deferred_locked = False
            self.log("弹窗上屏完成")
            self.pending = []
            self.first_pending = 0.0
            self.last_push = time.time()
            self._arm_dismiss()
        elif result == "locked":
            # 本地判定之后才锁屏（竞态）：同样推迟
            self._defer_locked("会话锁定中，弹窗推迟（解锁后自动补推）")
        elif result == "device":
            # 设备未连接：队列保留，按最小推送间隔节流重试（插回后自动补推）
            self.last_push = time.time()
            self.log("设备未连接，弹窗推迟（插回后重试）")
        else:
            # 失败也刷新 last_push：重试按最小推送间隔节流，不连续轰击
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
        if not self.overlay_until or time.time() < self.overlay_until or self.deferred_in() > 0:
            return
        if self._session_locked():
            # 锁屏闸门会拒绝推送：本地先判，不白起 powershell；解锁后自动还原
            self._defer_locked("会话锁定中，收起推迟（解锁后自动还原）")
            return
        if not MAIL_BASE_PNG.exists():
            # 底图已被收起流程删除（M5 手动收起后 cli 会删底图）：屏已还原，
            # 直接清状态即可，不再起 powershell、不再刷屏
            self.log("弹窗已被手动收起（底图不存在），定时收起跳过")
            self.overlay_until = 0.0
            self.overlay_page = None
            self._save_state()
            return
        current = self._read_page_state()
        if current != self.overlay_page:
            self.log(f"弹窗期间页面已流转（{self.overlay_page}→{current}），跳过还原")
            self.overlay_until = 0.0
            self.overlay_page = None
            self._save_state()
            return
        result = self._run_control("mailoff")
        if result == "locked":
            # 本地判定之后才锁屏（竞态）：同样推迟
            self._defer_locked("会话锁定中，收起推迟（解锁后自动还原）")
            return
        if result == "device":
            self._defer(CONTROL_RETRY_S)
            self.log("设备未连接，收起推迟（插回后重试）")
            return
        if result is not True:
            self._defer(CONTROL_RETRY_S)   # 失败不立刻重来，否则会每秒拉起一次 powershell
            self.log(f"mailoff 失败，{CONTROL_RETRY_S} 秒后重试收起")
            return
        self.log("弹窗已收起，被覆盖页还原完成")
        self.deferred_locked = False
        self.overlay_until = 0.0
        self.overlay_page = None
        self._save_state()

    # ---------- 主循环 ----------
    def run(self):
        self.log(f"邮件监控启动 account={self.account} watermark={self.watermark}"
                 + (f" 续期弹窗(至{time.strftime('%H:%M:%S', time.localtime(self.overlay_until))}"
                    f" 基准页{self.overlay_page})" if self.overlay_until else ""))
        threading.Thread(target=self._watch_lock, daemon=True,
                         name="lock-watcher").start()
        while True:
            try:
                if self.imap is None:
                    self.connect()
                    self.catchup()
                # 唤醒上限取三者最小：IDLE 协议上限 / 下次可推送时刻 / 弹窗收起时刻；
                # 推迟重试中（锁屏/失败）不早于 defer_until——到期即短路返回的 wait_events
                # 配上不等待的重试就是忙循环
                wake_in = self._push_due_in()
                if self.overlay_until:
                    wake_in = min(wake_in, max(1.0, self.overlay_until - time.time()))
                wake_in = max(wake_in, self.deferred_in())
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
            for name, step in (("maybe_push", self.maybe_push),
                               ("maybe_dismiss", self.maybe_dismiss)):
                # 状态文件被占用/权限等异常不该杀死守护：pythonw 后台无提示，也没有
                # 任何机制会把它重新拉起来——记日志，下轮重试
                try:
                    step()
                except Exception as exc:
                    self.log(f"{name} 异常，下轮重试: {exc!r}")


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------- 单实例 pid 锁 ----------
def _pid_alive(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def _pid_is_other_program(pid):
    """pid 还活着、但已经不是 python 进程（系统复用了 pid）时返回 True。
    是 python、进程不存在或无法判定都返回 False（拿不准就保守地认为锁有效）。"""
    image = _process_image(pid)
    return bool(image) and not image.lower().startswith("python")


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
            # pid 被系统复用给别的程序时，锁文件只是上次异常退出的残留，不能因此拒绝启动：
            # 开机登录时 pid 复用很常见，否则守护会静默不启动（既没邮件弹窗也没锁屏暂停）
            if pid and _pid_alive(pid) and not _pid_is_other_program(pid):
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


def _portrait_operation():
    """当前是否为竖版运营（switch_orientation.py 写的方向标记）。

    邮件监控只有横版：邮件弹窗与锁屏暂停层都只有横版渲染器。登录自启脚本不分方向都会
    拉起本进程，竖版运营期间它往屏上推的就是横着画面——这里直接退出；切回横版时由
    switch_orientation.py 重新拉起。"""
    try:
        marker = (BASE_DIR.parent / "ACTIVE_ORIENTATION.txt").read_text(encoding="ascii")
    except (OSError, ValueError):
        return False          # 没有标记文件（从未切换过方向）= 默认横版
    return marker.strip() == "portrait"


def main():
    if _portrait_operation():
        _log_write("当前为竖版运营，邮件监控不启动（切回横版后由 switch_orientation.py 重新拉起）")
        print("portrait operation: mail monitor not started", file=sys.stderr)
        return
    cfg = load_config()
    with _PidLock(BASE_DIR / "mail_monitor.lock"):
        MailMonitor(cfg).run()


if __name__ == "__main__":
    main()
