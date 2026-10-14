#!/usr/bin/env python3
"""离线全页面渲染：从 dashboard_data.json 缓存渲染全部页面，不联网、不推送。

用途：
1. 重构/改动渲染链路后的回归基准——重构前后各跑一次，PNG 逐字节对比；
2. 排版调试——固定时间渲染任意页面，直接看页面效果。

用法:
    python tools/render_all_pages.py landscape  [输出目录]
    python tools/render_all_pages.py portrait   [输出目录]

页面函数签名与 cli.py 的渲染分派完全一致；时间固定为 2026-09-23 12:00，
保证同缓存输入下输出可复现。输出 <out>/pageN.png（竖版含 page6.png）
与 test_pattern.png。
"""
import importlib
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXED_NOW = datetime(2026, 9, 23, 12, 0)
VARIANT_DIRS = {"landscape": "dashboard_serial_landscape", "portrait": "dashboard_serial"}


def render_variant(variant: str, out_dir: Path):
    variant_dir = ROOT / VARIANT_DIRS[variant]
    os.environ["EPD_VARIANT"] = variant
    os.environ["EPD_BASE_DIR"] = str(variant_dir)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from epd_dashboard.datastore import load_cache
    from epd_dashboard.placeholders import placeholder_glm, placeholder_weather

    p1 = importlib.import_module(f"epd_dashboard.renderers.{variant}.page1_today")
    p2 = importlib.import_module(f"epd_dashboard.renderers.{variant}.page2_news")
    p3 = importlib.import_module(f"epd_dashboard.renderers.{variant}.page3_markets")
    p4 = importlib.import_module(f"epd_dashboard.renderers.{variant}.page4_analysis")
    p5 = importlib.import_module(f"epd_dashboard.renderers.{variant}.page5_zhipu")
    tp = importlib.import_module(f"epd_dashboard.renderers.{variant}.test_pattern")
    page6 = None
    if variant == "portrait":
        page6 = importlib.import_module("epd_dashboard.renderers.portrait.page6_weather")

    cache = load_cache()
    weather = cache.get("weather") or placeholder_weather(FIXED_NOW)
    glm = cache.get("glm") or placeholder_glm()
    plans = cache.get("plans") or []
    news = cache.get("news") or {}
    markets = cache.get("markets") or {"quotes": {}, "updated": "12:00"}
    analysis = cache.get("analysis")
    stock = cache.get("stock_analysis")
    intraday = cache.get("intraday")
    intraday_ai = cache.get("intraday_ai")

    out_dir.mkdir(parents=True, exist_ok=True)
    pages = {
        "page1": p1.render_dashboard(weather, plans, glm, FIXED_NOW),
        "page2": p2.render_page2(news),
        "page3": p3.render_page3(markets),
        "page4": p4.render_page4(analysis),
        "page5": p5.render_page5(markets, stock, intraday, intraday_ai),
    }
    for name, img in pages.items():
        img.save(out_dir / f"{name}.png")
        print(f"{out_dir / (name + '.png')}  {img.size}")
    if page6 is not None:
        page6.render_page6(weather, FIXED_NOW).save(out_dir / "page6.png")
        print(f"{out_dir / 'page6.png'}")
    tp.render_test("info", FIXED_NOW).save(out_dir / "test_pattern.png")
    print(f"{out_dir / 'test_pattern.png'}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in VARIANT_DIRS:
        print(__doc__)
        sys.exit(2)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "_refactor_baseline" / sys.argv[1]
    render_variant(sys.argv[1], out)


if __name__ == "__main__":
    main()
