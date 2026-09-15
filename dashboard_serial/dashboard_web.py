#!/usr/bin/env python3
# dashboard_web.py — 墨水屏局域网 Web 控制台
# 手机/平板浏览器直接推送单页、更新模块、修改计划，无需到电脑上跑脚本。
# 页面资源在 web/index.html + web/app.js，与服务器逻辑分离。
# 用法: python dashboard_web.py [--port 8080]
import argparse
import json
import logging
import os
import socket
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONTROL_PS1 = SCRIPT_DIR / "dashboard_control.ps1"
PREVIEW_PNG = SCRIPT_DIR / "dashboard_preview.png"
HOTKEY_STATUS = SCRIPT_DIR / "hotkeys_status.json"
PAGE_STATE = SCRIPT_DIR / "page_state.json"
DASHBOARD_CACHE = SCRIPT_DIR / "dashboard_data.json"
LOG_FILE = SCRIPT_DIR / "web_console.log"
WEB_DIR = SCRIPT_DIR / "web"
INDEX_HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")
APP_JS = (WEB_DIR / "app.js").read_text(encoding="utf-8")

# 动作 -> dashboard_control.ps1 命令。只收 UI 实际使用的动作：
# 单模块强制刷新（weather/agentplan/news/markets）与 test_white 已删——
# 与"切页 + force"及"清屏"重复；CLI 里这些命令仍可用，只是不走 Web。
ACTION_CMD = {
    "refresh": "refresh",
    "plans": "plans",       # 修改计划卡片经 /api/plans 间接使用
    "page1": "page1",
    "page2": "page2",
    "page3": "page3",
    "page4": "page4",
    "analysis": "analysis",
    "page5": "page5",
    "stock": "stock",
    "clear": "clear",
    "preview": "preview",
    "preview_page4": "preview",
    "test_info": "test",
    "test_chess": "test",
    "test_black": "test",
}
ACTION_LABEL = {
    "refresh": "完整刷新",
    "plans": "更新计划",
    "page1": "切到今日看板", "page2": "切到热点新闻", "page3": "切到行情",
    "page4": "切到认知洞察", "analysis": "重新生成认知洞察",
    "page5": "切到智谱AI", "stock": "重新生成智谱AI分析",
    "clear": "清屏", "preview": "渲染预览",
    "preview_page4": "预览认知洞察",
    "test_info": "测试·信息卡", "test_chess": "测试·棋盘格", "test_black": "测试·全黑",
}

_state = {
    "running": False,
    "action": "",       # 正在运行的动作（空闲时为空）
    "last_action": "",  # 最近一次完成的动作，前端据此在 preview 完成后展示预览图
    "ok": None,
    "log": [],
}
_state_lock = threading.Lock()
MAX_LOG_LINES = 500


def get_lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def hotkey_status():
    try:
        # utf-8-sig 兼容带/不带 BOM 两种写入方
        return json.loads(HOTKEY_STATUS.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"state": "unknown", "message": "热键服务未运行或状态文件不存在"}

def current_page():
    try:
        # page_state.json 由 PowerShell Set-Content 写入、带 UTF-8 BOM，必须用 utf-8-sig 读
        data = json.loads(PAGE_STATE.read_text(encoding="utf-8-sig"))
        return data.get("page", 1)
    except Exception:
        return 1


def insight_status(now=None):
    try:
        data = json.loads(DASHBOARD_CACHE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"available": False, "message": "暂无页4缓存，先切换到页4或生成解读"}
    analysis = data.get("analysis")
    if not isinstance(analysis, dict) or analysis.get("kind") not in ("insight", "psychology"):
        return {"available": False, "message": "页4尚未生成认知洞察"}
    try:
        generated_at = datetime.fromisoformat(analysis.get("generated_at"))
        age_minutes = max(0, round(((now or datetime.now()) - generated_at).total_seconds() / 60, 1))
        fresh = age_minutes < 24 * 60
    except (TypeError, ValueError):
        age_minutes = None
        fresh = False
    return {
        "available": True,
        "domain": analysis.get("domain", ""),
        "topic": analysis.get("topic", ""),
        "text": analysis.get("text", ""),
        "model": analysis.get("model", ""),
        "updated": analysis.get("updated", ""),
        "generated_at": analysis.get("generated_at", ""),
        "stale": bool(analysis.get("stale")),
        "fresh": fresh,
        "age_minutes": age_minutes,
        "history_count": len(analysis.get("topic_history", analysis.get("recent_topics", []))),
        "recent_topics": analysis.get("recent_topics", []),
        "prompt_tokens": analysis.get("prompt_tokens"),
        "completion_tokens": analysis.get("completion_tokens"),
    }


def append_log(line):
    with _state_lock:
        _state["log"].append(line)
        if len(_state["log"]) > MAX_LOG_LINES:
            del _state["log"][: len(_state["log"]) - MAX_LOG_LINES]


def run_action(action, pattern=None, planstext=None, force=False):
    """后台执行 dashboard_control.ps1 动作；同一时间只允许一个动作。

    force=True 透传 -Force：page1-5 跳过切页缓存 TTL，强制联网刷新数据。
    """
    with _state_lock:
        if _state["running"]:
            return False
        _state["running"] = True
        _state["action"] = action
        _state["ok"] = None
        _state["log"] = []
    label = ACTION_LABEL.get(action, action)

    def worker():
        append_log(f"[{time.strftime('%H:%M:%S')}] 开始：{label}{'（强制联网）' if force else ''}")
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(CONTROL_PS1), ACTION_CMD.get(action, action)]
        if pattern:
            cmd += ["-Pattern", pattern]
        if planstext:
            cmd += ["-PlansText", planstext]
        if force:
            cmd += ["-Force"]
        if action == "preview_page4":
            cmd += ["-RenderMode", "insight", "-Page", "4"]
        ok = False
        skipped = False
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(SCRIPT_DIR), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    append_log(line)
                    if "another instance holds the mutex" in line:
                        skipped = True
            proc.wait()
            ok = proc.returncode == 0 and not skipped
        except Exception as exc:
            append_log(f"[错误] {exc}")
        finally:
            with _state_lock:
                _state["running"] = False
                _state["ok"] = ok
                _state["action"] = ""
                _state["last_action"] = action
            append_log(f"[{time.strftime('%H:%M:%S')}] 完成：{'成功' if ok else '失败'}")
            if skipped:
                append_log("提示：已有其他渲染/推送任务占用互斥锁，本次操作未执行。")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return True


def validate_plans(items):
    cleaned = [str(i).strip() for i in items if str(i).strip()]
    if not cleaned:
        return None, "至少输入一个计划"
    if len(cleaned) > 5:
        return None, "最多 5 个计划（屏幕显示上限）"
    return cleaned, None


class Handler(BaseHTTPRequestHandler):
    server_version = "EPDWeb/1.0"

    def log_message(self, fmt, *args):
        pass  # 静默默认访问日志

    def _send_bytes(self, body, content_type, code=200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, code=200):
        self._send_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8", code)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            html = INDEX_HTML.replace("{{PORT}}", str(self.server.server_port))
            self._send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")
        elif parsed.path == "/app.js":
            self._send_bytes(APP_JS.encode("utf-8"), "application/javascript; charset=utf-8")
        elif parsed.path == "/api/status":
            with _state_lock:
                running = _state["running"]
                action = _state["action"]
                last_action = _state["last_action"]
                ok = _state["ok"]
                log = list(_state["log"])
            self._send_json({
                "running": running,
                "action": action,
                "label": ACTION_LABEL.get(action, action),
                "last_action": last_action,
                "ok": ok,
                "log": log[-200:],
                "page": current_page(),
                "page4": insight_status(),
                "hotkeys": hotkey_status(),
            })
        elif parsed.path == "/preview.png":
            # 渲染进程用 tmp+rename 原子替换预览图；这里读到异常（半截/正被替换）时按无图处理
            try:
                body = PREVIEW_PNG.read_bytes()
            except Exception:
                body = None
            if body:
                self._send_bytes(body, "image/png")
            else:
                self._send_json({"ok": False, "message": "暂无预览图"}, 404)
        else:
            self._send_json({"ok": False, "message": "not found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/action":
            data = self._read_json()
            action = str(data.get("action", "")).strip()
            if action not in ACTION_CMD:
                self._send_json({"ok": False, "message": f"未知动作: {action}"}, 400)
                return
            pattern = action.split("_", 1)[1] if action.startswith("test_") else None
            force = bool(data.get("force"))
            started = run_action(action, pattern=pattern, force=force)
            if not started:
                self._send_json({"ok": False, "message": "已有任务运行中，请稍候"}, 409)
                return
            self._send_json({"ok": True})
        elif parsed.path == "/api/plans":
            data = self._read_json()
            items, err = validate_plans(data.get("items", []))
            if err:
                self._send_json({"ok": False, "message": err}, 400)
                return
            started = run_action("plans", planstext=";".join(items))
            if not started:
                self._send_json({"ok": False, "message": "已有任务运行中，请稍候"}, 409)
                return
            self._send_json({"ok": True, "items": items})
        else:
            self._send_json({"ok": False, "message": "not found"}, 404)


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    ap = argparse.ArgumentParser(description="墨水屏局域网 Web 控制台")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    # pythonw 后台运行无控制台，日志落文件；已存在实例时明确退出而不是 bind 崩溃静默死亡
    logging.basicConfig(
        filename=LOG_FILE, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8",
    )
    if port_in_use(args.port):
        msg = f"端口 {args.port} 已被占用（Web 控制台已在运行？），本次启动退出。"
        print(msg, flush=True)
        logging.error(msg)
        return
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    lan_ip = get_lan_ip()
    logging.info("web console started on %s:%s pid=%s", args.host, args.port, os.getpid())
    print("=" * 54, flush=True)
    print("  墨水屏 Web 控制台已启动")
    print(f"  本机访问:  http://127.0.0.1:{args.port}", flush=True)
    print(f"  局域网访问: http://{lan_ip}:{args.port}  (手机/平板需连同一 Wi-Fi)", flush=True)
    print("  关闭: 按 Ctrl+C", flush=True)
    print("  若手机打不开，请放行防火墙端口：", flush=True)
    print(f"    netsh advfirewall firewall add rule name=\"EPD Web\" dir=in action=allow protocol=TCP localport={args.port}", flush=True)
    print("=" * 54, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        logging.info("web console stopped")
        server.server_close()


if __name__ == "__main__":
    main()
