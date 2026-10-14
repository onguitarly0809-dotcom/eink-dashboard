#!/usr/bin/env python3
"""竖版入口（480x800 竖屏渲染，页1-6，推送前旋转到固件 800x480 栅格）。

实现已收归仓库根的共享包 epd_dashboard/；本文件只做变体引导：
设置 EPD_VARIANT/EPD_BASE_DIR 并把仓库根挂上 sys.path。调用方式保持不变：
    python render_dashboard.py --mode full            # 全量抓数据 + 页1
    python render_dashboard.py --mode weather --page 6
"""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
os.environ.setdefault("EPD_VARIANT", "portrait")
os.environ.setdefault("EPD_BASE_DIR", str(_HERE))
sys.path.insert(0, str(_ROOT))

from epd_dashboard.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
