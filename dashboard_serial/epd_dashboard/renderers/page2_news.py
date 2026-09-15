"""页2（三栏新闻）：国内/国际/AI，每栏 5 条单行，01-05 编号。"""
from PIL import Image, ImageDraw

from epd_dashboard.config import HEIGHT, PANEL_HEIGHT, PANEL_WIDTH, PANEL_X, PANEL_Y, WIDTH
from epd_dashboard.fetchers.news import NEWS_TITLES
from epd_dashboard.fonts import FONT_STRONG, SIZE_S, font
from epd_dashboard.renderers.common import draw_panel, truncate_text


def render_news_panel(draw, panel_y, title, items, updated="", source="", pinned_first=False, badge="新"):
    parts = []
    if source:
        parts.append(f"数据源:{source}")
    if updated:
        parts.append(f"更新时间:{updated}")
    right = "  ".join(parts)
    draw_panel(draw, panel_y, title, right, title_weight=700)
    p = panel_y
    line_y = p + 17 + 38
    content_top = line_y + 4
    content_bottom = p + PANEL_HEIGHT - 16
    slot_h = (content_bottom - content_top) / 5
    number_font = font(SIZE_S, FONT_STRONG)
    text_font = font(SIZE_S)
    text_x = PANEL_X + 18 + 44
    max_width = PANEL_X + PANEL_WIDTH - 18 - text_x
    for index in range(5):
        slot_top = content_top + int(index * slot_h)
        center_y = slot_top + int((slot_h - SIZE_S) / 2)
        if index == 0 and pinned_first and items:
            # 置顶行：编号位画细框角标字（如"新"/"价"）替代编号，不占用标题一行的宽度；
            # 后续条目按 01 起重新编号
            draw.rectangle((PANEL_X + 17, center_y - 3, PANEL_X + 39, center_y + SIZE_S + 1),
                           outline=0, width=1)
            draw.text((PANEL_X + 20, center_y), badge, font=number_font, fill=0)
        else:
            label = f"{index:02d}" if pinned_first else f"{index + 1:02d}"
            draw.text((PANEL_X + 18, center_y), label, font=number_font, fill=0)
        if index < len(items):
            display = truncate_text(draw, items[index], text_font, max_width)
            draw.text((text_x, center_y), display, font=text_font, fill=0)
        else:
            draw.text((text_x, center_y), "暂无新闻", font=text_font, fill=0)


def render_page2(news):
    image = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=0, width=2)
    base_updated = news.get("updated", "")
    stale = news.get("stale", False)
    for index, key in enumerate(("domestic", "international", "ai")):
        updated = f"{base_updated}（历史）" if stale else base_updated
        source = news.get(f"{key}_source", "") or ""
        render_news_panel(draw, PANEL_Y[index], NEWS_TITLES[key], news.get(key) or [], updated, source,
                          pinned_first=bool(news.get(f"{key}_pinned")),
                          badge=news.get(f"{key}_badge") or "新")
    return image
