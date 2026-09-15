"""页3（行情）：自选标的、AI概念板块热点、市场参考。"""
import sys
from datetime import datetime

from PIL import Image, ImageDraw

from epd_dashboard.calendar_cn import market_status, market_status_for
from epd_dashboard.config import (
    HEIGHT,
    MARKET_GROUPS,
    PANEL_HEIGHT,
    PANEL_WIDTH,
    PANEL_X,
    PANEL_Y,
    WIDTH,
)
from epd_dashboard.fonts import FONT_STRONG, SIZE_S, SIZE_XS, font
from epd_dashboard.renderers.common import draw_panel, truncate_text
from epd_dashboard.util import to_float

MARKET_TAGS = {"A": "A", "HK": "港", "US": "美"}  # 名称后的单字市场标记
# 当日交易已结束的状态：所有标的都处于这两种状态时，行内状态全同冗余，
# 只保留标题"更新时间"处的整体状态，不再逐个显示
CLOSED_STATUSES = frozenset({"已收盘", "休市"})


def render_market_panel(draw, panel_y, title, items, updated=""):
    draw_panel(draw, panel_y, title, f"更新时间：{updated}" if updated else "", title_weight=700)
    p = panel_y
    line_y = p + 17 + 38
    content_top = line_y + 4
    content_bottom = p + PANEL_HEIGHT - 16
    slot_h = (content_bottom - content_top) / 5
    number_font = font(SIZE_S, FONT_STRONG)
    name_font = font(SIZE_S)
    price_font = font(SIZE_S)
    pct_font = font(SIZE_S, FONT_STRONG)
    number_x = PANEL_X + 18
    name_x = number_x + 44
    price_right = PANEL_X + PANEL_WIDTH - 18 - 96
    pct_right = PANEL_X + PANEL_WIDTH - 18
    for index in range(5):
        slot_top = content_top + int(index * slot_h)
        center_y = slot_top + int((slot_h - SIZE_S) / 2)
        draw.text((number_x, center_y), f"{index + 1:02d}", font=number_font, fill=0)
        if index < len(items):
            item = items[index]
            name = truncate_text(draw, item["name"], name_font, price_right - name_x - 10)
            draw.text((name_x, center_y), name, font=name_font, fill=0)
            if item["price"] > 0:
                draw.text((price_right, center_y), f"{item['price']:.2f}", font=price_font, fill=0, anchor="ra")
                arrow = "▲" if item["pct"] >= 0 else "▼"
                draw.text((pct_right, center_y), f"{arrow}{item['pct']:+.2f}%", font=pct_font, fill=0, anchor="ra")
            else:
                draw.text((price_right, center_y), "--", font=price_font, fill=0, anchor="ra")
        else:
            draw.text((name_x, center_y), "暂无行情", font=name_font, fill=0)


def draw_compact_quote_column(draw, bounds, items):
    # 与黄金与大宗 render_market_panel 同字号（SIZE_S），3 行，每行两行显示（名称 / 价格+涨跌幅）。
    # 半宽列单行放不下 名称+价格+涨跌幅，故上下两行排布以保持字号一致。
    left, top, right, bottom = bounds
    row_height = (bottom - top) / 3
    name_font = font(SIZE_S)
    price_font = font(SIZE_S)
    pct_font = font(SIZE_S, FONT_STRONG)
    line_gap = 6
    for index in range(3):
        row_top = top + int(index * row_height)
        row_bottom = min(bottom, row_top + int(row_height))
        if row_bottom <= row_top:
            continue
        mid = row_top + int(row_height / 2)
        if index < len(items):
            item = items[index]
            status = item.get("status", "")
            status_font = font(SIZE_XS)
            status_w = draw.textlength(status, font=status_font) if status else 0
            tag = MARKET_TAGS.get(item.get("market", "A"), "")
            tag_text = f"({tag})" if tag else ""
            tag_w = draw.textlength(tag_text, font=status_font) if tag_text else 0
            name_max = (right - 4 - left) - (status_w + 6 if status else 0) - (tag_w + 4 if tag_text else 0)
            name = truncate_text(draw, item["name"], name_font, name_max)
            name_y = mid - SIZE_S - line_gap // 2
            draw.text((left, name_y), name, font=name_font, fill=0)
            if tag_text:
                draw.text((left + draw.textlength(name, font=name_font) + 4, name_y + 3), tag_text, font=status_font, fill=0)
            if status:
                draw.text((right - 4, name_y), status, font=status_font, fill=0, anchor="ra")
            if item.get("price", 0) > 0:
                arrow = "▲" if item["pct"] >= 0 else "▼"
                price_text = f"{item['price']:.2f}"
                pct_text = f"{arrow}{item['pct']:+.2f}%"
                pct_w = draw.textlength(pct_text, font=pct_font)
                draw.text((right - 4, mid + line_gap // 2), pct_text, font=pct_font, fill=0, anchor="ra")
                draw.text((right - 4 - pct_w - 8, mid + line_gap // 2), price_text, font=price_font, fill=0, anchor="ra")
            else:
                draw.text((left, mid + line_gap // 2), "--", font=price_font, fill=0)
        else:
            draw.text((left, mid - SIZE_S), "暂无行情", font=name_font, fill=0)


def render_split_market_panel(draw, panel_y, title, left_items, right_renderer, right_data, updated=""):
    draw_panel(draw, panel_y, title, f"更新时间：{updated}" if updated else "", title_weight=700)
    content_top = panel_y + 59
    content_bottom = panel_y + PANEL_HEIGHT - 16
    divider_x = PANEL_X + PANEL_WIDTH // 2
    draw.line((divider_x, content_top - 3, divider_x, content_bottom + 3), fill=0, width=2)
    left_bounds = (PANEL_X + 16, content_top, divider_x - 10, content_bottom)
    right_bounds = (divider_x + 12, content_top, PANEL_X + PANEL_WIDTH - 16, content_bottom)
    draw_compact_quote_column(draw, left_bounds, left_items)
    right_renderer(draw, right_bounds, right_data)


def _with_status(items, now):
    """给行情项附加市场交易状态。返回副本，不污染缓存里的原对象。"""
    return [dict(item, status=market_status_for(item.get("market", "A"), now)) for item in items]


def render_page3(markets, now=None):
    # 页3：自选标的、AI概念板块、市场参考；now 仅供测试注入，默认取当前时刻
    image = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=0, width=2)
    if now is None:
        now = datetime.now()
    updated = markets.get("updated", "")
    status = market_status(now)
    updated = f"{updated} {status}" if updated else status
    if markets.get("stale"):
        updated = f"{updated}（历史）"
    quotes = markets.get("quotes") or {}
    companies = markets.get("companies") or []
    # 面板1 数据：自选标的；quotes 为空或价格为 0 时用 companies 兜底
    my_watchlist = quotes.get("my_watchlist") or []
    if not my_watchlist or all(item.get("price", 0) == 0 for item in my_watchlist):
        my_watchlist = companies
        print("Using companies data as quotes fallback", file=sys.stderr)
    my_watchlist = _with_status(my_watchlist, now)

    # 面板3 数据：市场参考；quotes 为空或价格为 0 时用 companies 前 3 项兜底
    market_ref = quotes.get("market_ref") or []
    if not market_ref or all(item.get("price", 0) == 0 for item in market_ref):
        market_ref = companies[:3] if len(companies) >= 3 else companies
        print("Using companies data as market_ref fallback", file=sys.stderr)
    market_ref = _with_status(market_ref, now)

    # 所有标的当日交易都已结束（已收盘/休市）时，逐行显示同一状态纯属冗余：
    # 整体状态只保留在面板标题"更新时间"处（那里本来就是 A 股整体状态，盘后=已收盘），
    # 行内不再逐个显示；只要还有任一标的未收盘（未开盘/交易中/午休），保持逐行独立显示
    if all(item.get("status") in CLOSED_STATUSES for item in my_watchlist + market_ref):
        my_watchlist = [dict(item, status="") for item in my_watchlist]
        market_ref = [dict(item, status="") for item in market_ref]

    render_split_market_panel(
        draw,
        PANEL_Y[0],
        MARKET_GROUPS["my_watchlist"]["title"],
        my_watchlist[:3],  # 左列：自选标的
        draw_compact_quote_column,
        my_watchlist[3:],  # 右列：自选标的
        updated,
    )

    # 面板2：板块热点（今日最热/最跌板块）
    draw_panel(draw, PANEL_Y[1], "板块热点", f"更新时间：{updated}" if updated else "", title_weight=700)

    # 使用已获取的完整板块数据（包含领涨股信息）
    all_sectors = markets.get("raw_sectors", [])

    # 排序获取最热和最冷板块
    if all_sectors:
        all_sectors.sort(key=lambda item: to_float(item.get("zdf")), reverse=True)
        hot_sectors = all_sectors[:3]  # 最热3个
        cold_sectors = all_sectors[-3:] if len(all_sectors) >= 3 else []  # 最冷3个
    else:
        hot_sectors = []
        cold_sectors = []

    # 左右分栏显示（参照其他面板的排版风格）
    content_top = PANEL_Y[1] + 59
    content_bottom = PANEL_Y[1] + PANEL_HEIGHT - 16
    divider_x = PANEL_X + PANEL_WIDTH // 2

    # 绘制中间分割线
    draw.line((divider_x, content_top - 3, divider_x, content_bottom + 3), fill=0, width=2)

    # 左侧：最热板块
    left_bounds = (PANEL_X + 16, content_top, divider_x - 10, content_bottom)
    render_sector_list(draw, left_bounds, hot_sectors, is_hot=True)

    # 右侧：最冷板块
    right_bounds = (divider_x + 12, content_top, PANEL_X + PANEL_WIDTH - 16, content_bottom)
    render_sector_list(draw, right_bounds, cold_sectors, is_hot=False)

    # 面板3 渲染：市场参考（左列A股，右列港美；数据已在上方统一准备并做盘后合并）
    render_split_market_panel(
        draw,
        PANEL_Y[2],
        MARKET_GROUPS["market_ref"]["title"],
        market_ref[:3],  # 左列：A股指数
        draw_compact_quote_column,
        market_ref[3:],  # 右列：港美指数
        updated,
    )

    return image


def render_sector_list(draw, bounds, sectors, is_hot=True):
    """渲染板块列表（显示名称、涨跌幅、领涨/领跌股）"""
    left, top, right, bottom = bounds
    name_font = font(SIZE_S)
    pct_font = font(SIZE_S, FONT_STRONG)
    leader_font = font(SIZE_XS)  # 领涨/领跌股名称用较小字号
    label_font = font(SIZE_XS, FONT_STRONG)  # 领涨/领跌标签用较小字号

    # 3个板块，每个占33%高度
    item_height = (bottom - top) / 3
    line_gap = 8  # 增加行间距，让领涨/领跌不贴紧板块名称

    for index in range(3):
        if index >= len(sectors):
            # 没有足够板块时显示占位符
            row_top = top + int(index * item_height)
            row_bottom = min(bottom, row_top + int(item_height))
            mid = row_top + int(item_height / 2)
            draw.text((left, mid - SIZE_S // 2), "暂无数据", font=name_font, fill=0)
            continue

        sector = sectors[index]
        item_top = top + int(index * item_height)
        item_bottom = min(bottom, item_top + int(item_height))

        if item_bottom <= item_top:
            continue

        # 参照draw_compact_quote_column的排版风格
        mid = item_top + int(item_height / 2)

        # 上部：板块名称 + 市场标记（腾讯/akshare 板块均为A股）
        pct_value = sector.get('pct')
        if pct_value is None:
            pct_value = to_float(sector.get('zdf', 0))
        pct_text = f"{pct_value:+.2f}%"
        pct_w = draw.textlength(pct_text, font=pct_font)
        tag_font = font(SIZE_XS)
        tag_text = "(A)"
        tag_w = draw.textlength(tag_text, font=tag_font)
        name_y = mid - SIZE_S - line_gap
        name = truncate_text(draw, sector.get("name", ""), name_font, right - 4 - left - pct_w - 6 - tag_w - 4)
        draw.text((left, name_y), name, font=name_font, fill=0)
        draw.text((left + draw.textlength(name, font=name_font) + 4, name_y + 3), tag_text, font=tag_font, fill=0)

        # 上部右侧：涨跌幅
        draw.text((right - 4, name_y), pct_text, font=pct_font, fill=0, anchor="ra")

        # 下部：领涨/领跌股（支持显示2个股）
        label_text = "领涨:" if is_hot else "领跌:"
        draw.text((left, mid + line_gap // 2), label_text, font=label_font, fill=0)

        label_width = draw.textlength(label_text, font=label_font)
        current_x = left + label_width

        # 支持新的数据结构（包含多个个股）
        stocks = sector.get("stocks", [])
        if stocks:
            # 显示2个股名称，用空格分隔
            stock_names = [stock.get("name", "") for stock in stocks[:2]]
            stock_text = " ".join(filter(None, stock_names))

            available_width = right - 4 - current_x
            stock_text = truncate_text(draw, stock_text, leader_font, available_width)
            draw.text((current_x, mid + line_gap // 2), stock_text, font=leader_font, fill=0)
        else:
            # 回退到旧的单个股数据结构（腾讯财经API）
            leader_data = sector.get("lzg", {})
            if isinstance(leader_data, dict) and leader_data.get("name"):
                leader_name = leader_data.get("name", "")
                available_width = right - 4 - current_x
                leader_text = truncate_text(draw, leader_name, leader_font, available_width)
                draw.text((current_x, mid + line_gap // 2), leader_text, font=leader_font, fill=0)
            else:
                draw.text((current_x, mid + line_gap // 2), "--", font=leader_font, fill=0)
