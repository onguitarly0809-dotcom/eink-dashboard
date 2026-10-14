"""页3（行情，横版 V3）：沿用页2 定稿规则集。

规则集（页2 V3.10 验证通过）：8px 紧边距/6px 栏距、黑标题带（白字黑体 20/16px）、
18px 黑体正文（字重550）、1px 发丝分割线、
内容区严格 N 等分栅格（本页 6 行）、居中细字占位。
三栏：我的关注（个股）｜板块热点（最热3+最冷3）｜市场参考（指数）。
"""
import sys
from datetime import datetime

from PIL import Image, ImageDraw

from epd_dashboard.calendar_cn import market_status_for
from epd_dashboard.config import EPD_HEIGHT, EPD_WIDTH, MARKET_GROUPS
from epd_dashboard.fonts import FONT_STRONG, noto
from epd_dashboard.renderers.landscape.common import draw_tabler, frame, truncate_text
from epd_dashboard.renderers.landscape.page4_analysis import BODY_TEXT_WEIGHT
from epd_dashboard.util import to_float

MARKET_TAGS = {"A": "A", "HK": "港", "US": "美"}
CLOSED_STATUSES = frozenset({"已收盘", "休市"})

# 与页2 相同的顶满几何（2026-09-23 全屏顶满定稿：外圈灰晕即最外圈，无页边距）
GAP = 6
COL_W = (EPD_WIDTH - 2 * GAP) // 3
COL_X = tuple(i * (COL_W + GAP) for i in range(3))
BOX_Y0 = 0
BOX_Y1 = EPD_HEIGHT - 1
HEAD_H = 44
LINE_H = 26
ROWS = 6


def _column_box(index):
    x0 = COL_X[index]
    x1 = x0 + COL_W if index < 2 else EPD_WIDTH - 1  # 末栏贴右框
    return (x0, BOX_Y0, x1, BOX_Y1)


def _column_head(draw, box, title, right_meta, icon=None):
    """黑标题带（页2 同款），可带栏目图标，返回条目区顶 y。灰条已按用户要求移除。"""
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=0, width=1)
    draw.rectangle((x0, y0, x1, y0 + HEAD_H), fill=0)
    text_x = x0 + 14
    if icon:
        draw_tabler(draw, x0 + 21, y0 + HEAD_H // 2, 20, icon, fill=255)
        text_x = x0 + 44
    draw.text((text_x, y0 + HEAD_H // 2), title, font=noto(20, FONT_STRONG), fill=255, anchor="lm")
    if right_meta:
        meta_font = noto(16, 500)
        right_meta = truncate_text(draw, right_meta, meta_font, x1 - x0 - 28 - draw.textlength(title, font=noto(20, FONT_STRONG)))
        draw.text((x1 - 12, y0 + HEAD_H // 2), right_meta, font=meta_font, fill=255, anchor="rm")
    return y0 + HEAD_H


def _row_grid(draw, box, content_top):
    """六等分栅格 + 行边界发丝分割线，返回单行高度。"""
    x0, _, x1, y1 = box
    slot_h = (y1 - content_top) / ROWS
    for gap_index in range(1, ROWS):
        divider_y = content_top + gap_index * slot_h
        draw.line((x0 + 12, divider_y, x1 - 12, divider_y), fill=0, width=1)
    return slot_h


def _placeholder(draw, box, slot_top, slot_h):
    draw.text(((box[0] + box[2]) / 2, slot_top + slot_h / 2), "— 暂无行情 —",
              font=noto(16, 400), fill=0, anchor="mm")


def _quote_rows(draw, box, content_top, items, slot_h):
    """个股/指数双行条目：行1 名称+市场标记+交易状态，行2 价格+涨跌幅（右对齐）。"""
    x0, _, x1, _ = box
    name_font = noto(18, BODY_TEXT_WEIGHT)  # 550→450：与报告页正文同档（1-bit 试验已回退）
    small_font = noto(16, 400)
    price_font = noto(18, BODY_TEXT_WEIGHT)
    pct_font = noto(18, FONT_STRONG)
    for index in range(ROWS):
        slot_top = content_top + index * slot_h
        if index >= len(items):
            _placeholder(draw, box, slot_top, slot_h)
            continue
        item = items[index]
        status = item.get("status", "")
        tag = MARKET_TAGS.get(item.get("market", "A"), "")
        right_w = draw.textlength(status, font=small_font) if status else 0
        tag_text = f"({tag})" if tag else ""
        tag_w = draw.textlength(tag_text, font=small_font) if tag_text else 0
        text_x = x0 + 14
        right_x = x1 - 12
        name_max = (right_x - text_x) - (right_w + 8 if status else 0) - (tag_w + 6 if tag_text else 0)
        name = truncate_text(draw, item["name"], name_font, name_max)
        block_h = LINE_H * 2
        first_y = slot_top + (slot_h - block_h) / 2
        draw.text((text_x, first_y), name, font=name_font, fill=0)
        cursor = text_x + draw.textlength(name, font=name_font)
        if tag_text:
            draw.text((cursor + 6, first_y + 4), tag_text, font=small_font, fill=0)
        if status:
            draw.text((right_x, first_y + 4), status, font=small_font, fill=0, anchor="ra")
        if item.get("price", 0) > 0:
            arrow = "▲" if item["pct"] >= 0 else "▼"
            pct_text = f"{arrow}{item['pct']:+.2f}%"
            draw.text((right_x, first_y + LINE_H), pct_text, font=pct_font, fill=0, anchor="ra")
            pct_w = draw.textlength(pct_text, font=pct_font)
            draw.text((right_x - pct_w - 10, first_y + LINE_H), f"{item['price']:.2f}",
                      font=price_font, fill=0, anchor="ra")
        else:
            draw.text((right_x, first_y + LINE_H), "--", font=price_font, fill=0, anchor="ra")


def _sector_rows(draw, box, content_top, rows, slot_h):
    """板块双行条目：行1 板块名+涨跌幅（右对齐加粗），行2 领涨/领跌股（细字）。"""
    x0, _, x1, _ = box
    name_font = noto(18, BODY_TEXT_WEIGHT)  # 550→450：与报告页正文同档（1-bit 试验已回退）
    pct_font = noto(18, FONT_STRONG)
    leader_font = noto(16, 400)
    right_x = x1 - 12
    text_x = x0 + 14
    for index in range(ROWS):
        slot_top = content_top + index * slot_h
        if index >= len(rows):
            _placeholder(draw, box, slot_top, slot_h)
            continue
        sector, is_hot = rows[index]
        pct_value = sector.get("pct")
        if pct_value is None:
            pct_value = to_float(sector.get("zdf", 0))
        pct_text = f"{pct_value:+.2f}%"
        pct_w = draw.textlength(pct_text, font=pct_font)
        name = truncate_text(draw, sector.get("name", ""), name_font, right_x - text_x - pct_w - 10)
        block_h = LINE_H * 2
        first_y = slot_top + (slot_h - block_h) / 2
        draw.text((text_x, first_y), name, font=name_font, fill=0)
        draw.text((right_x, first_y), pct_text, font=pct_font, fill=0, anchor="ra")
        stocks = sector.get("stocks") or []
        if stocks:
            # akshare 路径：热板块带领涨股、冷板块带领跌股（抓取端已按方向排序取前二）
            label_text = "领涨:" if is_hot else "领跌:"
            stock_text = " ".join(s.get("name", "") for s in stocks[:2])
        elif is_hot:
            # 腾讯兜底仅有领涨股(lzg)字段：热板块如实展示领涨（lzg 即领涨股）
            label_text = "领涨:"
            leader = sector.get("lzg") or {}
            stock_text = leader.get("name", "") if isinstance(leader, dict) else ""
        else:
            # 冷板块无领跌数据（兜底接口不提供、东财成分股接口不可达时补查也失败）：
            # 个股行整体不显示——跌板块必须展示实际领跌，没有就不显示，
            # 绝不用领涨股冒充（2026-10-09 用户定稿）
            label_text = ""
            stock_text = ""
        if label_text:
            label_w = draw.textlength(label_text, font=leader_font)
            stock_text = stock_text or "--"
            stock_text = truncate_text(draw, stock_text, leader_font, right_x - text_x - label_w - 6)
            draw.text((text_x, first_y + LINE_H), label_text, font=leader_font, fill=0)
            draw.text((text_x + label_w + 6, first_y + LINE_H), stock_text, font=leader_font, fill=0)


def _with_status(items, now):
    """给行情项附加市场交易状态。返回副本，不污染缓存里的原对象。"""
    return [dict(item, status=market_status_for(item.get("market", "A"), now)) for item in items]


def render_page3(markets, now=None):
    image = Image.new("L", (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    frame(draw)
    if now is None:
        now = datetime.now()
    updated = markets.get("updated", "")
    if markets.get("stale"):
        updated = f"{updated}（历史）"
    quotes = markets.get("quotes") or {}
    companies = markets.get("companies") or []

    my_watchlist = quotes.get("my_watchlist") or []
    if not my_watchlist or all(item.get("price", 0) == 0 for item in my_watchlist):
        my_watchlist = companies
        print("Using companies data as quotes fallback", file=sys.stderr)
    my_watchlist = _with_status(my_watchlist, now)

    market_ref = quotes.get("market_ref") or []
    if not market_ref or all(item.get("price", 0) == 0 for item in market_ref):
        market_ref = companies[:3] if len(companies) >= 3 else companies
        print("Using companies data as market_ref fallback", file=sys.stderr)
    market_ref = _with_status(market_ref, now)

    # 盘后逐行同状态冗余：整体状态保留在标题带，行内不再重复（竖版同款逻辑）
    if all(item.get("status") in CLOSED_STATUSES for item in my_watchlist + market_ref):
        my_watchlist = [dict(item, status="") for item in my_watchlist]
        market_ref = [dict(item, status="") for item in market_ref]

    all_sectors = markets.get("raw_sectors", [])
    if all_sectors:
        all_sectors = sorted(all_sectors, key=lambda item: to_float(item.get("zdf")), reverse=True)
        hot_sectors = all_sectors[:3]
        cold_sectors = all_sectors[-3:] if len(all_sectors) >= 3 else []
    else:
        hot_sectors = []
        cold_sectors = []

    columns = [
        (MARKET_GROUPS["my_watchlist"]["title"], "", "star"),
        ("板块热点", "", "flame"),
        (MARKET_GROUPS["market_ref"]["title"], f"更新 {updated}" if updated else "", "chart-line"),
    ]
    for index, (title, meta, icon) in enumerate(columns):
        box = _column_box(index)
        content_top = _column_head(draw, box, title, meta, icon=icon)
        slot_h = _row_grid(draw, box, content_top)
        if index == 0:
            _quote_rows(draw, box, content_top, my_watchlist[:ROWS], slot_h)
        elif index == 1:
            _sector_rows(draw, box, content_top,
                         [(s, True) for s in hot_sectors] + [(s, False) for s in cold_sectors], slot_h)
        else:
            _quote_rows(draw, box, content_top, market_ref[:ROWS], slot_h)
    return image
