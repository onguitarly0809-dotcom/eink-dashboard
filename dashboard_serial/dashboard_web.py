#!/usr/bin/env python3
"""竖版 Web 控制台入口。实现在 epd_dashboard/web.py，本文件只做变体引导。

用法: python dashboard_web.py [--port 8080]
"""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
os.environ.setdefault("EPD_VARIANT", "portrait")
os.environ.setdefault("EPD_BASE_DIR", str(_HERE))
sys.path.insert(0, str(_ROOT))

from epd_dashboard.web import main  # noqa: E402

if __name__ == "__main__":
    main()
