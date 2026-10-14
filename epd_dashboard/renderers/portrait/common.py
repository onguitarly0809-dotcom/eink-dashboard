"""渲染公共件：面板外框/标题栏、单行截断。"""
from epd_dashboard.config import PANEL_HEIGHT, PANEL_WIDTH, PANEL_X
from epd_dashboard.fonts import FONT_REGULAR, FONT_STRONG, SIZE_S, font


def truncate_text(draw, text, fnt, max_width):
    # 单行截断：超出 max_width 时从尾部截断加省略号
    if draw.textlength(text, font=fnt) <= max_width:
        return text
    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=fnt) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def wrap_text(draw, text, fnt, max_width):
    """多行排版：按显示宽度贪心断行（中文逐字断行即可，行首不保留空格）。返回行列表。"""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = ""
        for ch in raw:
            candidate = line + ch
            if line and draw.textlength(candidate, font=fnt) > max_width:
                lines.append(line)
                line = ch
            else:
                line = candidate
        lines.append(line)
    return lines


def text_right(draw, xy, value, fnt, fill=0):
    x, y = xy
    draw.text((x, y), value, font=fnt, fill=fill)
    return draw.textlength(value, font=fnt)


def draw_panel(draw, y, title, right, right_size=SIZE_S, title_weight=FONT_STRONG):
    draw.rectangle((PANEL_X, y, PANEL_X + PANEL_WIDTH, y + PANEL_HEIGHT), outline=0, width=3)
    header_y = y + 17
    line_y = header_y + 38
    draw.line((PANEL_X + 16, line_y, PANEL_X + PANEL_WIDTH - 16, line_y), fill=0, width=3)
    title_font = font(22, title_weight)
    right_font = font(right_size, FONT_REGULAR)
    t_ascent, t_descent = title_font.getmetrics()
    r_ascent, r_descent = right_font.getmetrics()
    title_h = t_ascent + t_descent
    right_h = r_ascent + r_descent
    # 模块标题：比 M(18) 大一号 -> 22
    draw.text((PANEL_X + 18, header_y), title, font=title_font, fill=0)
    # 右侧文字底部与标题底部对齐：二者到下划线间隔一致、同一水平线。
    # 与标题重叠时截断（"（历史）"标注/长来源标签曾把头部挤到文字重叠）
    avail = PANEL_WIDTH - 36 - draw.textlength(title, font=title_font) - 16
    if draw.textlength(right, font=right_font) > avail:
        right = truncate_text(draw, right, right_font, avail)
    draw.text((PANEL_X + PANEL_WIDTH - 18, header_y + title_h - right_h), right, font=right_font, fill=0, anchor="ra")
