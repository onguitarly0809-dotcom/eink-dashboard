#!/usr/bin/env python3
"""横版邮件监控入口。实现在 epd_dashboard/mail_monitor.py，本文件只做变体引导。

用法: pythonw mail_monitor.py   （后台常驻；配置 dashboard_serial_landscape/mail_config.json）
"""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
os.environ.setdefault("EPD_VARIANT", "landscape")
os.environ.setdefault("EPD_BASE_DIR", str(_HERE))
sys.path.insert(0, str(_ROOT))

from epd_dashboard.mail_monitor import main  # noqa: E402

if __name__ == "__main__":
    main()
