"""页2（三栏新闻，横版 V3.3）：真机可读性优先的重排。

实机反馈整改（用户逐条）：
- 黑底标题带与更新时间：像素字完全认不出 → 思源黑体 20px/16px 白字
- 正文粗细不均、偏小 → 思源黑体 18px/字重550（1-bit 下笔画更匀），行距 26
- 空白多 → 字号与行距整体放大吃掉留白
- 来源灰条已移除（用户判定无信息量），条目区直接从标题带下缘起算
栏目黑带保留为纯黑色块锚点；编号用加粗黑体（V2 同款"小但清晰"路线的放大版）。
"""
from PIL import Image, ImageDraw

from epd_dashboard.config import EPD_HEIGHT, EPD_WIDTH
from epd_dashboard.fetchers.news import NEWS_TITLES
from epd_dashboard.fonts import FONT_STRONG, noto
from epd_dashboard.renderers.landscape.common import draw_tabler, frame, truncate_text, wrap_text
from epd_dashboard.renderers.landscape.page4_analysis import BODY_TEXT_WEIGHT

ITEM_FONT_SIZE = 18
LINE_H = 26
HEAD_H = 44

# 栏目几何（2026-09-23 全屏顶满定稿）：外圈灰晕即最外圈，栏目框直接贴屏幕四缘
# （外边线与 1px 外框重合），无页边距；栏间距 6px 不变，末栏贴右缘（整除余数并入末栏）
GAP = 6
COL_W = (EPD_WIDTH - 2 * GAP) // 3
COL_X = tuple(i * (COL_W + GAP) for i in range(3))

# V3.8 无序号版：条目顺序=最新在上，序号无定位意义，删除编号列（框+虚线），
# 正文起点提前到 x0+14，每行容量 11→12 字。行内角标方框为临时新闻任务置顶专用
# （新模型置顶行 2026-09-24 起按正常正文显示，不再打"新"角标）。
TEXT_X_OFF = 14
COLUMN_BOX_Y0 = 0
COLUMN_BOX_Y1 = EPD_HEIGHT - 1


def render_news_column(draw, box, title, items, updated="", pinned_first=False,
                       badge="新", icon=None):
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=0, width=1)

    # 黑色标题带：纯黑块 + 白字思源黑体（20px 标题 / 16px 时间）+ 栏目图标
    draw.rectangle((x0, y0, x1, y0 + HEAD_H), fill=0)
    text_x = x0 + 14
    if icon:
        draw_tabler(draw, x0 + 21, y0 + HEAD_H // 2, 20, icon, fill=255)
        text_x = x0 + 44
    draw.text((text_x, y0 + HEAD_H // 2), title, font=noto(20, FONT_STRONG), fill=255, anchor="lm")
    if updated:
        draw.text((x1 - 12, y0 + HEAD_H // 2), updated, font=noto(16, 500), fill=255, anchor="rm")

    # 条目区：标题带下缘 → 栏底边框（来源灰条已按用户要求移除），纵向严格五等分；
    # 条目在各自行内垂直居中，分割线落在行边界
    content_top = y0 + HEAD_H
    content_bottom = y1
    slot_h = (content_bottom - content_top) / 5
    text_x = x0 + TEXT_X_OFF
    max_width = x1 - 12 - text_x
    text_font = noto(ITEM_FONT_SIZE, BODY_TEXT_WEIGHT)  # 550→450：与页4/5 报告正文同档（1-bit 补偿随清洗帧退役）
    # 条目间分割线（1px 发丝线，占满内容宽）：条目分组信号由"序号+行距"改为"行距+分割线"
    for gap_index in range(1, 5):
        divider_y = content_top + gap_index * slot_h
        draw.line((x0 + 12, divider_y, x1 - 12, divider_y), fill=0, width=1)
    for index in range(5):
        slot_top = content_top + index * slot_h
        is_pinned = index == 0 and pinned_first and bool(items)
        entry = items[0] if is_pinned else (items[index] if index < len(items) else None)
        if entry is None:
            # 空槽占位：小号细字居中 + 两侧短线，明确"这不是一条新闻"（评审抓过的误读问题）
            draw.text(((x0 + x1) / 2, slot_top + slot_h / 2), "— 暂无新闻 —",
                      font=noto(16, 400), fill=0, anchor="mm")
            continue
        # 临时任务置顶条目行内角标占位，其余条目正文顶格
        indent = 28 if is_pinned else 0
        eff_max = max_width - indent
        lines = wrap_text(draw, entry, text_font, eff_max)
        if len(lines) > 2:
            # 两行封顶：有整行被丢弃时，第二行即使自身放得下也强制让出省略号空间，
            # 否则会静默丢字（评审抓到的真 bug）
            lines = lines[:2]
            ell = "…"
            while lines[1] and draw.textlength(lines[1] + ell, font=text_font) > eff_max:
                lines[1] = lines[1][:-1]
            lines[1] = (lines[1] + ell) if lines[1] else ell
        block_h = LINE_H * len(lines)
        first_line_y = slot_top + (slot_h - block_h) / 2
        if is_pinned:
            draw.rectangle((text_x, first_line_y + 1, text_x + 22, first_line_y + 23), outline=0, width=1)
            draw.text((text_x + 11, first_line_y + 12), badge, font=noto(16, FONT_STRONG), fill=0, anchor="mm")
        for line_index, piece in enumerate(lines):
            draw.text((text_x + indent, first_line_y + line_index * LINE_H), piece, font=text_font, fill=0)


def render_page2(news):
    image = Image.new("L", (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    frame(draw)
    base_updated = news.get("updated", "")
    stale = news.get("stale", False)
    column_icons = {"domestic": "flag", "international": "world", "ai": "cpu"}
    for index, key in enumerate(("domestic", "international", "ai")):
        # 全页只保留一个更新时间：AI 栏（第三栏）右上角
        upd = f"{base_updated}（历史）" if stale else base_updated if key == "ai" else ""
        render_news_column(draw, _column_box(index), NEWS_TITLES[key], news.get(key) or [],
                           upd,
                           pinned_first=bool(news.get(f"{key}_pinned")),
                           badge=news.get(f"{key}_badge") or "新",
                           icon=column_icons[key])
    return image


def _column_box(index):
    x0 = COL_X[index]
    # 末栏 x1 直接贴右框（整除余数并入末栏，避免右缘留缝）
    x1 = x0 + COL_W if index < 2 else EPD_WIDTH - 1
    return (x0, COLUMN_BOX_Y0, x1, COLUMN_BOX_Y1)
