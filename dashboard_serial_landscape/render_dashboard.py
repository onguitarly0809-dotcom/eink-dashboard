#!/usr/bin/env python3
"""横版入口（800x480 原生横屏渲染全 5 页）。

实现已收归仓库根的共享包 epd_dashboard/；本文件只做变体引导：
设置 EPD_VARIANT/EPD_BASE_DIR 并把仓库根挂上 sys.path。调用方式保持不变：
    python render_dashboard.py --mode full            # 全量抓数据 + 页1
    python render_dashboard.py --mode stock --page 5 --push --gray
"""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
os.environ.setdefault("EPD_VARIANT", "landscape")
os.environ.setdefault("EPD_BASE_DIR", str(_HERE))
sys.path.insert(0, str(_ROOT))

from epd_dashboard.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
