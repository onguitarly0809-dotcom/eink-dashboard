#!/usr/bin/env python3
"""Global hotkey bridge for the e-paper dashboard.

Map Keychron Launcher physical keys M1-M5 to F13-F17, then run this
script (normally via pythonw from Startup). It posts page1-page5 to the
dashboard web API even when the browser is not focused.
"""
import argparse
import ctypes
import datetime
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from ctypes import wintypes

user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312
VK_F13 = 0x7C
VK_F14 = 0x7D
VK_F15 = 0x7E
VK_F16 = 0x7F
VK_F17 = 0x80
# 同一键 500ms 内重复触发（按住/键盘重发）只算一次
DEBOUNCE_SECONDS = 0.5

SCRIPT_DIR = Path(__file__).resolve().parent
STATUS_PATH = SCRIPT_DIR / "hotkeys_status.json"
# F16/F17 供 Keychron Launcher 把 M4/M5 物理键映射过来；未映射时注册了也不影响使用
HOTKEYS = {
    1: (VK_F13, "F13", "page1"),
    2: (VK_F14, "F14", "page2"),
    3: (VK_F15, "F15", "page3"),
    4: (VK_F16, "F16", "page4"),
    5: (VK_F17, "F17", "page5"),
}
_status_lock = threading.Lock()


def now_text():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _replace_quiet(temp_path, target_path):
    # 目标文件可能正被读方（web 控制台每 2 秒轮询）短暂占用；失败重试几次仍不行就放弃，
    # 绝不让状态写文件的小概率冲突杀死消息循环（pythonw 后台无任何提示）
    for attempt in range(4):
        try:
            os.replace(temp_path, target_path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    try:
        temp_path.unlink()
    except OSError:
        pass


def write_status(**updates):
    with _status_lock:
        try:
            status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            status = {}
        status.update(updates)
        status["updated_at"] = now_text()
        status["pid"] = os.getpid()
        temp_path = STATUS_PATH.with_suffix(".tmp")
        try:
            temp_path.write_text(
                json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _replace_quiet(temp_path, STATUS_PATH)
        except OSError:
            # 状态文件写不进只影响可观测性，不影响热键功能本身
            pass


def post_action(action):
    # 直连本机控制台（显式 host/port 常量，无动态目标）：控制台固定在本机 8080，
    # 改端口时需同步改这里与 dashboard_web.py 的默认端口
    conn = http.client.HTTPConnection("127.0.0.1", 8080, timeout=5)
    try:
        body = json.dumps({"action": action})
        conn.request("POST", "/api/action", body=body,
                     headers={"Content-Type": "application/json"})
        result = json.loads(conn.getresponse().read().decode("utf-8"))
        write_status(
            last_result="ok" if result.get("ok") else "rejected",
            last_message=str(result),
        )
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        write_status(last_result="failed", last_message=str(exc))
    finally:
        conn.close()


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def main():
    parser = argparse.ArgumentParser(description="Dashboard global hotkeys (F13/F14/F15)")
    args = parser.parse_args()

    counts = {key: 0 for key in ("F13", "F14", "F15", "F16", "F17")}
    write_status(
        state="registering",
        registered_keys=[],
        counts=counts,
        last_hotkey=None,
        last_result=None,
        last_message=None,
        started_at=now_text(),
    )
    registered = []
    try:
        for hotkey_id, (virtual_key, key_name, _) in HOTKEYS.items():
            if not user32.RegisterHotKey(None, hotkey_id, 0, virtual_key):
                raise OSError(f"RegisterHotKey failed for VK 0x{virtual_key:02X}")
            registered.append(key_name)
        write_status(state="listening", registered_keys=registered)
    except Exception as exc:
        write_status(state="register_failed", registered_keys=registered, last_message=str(exc))
        raise

    message = MSG()
    last_fire = {}
    write_status(state="listening", registered_keys=registered)
    try:
        while True:
            ret = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            # 0=WM_QUIT 正常退出；-1=GetMessage 出错，都不能继续循环
            if ret == 0 or ret == -1:
                break
            if message.message == WM_HOTKEY and message.wParam in HOTKEYS:
                _, key_name, action = HOTKEYS[message.wParam]
                fire_at = time.monotonic()
                if fire_at - last_fire.get(key_name, 0.0) < DEBOUNCE_SECONDS:
                    continue
                last_fire[key_name] = fire_at
                counts[key_name] += 1
                write_status(
                    last_hotkey=key_name,
                    last_action=action,
                    last_result="sending",
                    counts=counts,
                )
                threading.Thread(
                    target=post_action, args=(action,), daemon=True
                ).start()
    finally:
        write_status(state="stopped", registered_keys=[])
        for hotkey_id in HOTKEYS:
            user32.UnregisterHotKey(None, hotkey_id)


if __name__ == "__main__":
    main()
