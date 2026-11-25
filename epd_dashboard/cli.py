"""命令行入口（横竖共用）：按 --mode 抓数据、按 --page 渲染并输出。

渲染器按当前变体（config.VARIANT，由入口脚本的 EPD_VARIANT 决定）从
epd_dashboard.renderers.{landscape,portrait} 分派；页面集合：横版 1-5，
横竖均为页1-5。参数与输出 JSON 两版一致，便于脚本互通。
"""
import argparse
import importlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from epd_dashboard.config import (
    DEFAULT_ORIENTATION,
    DEFAULT_OUTPUT_DIR,
    EPD_HEIGHT,
    EPD_SERIAL_PORT,
    EPD_WIDTH,
    MAIL_BASE_PNG,
    MAIL_INBOX_FILE,
    MAIL_STATE_FILE,
    PAUSE_BASE_PNG,
    PAUSE_STATE_FILE,
    MARKETS_TTL_CLOSED_MINUTES,
    MARKETS_TTL_TRADING_MINUTES,
    PAGE_STATE_FILE,
    PLANS_FILE,
    TTL_MINUTES,
    VARIANT,
)
from epd_dashboard.datastore import is_fresh, load_cache, mark_fetched, read_plans, save_cache
from epd_dashboard.fetchers.analysis import in_generation_window, should_refresh
from epd_dashboard.fetchers.glm import fetch_glm_plan
from epd_dashboard.fetchers.insight import fetch_insight
from epd_dashboard.fetchers.markets import fetch_intraday, fetch_markets
from epd_dashboard.fetchers.news import fetch_news
from epd_dashboard.fetchers.weather import fetch_weather
from epd_dashboard.fetchers.zhipu_analysis import (
    AI_INDEX_CODE,
    HK_SESSION_END,
    ZHIPU_CODE,
    fetch_zhipu_analysis,
)
from epd_dashboard.obsidian_export import archive_insight
from epd_dashboard.output import write_outputs
from epd_dashboard.placeholders import placeholder_glm, placeholder_weather

# 变体渲染器：页面函数从这里取，页面差异（签名）在各变体包内自洽
R = importlib.import_module(f"epd_dashboard.renderers.{VARIANT}")

PAGES = ("1", "2", "3", "4", "5")

# 与 ops/control.ps1 约定：设备未连接时以 4 退出，调度方按"本轮跳过"处理（不算渲染失败）
DEVICE_OFFLINE_EXIT = 4


def _device_online(args):
    """--push 前的设备在线预检：只枚举串口，不开端口、不碰固件。"""
    if os.environ.get("EPD_FORCE_OFFLINE"):   # 自动化测试钩子：不必真拔 USB
        print("device offline (forced by EPD_FORCE_OFFLINE)", file=sys.stderr)
        return False
    from epd_dashboard.push import DeviceUnavailable, _resolve_port
    try:
        _resolve_port(args.port or EPD_SERIAL_PORT, lambda message: print(message, file=sys.stderr))
        return True
    except DeviceUnavailable as exc:
        print(f"device offline: {exc}", file=sys.stderr)
        return False


def _render_base_page(now):
    """按页状态从缓存纯渲染当前页，作为邮件弹窗的底图（还原基准）。

    不联网、不写缓存：底图必须与屏幕上正在显示的内容一致（同样的缓存数据），
    任何 fetch 都可能让底图偏离屏幕。数据缺失时与主渲染流程同款占位兜底。
    """
    cache = load_cache()
    weather = cache.get("weather") or placeholder_weather(now)
    glm = cache.get("glm") or placeholder_glm()
    plans = cache.get("plans") or []
    news = cache.get("news") or {}
    markets = cache.get("markets") or {"quotes": {}, "updated": now.strftime("%H:%M")}
    analysis = cache.get("analysis")
    stock_analysis = cache.get("stock_analysis")
    page = 1
    try:
        state = json.loads(PAGE_STATE_FILE.read_text(encoding="utf-8"))
        if int(state.get("page", 1)) in (1, 2, 3, 4, 5):
            page = int(state["page"])
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    print(f"mail base: 按页状态渲染页{page}（纯缓存）", file=sys.stderr)
    if page == 3:
        return R.render_page3(markets)
    if page == 2:
        return R.render_page2(news)
    if page == 4:
        return R.render_page4(analysis)
    if page == 5:
        return R.render_page5(markets, stock_analysis,
                              cache.get("intraday"), cache.get("intraday_ai"))
    return R.render_dashboard(weather, plans, glm, now)


def main():
    parser = argparse.ArgumentParser(description="Render the 7.5-inch e-paper dashboard")
    parser.add_argument(
        "--mode",
        choices=("full", "today", "weather", "plans", "news", "markets", "insight", "psychology", "analysis", "stock", "mail", "mailoff", "pause", "resume"),
        default="full",
        help="which module to refresh: full=all, today=page1 only (weather/glm, TTL-gated), "
             "weather, plans, news, markets, insight, analysis, stock; mail=新邮件弹窗层"
             "（当前页底图+弹窗，读 mail_inbox.json，全程不联网）; mailoff=推回底图像素级还原; "
             "pause=锁屏暂停大弹窗（监控的锁屏监视线程触发）; resume=解锁还原锁屏前画面",
    )
    parser.add_argument(
        "--page",
        choices=PAGES,
        default="1",
        help="which page to render: 1=今日看板, 2=三栏新闻, 3=行情, 4=AI认知洞察, 5=智谱AI走势归因",
    )
    parser.add_argument(
        "--test-pattern",
        choices=("chess", "white", "black", "info"),
        default=None,
        help="render a test pattern instead of the dashboard",
    )
    parser.add_argument("--plans", type=Path, default=PLANS_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--orientation", choices=("cw", "ccw", "none"), default=DEFAULT_ORIENTATION,
                        help=f"落盘前旋转（默认 {DEFAULT_ORIENTATION}，随版式：横版直出/竖版顺时针转正）")
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
    parser.add_argument(
        "--gray",
        action="store_true",
        help="4-gray mode: pack as two 1bpp planes (96KB) and let firmware refresh with "
             "the 4-gray waveform (~3-4x slower refresh, gray anti-aliasing for body text)",
    )
    args = parser.parse_args()

    # 设备在线预检（只在要推送时做）：设备拔掉时抓数/生成一轮要几十秒到几分钟，还白白
    # 消耗 GLM 额度、往 Obsidian 写笔记，最后一步才发现推不了。不在线直接以 4 结束
    if args.push and not _device_online(args):
        print(json.dumps({"mode": args.test_pattern or args.mode, "page": args.page,
                          "skipped": "device-offline"}, ensure_ascii=False))
        sys.exit(DEVICE_OFFLINE_EXIT)

    now = datetime.now()

    if args.test_pattern:
        portrait = R.render_test(args.test_pattern, now)
        portrait_path, preview_path, binary_path, packed_len = write_outputs(portrait, args)
        print(json.dumps({
            "test": args.test_pattern,
            "portrait": str(portrait_path),
            "preview": str(preview_path),
            "binary": str(binary_path),
            "bytes": packed_len,
        }, ensure_ascii=False))
        return

    if args.mode in ("mail", "mailoff", "pause", "resume"):
        # 覆盖层四模式：mail/mailoff=邮件弹窗上屏/像素级还原（底图 mail_base.png）；
        # pause/resume=锁屏暂停大弹窗/解锁还原（底图 pause_base.png，另一份互不干扰）。
        # 全程不联网、不读写轮播缓存、不写页状态。--page 对这些模式无意义。
        if args.mode == "pause":
            base = _render_base_page(now)
            tmp = PAUSE_BASE_PNG.with_suffix(".png.tmp")
            base.save(tmp, format="PNG")
            tmp.replace(PAUSE_BASE_PNG)
            # 记录暂停时的页状态：resume 前若轮播已推进（页状态变化）则不还原防倒退
            page = 1
            try:
                page = int(json.loads(PAGE_STATE_FILE.read_text(encoding="utf-8")).get("page", 1))
            except (OSError, ValueError, json.JSONDecodeError):
                pass
            Path(str(PAUSE_STATE_FILE)).write_text(json.dumps({"page": page}), encoding="utf-8")
            render_pause = getattr(R, "render_pause_overlay", None)
            if render_pause is None:
                raise RuntimeError("锁屏暂停层暂仅横版支持（当前变体无对应渲染器）")
            portrait = render_pause(base, now)
        elif args.mode == "resume":
            if not PAUSE_BASE_PNG.exists():
                print("resume: 无暂停层在屏（底图不存在），本次为空操作", file=sys.stderr)
                print(json.dumps({"mode": "resume", "noop": True}, ensure_ascii=False))
                return
            # 防倒退守卫：恢复排队期间轮播已推进（页状态变化）则不还原旧页——
            # 屏幕 已被新内容接管，直接清理暂停态
            try:
                paused_page = int(json.loads(PAUSE_STATE_FILE.read_text(encoding="utf-8"))["page"])
                current_page = int(json.loads(PAGE_STATE_FILE.read_text(encoding="utf-8")).get("page", 1))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                paused_page = current_page = None
            # 状态文件缺失（旧版暂停/异常路径）或页状态已流转：一律不还原——
            # 无法证明"底图仍是被覆盖画面"时宁可不动屏，交给轮播自然接管
            if paused_page is None or current_page != paused_page:
                print(f"resume: 页状态已流转（{paused_page}→{current_page}），屏幕已被接管，跳过还原",
                      file=sys.stderr)
                PAUSE_BASE_PNG.unlink(missing_ok=True)
                PAUSE_STATE_FILE.unlink(missing_ok=True)
                print(json.dumps({"mode": "resume", "noop": True, "reason": "page-moved"},
                                 ensure_ascii=False))
                return
            from PIL import Image
            portrait = Image.open(PAUSE_BASE_PNG).convert("L")
            if portrait.size != (EPD_WIDTH, EPD_HEIGHT):
                raise RuntimeError(f"pause_base.png 尺寸异常 {portrait.size}，拒绝还原")
            print("resume: 以保存的底图像素级还原锁屏前画面", file=sys.stderr)
        elif args.mode == "mail":
            base = _render_base_page(now)
            tmp = MAIL_BASE_PNG.with_suffix(".png.tmp")
            base.save(tmp, format="PNG")
            tmp.replace(MAIL_BASE_PNG)
            payload = {}
            try:
                payload = json.loads(MAIL_INBOX_FILE.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                print(f"WARN mail inbox payload missing/invalid: {MAIL_INBOX_FILE}", file=sys.stderr)
            render_overlay = getattr(R, "render_mail_overlay", None)
            if render_overlay is None:
                raise RuntimeError("邮件弹窗层暂仅横版支持（当前变体无对应渲染器）")
            portrait = render_overlay(base, payload, now)
        else:
            if not MAIL_BASE_PNG.exists():
                # 幂等空操作：底图不存在=弹窗已收起（或从未上屏）。正常退出，
                # 让手动收起（M5）与守护定时收起互不冲突，二次调用不重复刷屏
                print("mailoff: 无弹窗在屏（底图不存在），本次为空操作", file=sys.stderr)
                print(json.dumps({"mode": "mailoff", "noop": True}, ensure_ascii=False))
                return
            # 页状态已流转（排队期间轮播/手动切页接管过屏幕）则不还原，避免倒退
            try:
                overlay_page = json.loads(MAIL_STATE_FILE.read_text(encoding="utf-8")).get("overlay_page")
                current_page = json.loads(PAGE_STATE_FILE.read_text(encoding="utf-8")).get("page")
            except (OSError, ValueError, json.JSONDecodeError):
                overlay_page = current_page = None
            if overlay_page in (1, 2, 3, 4, 5) and current_page != overlay_page:
                print(f"mailoff: 页状态已流转（{overlay_page}→{current_page}），弹窗已被接管，无需还原",
                      file=sys.stderr)
                print(json.dumps({"mode": "mailoff", "noop": True, "reason": "page-moved"},
                                 ensure_ascii=False))
                return
            from PIL import Image
            portrait = Image.open(MAIL_BASE_PNG).convert("L")
            if portrait.size != (EPD_WIDTH, EPD_HEIGHT):
                raise RuntimeError(f"mail_base.png 尺寸异常 {portrait.size}，拒绝还原")
            print("mailoff: 以保存的底图像素级还原被覆盖页", file=sys.stderr)
        portrait_path, preview_path, binary_path, packed_len = write_outputs(portrait, args)
        result = {
            "mode": args.mode,
            "portrait": str(portrait_path),
            "preview": str(preview_path),
            "binary": str(binary_path),
            "bytes": packed_len,
            "orientation": args.orientation,
        }
        if args.push:
            from epd_dashboard.push import push_with_retry
            push_with_retry(binary_path=binary_path, port=args.port, baud=args.baud, chunk=args.chunk)
            result["pushed"] = True
            if args.mode == "mailoff":
                # 推回成功即删底图：后续 mailoff（守护定时器/重复按键）自动变空操作
                MAIL_BASE_PNG.unlink(missing_ok=True)
            elif args.mode == "resume":
                # 同理：恢复成功即删暂停底图与状态，重复 resume 变空操作
                PAUSE_BASE_PNG.unlink(missing_ok=True)
                PAUSE_STATE_FILE.unlink(missing_ok=True)
        print(json.dumps(result, ensure_ascii=False))
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
    intraday_ai = cache.get("intraday_ai")

    # 切页 mode（today/news/markets）受 TTL 门控：缓存未过期直接用，按键秒出图。
    # full（定时轮播，数据补给线）与手动单模块命令（weather 等）不受限，始终联网；
    # --force 再额外跳过切页 TTL。
    # 例外（2026-11-25）：full 渲染的不是页1、且天气缓存仍在 TTL 内时也不重抓——天气
    # 只有页1 用，轮播 20 分钟一轮而 TTL 30 分钟，省下的这一轮照样覆盖随后的按键切页；
    # 页1 自身上屏时照常抓最新（open-meteo 单次 1~20 秒，是每轮的固定开销）
    if args.mode in ("full", "weather", "today"):
        weather_reusable = (
            not args.force
            and (args.mode == "today" or (args.mode == "full" and page != 1))
            and is_fresh(cache, "weather", TTL_MINUTES["weather"], now)
        )
        if weather_reusable:
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

    # stock（强制重生成页5）也刷新行情：归因要用最新价/涨跌幅做上下文
    if args.mode in ("full", "markets", "stock"):
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

    # 页5 分时折线：智谱个股 + 人工智能(A)指数各一条，与行情同 TTL 节奏；
    # stock（强制重生成）时一并强制刷新
    if page == 5 and args.mode in ("full", "markets", "stock"):
        for key, symbol in (("intraday", ZHIPU_CODE), ("intraday_ai", AI_INDEX_CODE)):
            if args.mode != "stock" and not args.force and is_fresh(cache, key, markets_ttl, now):
                print(f"{key} fresh, skip fetch", file=sys.stderr)
                continue
            try:
                fetched = fetch_intraday(symbol)
                if key == "intraday":
                    intraday = fetched
                else:
                    intraday_ai = fetched
                cache[key] = fetched
                mark_fetched(cache, key, now)
                print(f"{key} refreshed", file=sys.stderr)
            except Exception as exc:
                print(f"WARN {key} fetch failed, keep last value: {exc}", file=sys.stderr)

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
            # 生成失败不再取消渲染：那样页状态不会提交，下一轮仍指向页4，接口持续故障时
            # 整个轮播就冻在页4。改为沿用上一篇洞察并标"历史"（标题带显示"（历史）"），
            # 轮播照常流转；一篇缓存都没有时页面显示占位
            print(f"WARN insight generation failed, keep last insight: {exc}", file=sys.stderr)
            if isinstance(analysis, dict) and analysis.get("text"):
                analysis = dict(analysis, stale=True)
            else:
                analysis = None
            cache["analysis"] = analysis

    # 页5 智谱AI 分析：港股时段内每次渲染本页都重新生成（2026-11-25 用户选定方案 E：不再按
    # 90 分钟 TTL 省额度，报告与同时刷新的分时图保持同一时刻）；时段外行情不动，自动轮播
    # 不重写，只把超过 TTL 的旧报告标"历史"。手动 stock / page5 -Force 不受时段限制。
    if args.mode == "stock" or (args.mode in ("full", "markets") and page == 5):
        # --force 且目标是页5 = 热键 M5/手动 page5 -Force：显式按键是用户要"现在就要新内容"
        force = args.mode == "stock" or (args.force and page == 5)
        in_session = in_generation_window(now, end_time=HK_SESSION_END)
        if force or in_session:
            try:
                stock_analysis = fetch_zhipu_analysis(markets, stock_analysis, now=now)
                cache["stock_analysis"] = stock_analysis
                print("stock analysis refreshed", file=sys.stderr)
            except Exception as exc:
                print(f"WARN stock analysis generation failed, keep last value: {exc}", file=sys.stderr)
                # 重写失败而沿用旧报告：标"历史"。旁边是刚刷新的分时图，不标的话正文会对着
                # 一张更新的图却毫无提示（旧报告不足 90 分钟时原先是不标的）
                if isinstance(stock_analysis, dict) and stock_analysis.get("text"):
                    stock_analysis = dict(stock_analysis, stale=True)
                    cache["stock_analysis"] = stock_analysis
        elif should_refresh(stock_analysis):
            print("stock analysis: 非交易时段，跳过自动生成", file=sys.stderr)
        if isinstance(stock_analysis, dict) and stock_analysis.get("text") and should_refresh(stock_analysis):
            stock_analysis = dict(stock_analysis, stale=True)
            cache["stock_analysis"] = stock_analysis

    cache["updated_at"] = now.isoformat(timespec="seconds")
    save_cache(cache)

    if page == 3:
        portrait = R.render_page3(markets)
    elif page == 2:
        portrait = R.render_page2(news)
    elif page == 4:
        portrait = R.render_page4(analysis)
    elif page == 5:
        portrait = R.render_page5(markets, stock_analysis, intraday, intraday_ai)
    else:
        portrait = R.render_dashboard(weather, plans, glm, now)
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
