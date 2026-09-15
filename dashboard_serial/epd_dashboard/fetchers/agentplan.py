"""火山方舟 Agent Plan 额度：arkcli 直连优先，data.js 缓存兜底，SSO 失效自动拉起登录。"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from epd_dashboard.config import AGENT_PLAN_DATA_FILE, AGENT_PLAN_ENABLED, BASE_DIR

LOGIN_TRIGGER_FILE = BASE_DIR / "arkcli_login_triggered.json"
ARKCLI_CMD = shutil.which("arkcli.cmd") or shutil.which("arkcli") or "arkcli"
LOGIN_COOLDOWN_SECONDS = 300


def _items(payload):
    """兼容两种返回结构：data.js 的 {data:{items}} 与 arkcli 直出的 {items}。"""
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(payload.get("items"), list):
        return payload["items"]
    return []


def parse_agent_plan(payload):
    items = [item for item in _items(payload) if item.get("subscribed")]
    if not items:
        raise RuntimeError("No subscribed Agent Plan item")
    periods = {period["label"]: period for period in items[0].get("periods", [])}
    output = {}
    for label, title in (("5h", "5小时"), ("weekly", "周额度"), ("monthly", "月额度")):
        period = periods.get(label)
        if not period:
            raise RuntimeError(f"Missing Agent Plan period: {label}")
        total = period["total"]
        remaining = max(0.0, total - period.get("used", 0))
        reset_at = period.get("reset_at")
        if not reset_at:
            reset = datetime.now() + timedelta(hours=5)
        else:
            reset = datetime.fromisoformat(reset_at)
        reset_text = reset.strftime("%H:%M") if label == "5h" else reset.strftime("%m/%d")
        output[title] = {
            "remaining": remaining,
            "total": total,
            "percent": round(remaining / total * 100),
            "reset": reset_text,
        }
    return output


def _sso_login_failed(message):
    markers = (
        "session expired",
        "requires Volcengine Ark SSO STS",
        "arkcli auth login volc-sso",
    )
    return any(marker in message for marker in markers)


def _trigger_sso_login():
    try:
        state = json.loads(LOGIN_TRIGGER_FILE.read_text(encoding="utf-8"))
        triggered_at = datetime.fromisoformat(state["triggered_at"])
        if (datetime.now() - triggered_at).total_seconds() < LOGIN_COOLDOWN_SECONDS:
            return
    except Exception:
        pass
    LOGIN_TRIGGER_FILE.write_text(
        json.dumps({"triggered_at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False),
        encoding="utf-8",
    )
    subprocess.Popen(
        [ARKCLI_CMD, "auth", "login", "volc-sso"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True,
    )


def _from_arkcli():
    """直接调用 arkcli 实时获取额度，保证与命令行结果一致。"""
    proc = subprocess.run(
        [ARKCLI_CMD, "usage", "plan", "--product", "agent-plan", "--format", "json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip() or "arkcli failed")
    payload = json.loads(proc.stdout)
    items = payload.get("items") or []
    errors = [str(item.get("error")) for item in items if item.get("error")]
    if errors:
        raise RuntimeError("; ".join(errors))
    if not items:
        raise RuntimeError("arkcli returned no Agent Plan item")
    return payload


def _from_datajs():
    text = AGENT_PLAN_DATA_FILE.read_text(encoding="utf-8")
    marker = "window.ARK_USAGE = "
    if marker in text:
        text = text.split(marker, 1)[1]
    if text.rstrip().endswith(";"):
        text = text.rstrip()[:-1]
    payload = json.loads(text.strip())
    if payload.get("ok") is False:
        raise RuntimeError(payload.get("error") or "Agent Plan data.js not ok")
    if not _items(payload):
        raise RuntimeError("data.js has no Agent Plan item")
    return payload


def fetch_agent_plan():
    """优先实时调用 arkcli，失败时回退到 AgentPlan 看板的 data.js 缓存。"""
    if not AGENT_PLAN_ENABLED:
        raise RuntimeError("Agent Plan integration disabled; set EPD_AGENT_PLAN_ENABLED=1 to enable it")
    try:
        return parse_agent_plan(_from_arkcli())
    except Exception as exc:
        message = str(exc)
        if _sso_login_failed(message):
            print("[提醒] 检测到 Agent Plan 登录态失效，已自动打开火山登录窗口；完成登录后额度将恢复实时刷新。", flush=True)
            _trigger_sso_login()
        try:
            result = parse_agent_plan(_from_datajs())
            print("[提示] Agent Plan 已临时使用本地缓存 data.js，登录成功后会自动恢复最新数据。", flush=True)
            return result
        except Exception:
            raise exc
