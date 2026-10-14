#!/usr/bin/env python3
"""横版全局热键入口（F13-F17 → 页1-5）。实现在 epd_dashboard/hotkeys.py。

正常经开机自启 VBS 以 pythonw 隐藏运行；状态写本目录 hotkeys_status.json。
"""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
os.environ.setdefault("EPD_VARIANT", "landscape")
os.environ.setdefault("EPD_BASE_DIR", str(_HERE))
sys.path.insert(0, str(_ROOT))

from epd_dashboard.hotkeys import main  # noqa: E402

if __name__ == "__main__":
    main()
