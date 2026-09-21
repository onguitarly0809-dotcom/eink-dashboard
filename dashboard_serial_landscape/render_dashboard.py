#!/usr/bin/env python3
"""横版入口：800x480 原生横屏渲染全 6 页。实现见 epd_dashboard 包。

用法与竖版完全一致：
    python render_dashboard.py --mode full            # 全量抓数据 + 页1
    python render_dashboard.py --mode weather --page 6 --push
"""
from epd_dashboard.cli import main

if __name__ == "__main__":
    main()
