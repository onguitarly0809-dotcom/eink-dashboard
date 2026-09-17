"""命令行入口：按 --mode 抓数据、按 --page 渲染并输出。

保持与旧版单文件 render_dashboard.py 完全一致的参数与输出 JSON。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from epd_dashboard.config import (
    DEFAULT_OUTPUT_DIR,
    MARKETS_TTL_CLOSED_MINUTES,
    MARKETS_TTL_TRADING_MINUTES,
    PLANS_FILE,
    TTL_MINUTES,
)
from epd_dashboard.datastore import is_fresh, load_cache, mark_fetched, read_plans, save_cache
from epd_dashboard.fetchers.analysis import in_generation_window, should_refresh
from epd_dashboard.fetchers.glm import fetch_glm_plan
from epd_dashboard.fetchers.markets import fetch_intraday, fetch_markets
from epd_dashboard.fetchers.news import fetch_news
from epd_dashboard.fetchers.insight import fetch_insight
from epd_dashboard.fetchers.weather import fetch_weather
from epd_dashboard.fetchers.zhipu_analysis import HK_SESSION_END, ZHIPU_CODE, fetch_zhipu_analysis
from epd_dashboard.output import write_outputs
from epd_dashboard.obsidian_export import archive_insight
from epd_dashboard.placeholders import placeholder_glm, placeholder_weather
from epd_dashboard.renderers.page1_today import render_dashboard
from epd_dashboard.renderers.page2_news import render_page2
from epd_dashboard.renderers.page3_markets import render_page3
from epd_dashboard.renderers.page4_analysis import render_page4
from epd_dashboard.renderers.page5_zhipu import render_page5
from epd_dashboard.renderers.test_pattern import render_test


def main():
    parser = argparse.ArgumentParser(description="Render the 7.5-inch e-paper dashboard")
    parser.add_argument(
        "--mode",
        choices=("full", "today", "weather", "plans", "news", "markets", "insight", "psychology", "analysis", "stock"),
        default="full",
        help="which module to refresh: full=all, today=page1 only (weather/glm, TTL-gated), "
             "weather, plans, news, markets, insight, analysis, stock",
    )
    parser.add_argument(
        "--page",
        choices=("1", "2", "3", "4", "5"),
        default="1",
        help="which page to render: 1=今日看板 V1.0, 2=三栏新闻, 3=行情, 4=AI认知洞察, 5=智谱AI走势归因",
    )
    parser.add_argument(
        "--test-pattern",
        choices=("chess", "white", "black", "info"),
        default=None,
        help="render a test pattern instead of the dashboard",
    )
    parser.add_argument("--plans", type=Path, default=PLANS_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--orientation", choices=("cw", "ccw", "none"), default="cw")
    parser.add_argument(
        "--force",
        action="store_true",
        help="ignore cache TTL and fetch fresh data for every module",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="push the rendered binary to the e-paper over serial after rendering",
    )
    parser.add_argument("--port", default=None, help="serial port for --push (default from config)")
    parser.add_argument("--baud", type=int, default=None, help="serial baud rate for --push (default from config)")
    parser.add_argument("--chunk", type=int, default=None, help="serial chunk bytes for --push (default from config)")
    args = parser.parse_args()

    now = datetime.now()

    if args.test_pattern:
        portrait = render_test(args.test_pattern, now)
        portrait_path, preview_path, binary_path, packed_len = write_outputs(portrait, args)
        print(json.dumps({
            "test": args.test_pattern,
            "portrait": str(portrait_path),
            "preview": str(preview_path),
            "binary": str(binary_path),
            "bytes": packed_len,
        }, ensure_ascii=False))
        return

    page = int(args.page)
    cache = load_cache()
    weather = cache.get("weather")
    glm = cache.get("glm")
    plans = cache.get("plans")
    news = cache.get("news")
    markets = cache.get("markets")
    analysis = cache.get("analysis")
    stock_analysis = cache.get("stock_analysis")
    intraday = cache.get("intraday")

    # 切页 mode（today/news/markets）受 TTL 门控：缓存未过期直接用，按键秒出图。
    # full（定时轮播，数据补给线）与手动单模块命令（weather 等）不受限，始终联网；
    # --force 再额外跳过切页 TTL。
    if args.mode in ("full", "weather", "today"):
        if args.mode == "today" and not args.force and is_fresh(cache, "weather", TTL_MINUTES["weather"], now):
            print("weather fresh, skip fetch", file=sys.stderr)
        else:
            try:
                weather = fetch_weather()
                cache["weather"] = weather
                mark_fetched(cache, "weather", now)
                print("weather refreshed", file=sys.stderr)
            except Exception as exc:
                print(f"WARN weather fetch failed, keep last value: {exc}", file=sys.stderr)

    if args.mode in ("full", "today"):
        glm_fresh = (args.mode == "today" and not args.force
                     and is_fresh(cache, "glm", TTL_MINUTES["glm"], now))
        if glm_fresh:
            print("glm fresh, skip fetch", file=sys.stderr)
        else:
            try:
                glm = fetch_glm_plan()
                cache["glm"] = glm
                mark_fetched(cache, "glm", now)
                print("glm plan refreshed", file=sys.stderr)
            except Exception as exc:
                print(f"WARN glm plan fetch failed, keep last value: {exc}", file=sys.stderr)
                if not cache.get("glm"):
                    glm = placeholder_glm()
                    cache["glm"] = glm
                    print("Using placeholder glm due to fetch failure", file=sys.stderr)

    if args.mode in ("full", "news"):
        if args.mode == "news" and not args.force and is_fresh(cache, "news", TTL_MINUTES["news"], now):
            print("news fresh, skip fetch", file=sys.stderr)
        else:
            try:
                # AI 摘要只在后台补给（full）或手动 --force 时执行，按键切页永不为摘要等待
                news = fetch_news(news, summarize=args.mode == "full" or bool(args.force))
                cache["news"] = news
                mark_fetched(cache, "news", now)
                print("news refreshed", file=sys.stderr)
            except Exception as exc:
                print(f"WARN news fetch failed, keep last value: {exc}", file=sys.stderr)

    markets_ttl = (MARKETS_TTL_TRADING_MINUTES
                   if in_generation_window(now, end_time=HK_SESSION_END)
                   else MARKETS_TTL_CLOSED_MINUTES)

    if args.mode in ("full", "markets"):
        if args.mode == "markets" and not args.force and is_fresh(cache, "markets", markets_ttl, now):
            print("markets fresh, skip fetch", file=sys.stderr)
        else:
            try:
                markets = fetch_markets(markets)
                cache["markets"] = markets
                mark_fetched(cache, "markets", now)
                print("markets refreshed", file=sys.stderr)
            except Exception as exc:
                print(f"WARN markets fetch failed, keep last value: {exc}", file=sys.stderr)

    # 页5 分时折线：与行情同 TTL 节奏；stock（强制重生成）时一并强制刷新
    if page == 5 and args.mode in ("full", "markets", "stock"):
        if args.mode != "stock" and not args.force and is_fresh(cache, "intraday", markets_ttl, now):
            print("intraday fresh, skip fetch", file=sys.stderr)
        else:
            try:
                intraday = fetch_intraday(ZHIPU_CODE)
                cache["intraday"] = intraday
                mark_fetched(cache, "intraday", now)
                print("intraday refreshed", file=sys.stderr)
            except Exception as exc:
                print(f"WARN intraday fetch failed, keep last value: {exc}", file=sys.stderr)

    if args.mode in ("full", "plans") or plans is None:
        try:
            plans = read_plans(args.plans)
            cache["plans"] = plans
        except Exception as exc:
            print(f"WARN plans read failed: {exc}", file=sys.stderr)

    # 按页面确定必需模块：页1=天气/额度/计划，页2=新闻，页3/5=行情，页4=AI生成内容
    data_map = {"weather": weather, "plans": plans, "news": news, "markets": markets}
    if page in (3, 5):
        required = ("markets",)
    elif page == 2:
        required = ("news",)
    else:
        required = ("weather", "plans")
    missing_modules = [module for module in required if data_map[module] is None]
    if missing_modules:
         print(
             "ERROR: missing data for " + ", ".join(missing_modules)
             + "; using placeholder data to continue",
             file=sys.stderr,
         )
         # sys.exit(2)  # 注释掉，允许使用占位数据继续渲染

    # 非必需模块缺失时用占位，避免渲染引用出错
    if weather is None:
        weather = placeholder_weather(now)
    if glm is None:
        glm = placeholder_glm()
        cache["glm"] = glm  # 更新cache中的占位数据
    if plans is None:
        plans = []
        cache["plans"] = plans  # 更新cache中的占位数据
    if news is None:
        news = {}
        cache["news"] = news  # 更新cache中的占位数据

    if markets is None:
        markets = {"quotes": {}, "updated": now.strftime("%H:%M")}
        cache["markets"] = markets  # 更新cache中的占位数据

    # 页4认知洞察：每次触发都按领域轮换生成新主题；历史主题持久去重
    if args.mode in ("analysis", "insight", "psychology") or (args.mode in ("full", "markets") and page == 4):
        try:
            analysis = fetch_insight(analysis, now=now)
            cache["analysis"] = analysis
            archived = archive_insight(analysis, now=now)
            if archived:
                print(f"insight archived -> {archived}", file=sys.stderr)
            print("insight refreshed", file=sys.stderr)
        except Exception as exc:
            print(f"ERROR insight generation failed: {exc}", file=sys.stderr)
            raise RuntimeError("页4新主题生成失败，已取消渲染/推送以避免重复显示") from exc

    # 页5 智谱AI 分析：手动 stock 模式强制重生成；轮播到页5且缓存超 TTL 时仅在港股时段内重生成
    if args.mode == "stock" or (args.mode in ("full", "markets") and page == 5):
        force = args.mode == "stock"
        if should_refresh(stock_analysis, force=force):
            if force or in_generation_window(now, end_time=HK_SESSION_END):
                try:
                    stock_analysis = fetch_zhipu_analysis(markets, stock_analysis, now=now)
                    cache["stock_analysis"] = stock_analysis
                    print("stock analysis refreshed", file=sys.stderr)
                except Exception as exc:
                    print(f"WARN stock analysis generation failed, keep last value: {exc}", file=sys.stderr)
            else:
                print("stock analysis: 非交易时段，跳过自动生成", file=sys.stderr)
        if isinstance(stock_analysis, dict) and stock_analysis.get("text") and should_refresh(stock_analysis):
            stock_analysis = dict(stock_analysis, stale=True)
            cache["stock_analysis"] = stock_analysis

    cache["updated_at"] = now.isoformat(timespec="seconds")
    save_cache(cache)

    if page == 3:
        portrait = render_page3(markets)
    elif page == 2:
        portrait = render_page2(news)
    elif page == 4:
        portrait = render_page4(analysis)
    elif page == 5:
        portrait = render_page5(markets, stock_analysis, intraday)
    else:
        portrait = render_dashboard(weather, plans, glm, now)
    portrait_path, preview_path, binary_path, packed_len = write_outputs(portrait, args)
    result = {
        "mode": args.mode,
        "page": page,
        "portrait": str(portrait_path),
        "preview": str(preview_path),
        "binary": str(binary_path),
        "bytes": packed_len,
        "orientation": args.orientation,
        "plans": len(plans),
    }

    if args.push:
        # 渲染进程内直接推送，省掉再起一个 PowerShell（send_dashboard.ps1）的开销
        from epd_dashboard.push import push_with_retry
        push_with_retry(binary_path=binary_path, port=args.port, baud=args.baud, chunk=args.chunk)
        result["pushed"] = True

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
