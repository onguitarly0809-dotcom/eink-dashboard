#!/usr/bin/env python3
"""墨水屏局域网 Web 控制台（横竖共用）。

手机/平板浏览器直接推送单页、更新模块、修改计划，无需到电脑上跑脚本。
页面资源在各运营变体目录的 web/index.html + web/app.js（两版 UI 不同），
启动时读入内存，改动需重启。用法: python dashboard_web.py [--port 8080]

横竖行为差异全部由 config.VARIANT 分支：
- 横版：基础动作 + 切换竖版运营（switch_portrait）；
- 竖版：基础动作 + 页6 天气整页 + 切换横版运营 + 横版六页预览/推送互看
  （依赖兄弟目录 dashboard_serial_landscape 存在）。
"""
import argparse
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from epd_dashboard.config import (
    BASE_DIR,
    INSIGHT_ARCHIVE_DIR,
    VARIANT,
)

REPO_ROOT = BASE_DIR.parent
CONTROL_PS1 = BASE_DIR / "dashboard_control.ps1"
PREVIEW_PNG = BASE_DIR / "dashboard_preview.png"
HOTKEY_STATUS = BASE_DIR / "hotkeys_status.json"
PAGE_STATE = BASE_DIR / "page_state.json"
DASHBOARD_CACHE = BASE_DIR / "dashboard_data.json"
LOG_FILE = BASE_DIR / "web_console.log"
WEB_DIR = BASE_DIR / "web"
INDEX_HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")
APP_JS = (WEB_DIR / "app.js").read_text(encoding="utf-8")

# 渲染入口（本变体目录的薄引导脚本）
RENDER_PY = BASE_DIR / "render_dashboard.py"
# 一键切换横竖版：切换脚本在仓库根（横竖两变体共用）
SWITCH_PY = REPO_ROOT / "switch_orientation.py"

# 临时新闻任务（fetchers/news.py 的文件驱动机制）
TEMP_TASK_FILE = BASE_DIR / "temp_news_task.json"

# 竖版专属：页6 天气整页 + 横版兄弟目录互看
IS_PORTRAIT = VARIANT == "portrait"
PAGE6_PREVIEW = BASE_DIR / "dashboard_page6_preview.png"
LANDSCAPE_DIR = REPO_ROOT / "dashboard_serial_landscape"
LANDSCAPE_AVAILABLE = IS_PORTRAIT and (LANDSCAPE_DIR / "render_dashboard.py").exists()
LANDSCAPE_RENDER = LANDSCAPE_DIR / "render_dashboard.py"
LANDSCAPE_PREVIEW = LANDSCAPE_DIR / "dashboard_preview.png"
LANDSCAPE_MODES = {1: "today", 2: "news", 3: "markets", 4: "insight", 5: "stock"}

# 动作 -> dashboard_control.ps1 命令。只收 UI 实际使用的动作：
# 单模块强制刷新（weather/news/markets）与 test_white 已删——
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

if IS_PORTRAIT:
    ACTION_LABEL.update({
        "page6": "推送页6·天气整页", "preview_page6": "预览页6·天气整页",
        "switch_landscape": "切换横版运营",
    })
    if LANDSCAPE_AVAILABLE:
        ACTION_LABEL["switch_landscape"] = "切换横版运营"
        for _n, _label in ((1, "今日"), (2, "新闻"), (3, "行情"), (4, "洞察"), (5, "智谱AI")):
            ACTION_LABEL[f"landscape_preview_{_n}"] = f"横版预览·页{_n}{_label}"
            ACTION_LABEL[f"landscape_push_{_n}"] = f"横版推送·页{_n}{_label}"
else:
    ACTION_LABEL["switch_portrait"] = "切换竖版运营"

# python 直连路由的动作（不走 dashboard_control.ps1）：
# 页6 天气整页（竖版）+ 横版互看（竖版）+ 方向切换（两版各指对方）
PY_ACTIONS = {"switch_portrait"} if not IS_PORTRAIT else {"switch_landscape", "page6", "preview_page6"}
if IS_PORTRAIT and LANDSCAPE_AVAILABLE:
    PY_ACTIONS |= {f"landscape_preview_{n}" for n in LANDSCAPE_MODES}
    PY_ACTIONS |= {f"landscape_push_{n}" for n in LANDSCAPE_MODES}
KNOWN_ACTIONS = set(ACTION_CMD) | PY_ACTIONS

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


def _ps_mutex_wrap(py_cmd):
    """把跨目录/直连渲染推送包进 Global\EPD_Dashboard_Control 互斥锁：
    与 dashboard_control.ps1（计划任务/热键/CLI）同一把锁，避免并发推送串口握手错乱。
    参数逐个 PS 单引号转义——双引号/分号/空格都会被 PowerShell 拆坏。"""
    def q(a):
        # PS 单引号内的单引号写成两个；双引号要 \" 给原生命令行还原
        return "'" + str(a).replace("'", "''").replace('"', '\\"') + "'"
    inner = " ".join(q(a) for a in py_cmd)
    return [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "$m = New-Object System.Threading.Mutex($false, 'Global\\EPD_Dashboard_Control'); "
        "if (-not $m.WaitOne(0)) { Write-Output 'mutex busy: another dashboard task is running'; exit 1 } "
        "try { & " + inner + "; exit $LASTEXITCODE } "
        "finally { $m.ReleaseMutex() | Out-Null; $m.Dispose() }",
    ]


def _build_cmd(action, pattern, planstext, force):
    """返回 (cmd, cwd)。默认走 dashboard_control.ps1；直连动作走 python 入口。"""
    if action == "switch_portrait":
        return ([sys.executable, str(SWITCH_PY), "portrait"], str(REPO_ROOT))
    if action == "switch_landscape":
        return ([sys.executable, str(SWITCH_PY), "landscape"], str(REPO_ROOT))
    if action in ("page6", "preview_page6"):
        cmd = [sys.executable, str(RENDER_PY), "--mode", "weather", "--page", "6"]
        if action == "page6":
            cmd.append("--push")
            return _ps_mutex_wrap(cmd), str(BASE_DIR)
        return cmd, str(BASE_DIR)
    if action.startswith("landscape_"):
        kind, _, num = action.rpartition("_")
        mode = LANDSCAPE_MODES.get(int(num))
        if mode is None:
            raise ValueError(f"unknown landscape page: {action}")
        cmd = [sys.executable, str(LANDSCAPE_RENDER), "--mode", mode, "--page", num]
        if kind == "landscape_push":
            cmd.append("--push")
            return _ps_mutex_wrap(cmd), str(LANDSCAPE_DIR)
        return cmd, str(LANDSCAPE_DIR)
    # -Wait 150：用户动作遇轮播占锁时排队等待（带[排队]提示）而非立即失败；
    # 轮播一轮约1.5~2.5分钟，150s 覆盖绝大多数情况（2026-10-12 用户定稿）
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(CONTROL_PS1), ACTION_CMD.get(action, action), "-Wait", "150"]
    if pattern:
        cmd += ["-Pattern", pattern]
    if planstext:
        cmd += ["-PlansText", planstext]
    if force:
        cmd += ["-Force"]
    if action == "preview_page4":
        cmd += ["-RenderMode", "insight", "-Page", "4"]
    return cmd, str(BASE_DIR)


def run_action(action, pattern=None, planstext=None, force=False):
    """后台执行动作；同一时间只允许一个。

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
        try:
            cmd, cwd = _build_cmd(action, pattern, planstext, force)
        except ValueError as exc:
            with _state_lock:
                _state["running"] = False
                _state["ok"] = False
                _state["action"] = ""
                _state["last_action"] = action
            append_log(f"[错误] {exc}")
            return
        ok = False
        skipped = False
        try:
            proc = subprocess.Popen(
                cmd, cwd=cwd, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    append_log(line)
                    if "another instance holds the mutex" in line or line.startswith("mutex busy"):
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


# ---------- 只读数据面板：缓存 JSON + 串口探测 + 临时任务 + 洞察归档 ----------

def _read_cache():
    try:
        return json.loads(DASHBOARD_CACHE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


# 各模块缓存新鲜度上界（分钟）。与 config.TTL_MINUTES 对齐；行情盘中 3 分钟/收盘 60 分钟
# 的交易时段判定不在此复刻，展示用 60 分钟上界即可。
_FRESHNESS_TTL = {"weather": 30, "news": 10, "glm": 30, "markets": 60, "intraday": 10}


def _ages(data, now=None):
    now = now or datetime.now()
    ages = {}
    for mod, ttl in _FRESHNESS_TTL.items():
        fetched = ((data.get("_meta") or {}).get(mod) or {}).get("fetched_at")
        try:
            age = max(0.0, round(((now - datetime.fromisoformat(fetched)).total_seconds() / 60), 1))
        except (TypeError, ValueError):
            age = None
        ages[mod] = {"age_min": age, "ttl_min": ttl, "fresh": age is not None and age < ttl}
    return ages


def serial_ports():
    """COM 口列表 + CP210x（墨水屏驱动板 VID:PID 10C4:EA60）标记，结果缓存 30 秒。"""
    global _serial_ts, _serial_ports
    if time.time() - _serial_ts < 30:
        return _serial_ports
    ports = []
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            hwid = (p.hwid or "") + " " + (p.description or "")
            ports.append({
                "device": p.device,
                "desc": p.description or "",
                "epd": "10C4:EA60" in hwid.upper(),
            })
    except Exception:
        pass
    ports.sort(key=lambda x: x["device"])
    _serial_ports, _serial_ts = ports, time.time()
    return ports


_serial_ts, _serial_ports = 0.0, []


def overview_payload():
    data = _read_cache()
    glm = data.get("glm") or {}
    weather = data.get("weather") or {}
    stock = data.get("stock_analysis") or {}
    analysis = data.get("analysis") or {}
    return {
        "page": current_page(),
        "next_page": (current_page() % 5) + 1,
        "ages": _ages(data),
        "glm": {"level": glm.get("level"), "quotas": glm.get("quotas") or {}},
        "weather_now": {k: weather.get(k) for k in
                        ("temperature", "description", "high", "low", "feels", "wind",
                         "humidity", "city", "updated", "alert") if k in weather},
        "insight": {k: analysis.get(k) for k in ("topic", "domain", "updated", "stale") if k in analysis},
        "stock": {k: stock.get(k) for k in ("price", "pct", "updated", "stale") if k in stock},
        "hotkeys": hotkey_status(),
        "serial": serial_ports(),
        "temp_task": temp_task_summary(),
        "plans": data.get("plans") or [],
    }


def data_payload():
    data = _read_cache()
    weather = dict(data.get("weather") or {})
    hourly = weather.get("hourly") or {}
    if hourly:  # 36 点只取前 24，Web 一天的走势足够
        weather["hourly"] = {k: (v[:24] if isinstance(v, list) else v) for k, v in hourly.items()}
    news = data.get("news") or {}
    news = {k: news.get(k) for k in (
        "updated", "domestic", "international", "ai", "stale",
        "domestic_source", "international_source", "ai_source",
        "domestic_pinned", "international_pinned", "ai_pinned",
        "domestic_badge", "international_badge", "ai_badge", "summaries")}
    markets = data.get("markets") or {}
    markets = {k: markets.get(k) for k in ("companies", "quotes", "sectors", "updated", "stale")}
    return {
        "weather": weather,
        "news": news,
        "markets": markets,
        "intraday": data.get("intraday") or {},
        "glm": data.get("glm") or {},
    }


def temp_task_summary():
    try:
        task = json.loads(TEMP_TASK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(task, dict):
        return None
    return {k: task.get(k) for k in
            ("enabled", "query", "match", "require_price", "band", "badge", "last_hit")}


TEMP_BANDS = {"domestic": "国内", "international": "国际", "ai": "AI"}


def temp_task_save(payload):
    """校验并写 temp_news_task.json。字段语义与 fetchers/news.py 注释一致。"""
    if not isinstance(payload, dict):
        return "任务格式错误"
    query = str(payload.get("query", "")).strip()
    match = str(payload.get("match", "")).strip()
    if not query:
        return "搜索词不能为空"
    if not match:
        return "标题匹配正则不能为空"
    try:
        re.compile(match, re.IGNORECASE)
    except re.error as exc:
        return f"正则无效：{exc}"
    band = str(payload.get("band", "domestic"))
    if band not in TEMP_BANDS:
        return "置顶栏目必须是 domestic/international/ai"
    task = {
        "enabled": bool(payload.get("enabled", True)),
        "query": query,
        "match": match,
        "require_price": bool(payload.get("require_price", True)),
        "band": band,
        "badge": str(payload.get("badge", "价")).strip()[:4] or "价",
    }
    # 保留历史命中（粘性置顶依赖 last_hit 跨刷新存续）
    old = temp_task_summary()
    if old and old.get("last_hit"):
        task["last_hit"] = old["last_hit"]
    try:
        TEMP_TASK_FILE.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        return f"写入失败：{exc}"
    return None


def temp_task_stop():
    old = temp_task_summary()
    if not old:
        return "当前没有任务"
    task = dict(old)
    task["enabled"] = False
    try:
        TEMP_TASK_FILE.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        return f"写入失败：{exc}"
    return None


def insight_archive_list():
    """Obsidian 归档目录下的洞察笔记清单（mtime 倒序，最多 60 条）。"""
    if not INSIGHT_ARCHIVE_DIR.is_dir():
        return []
    items = []
    for f in INSIGHT_ARCHIVE_DIR.glob("*.md"):
        try:
            items.append({"name": f.name, "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="minutes")})
        except OSError:
            continue
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:60]


def insight_archive_read(name):
    """读单个归档笔记。仅允许归档目录直下的 .md，杜绝路径穿越。"""
    if not name.endswith(".md") or "/" in name or "\\" in name or name.startswith("."):
        return None, "非法文件名"
    path = (INSIGHT_ARCHIVE_DIR / name).resolve()
    if path.parent != INSIGHT_ARCHIVE_DIR.resolve() or not path.is_file():
        return None, "文件不存在"
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as exc:
        return None, f"读取失败：{exc}"


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
        elif parsed.path == "/api/overview":
            self._send_json(overview_payload())
        elif parsed.path == "/api/data":
            self._send_json(data_payload())
        elif parsed.path == "/api/tempnews":
            self._send_json({"task": temp_task_summary(), "bands": TEMP_BANDS})
        elif parsed.path == "/api/insights":
            # urlparse().path 不含查询串，文件读取必须按 query 参数分流
            qs = urllib.parse.parse_qs(parsed.query)
            req_file = (qs.get("file") or [""])[0]
            if req_file:
                content, err = insight_archive_read(req_file)
                if err:
                    self._send_json({"ok": False, "message": err}, 400)
                else:
                    self._send_json({"ok": True, "name": req_file, "content": content})
                return
            analysis = self._read_analysis() or {}
            stock = {}
            try:
                stock = json.loads(DASHBOARD_CACHE.read_text(encoding="utf-8-sig")).get("stock_analysis") or {}
            except Exception:
                pass
            stock = {k: stock.get(k) for k in ("text", "model", "price", "pct", "updated", "stale", "web_search")}
            self._send_json({
                "archive": insight_archive_list(),
                "topic_history": analysis.get("topic_history"),
                "stock": stock,
            })
        elif parsed.path == "/preview.png":
            self._serve_png(PREVIEW_PNG)
        elif IS_PORTRAIT and parsed.path == "/preview_page6.png":
            self._serve_png(PAGE6_PREVIEW)
        elif IS_PORTRAIT and parsed.path == "/preview_landscape.png":
            self._serve_png(LANDSCAPE_PREVIEW)
        else:
            self._send_json({"ok": False, "message": "not found"}, 404)

    def _serve_png(self, path):
        # 渲染进程用 tmp+rename 原子替换预览图；这里读到异常（半截/正被替换）时按无图处理
        try:
            body = path.read_bytes()
        except Exception:
            body = None
        if body:
            self._send_bytes(body, "image/png")
        else:
            self._send_json({"ok": False, "message": "暂无预览图"}, 404)

    @staticmethod
    def _read_analysis():
        try:
            return json.loads(DASHBOARD_CACHE.read_text(encoding="utf-8-sig")).get("analysis")
        except Exception:
            return None

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/action":
            data = self._read_json()
            action = str(data.get("action", "")).strip()
            if action not in KNOWN_ACTIONS:
                self._send_json({"ok": False, "message": f"未知动作: {action}"}, 400)
                return
            pattern = action.split("_", 1)[1] if action.startswith("test_") else None
            force = bool(data.get("force"))
            started = run_action(action, pattern=pattern, force=force)
            if not started:
                self._send_json({"ok": False, "message": "已有任务运行中，请稍候"}, 409)
                return
            self._send_json({"ok": True})
        elif parsed.path == "/api/tempnews":
            data = self._read_json()
            op = str(data.get("op", ""))
            if op == "stop":
                err = temp_task_stop()
            elif op == "save":
                err = temp_task_save(data.get("task"))
            else:
                err = "op 必须是 save 或 stop"
            if err:
                self._send_json({"ok": False, "message": err}, 400)
                return
            self._send_json({"ok": True, "task": temp_task_summary()})
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
    logging.info("web console (%s) started on %s:%s pid=%s", VARIANT, args.host, args.port, os.getpid())
    print("=" * 54, flush=True)
    print(f"  墨水屏 Web 控制台已启动（{'横版' if not IS_PORTRAIT else '竖版'}运营目录 {BASE_DIR}）")
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
