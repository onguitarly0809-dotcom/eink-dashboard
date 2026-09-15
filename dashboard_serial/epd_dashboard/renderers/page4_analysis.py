"""AI 归因报告整页排版组件：页4（板块）与页5（智谱AI）共用。

正文按报告实际长度在候选字号中自适应选最大可容纳字号，
小节标题（【】行）加粗并带左侧竖线强调；页面有富余时把剩余高度
均摊到各小节间距，让短报告也铺满整页。
"""
from PIL import Image, ImageDraw

from epd_dashboard.config import HEIGHT, WIDTH
from epd_dashboard.fonts import FONT_REGULAR, FONT_STRONG, SIZE_S, SIZE_XXS, font
from epd_dashboard.renderers.common import truncate_text, wrap_text

MARGIN_X = 18
LINE_GAP = 6          # 正文字号与行距的差值（约1.3倍行距，墨水屏上更易读）
HEADER_GAP = 8        # 小节标题字号与行距的差值
HEADER_SPACE = 7      # 每个小节标题前的最小留白（页面有富余时按剩余高度均摊，上限 +20px）
HEADER_SPACE_MAX = 20
HEADER_UNDERLINE_GAP = 6  # 小节标题下通栏细线占用的额外高度（_measure 必须计入，否则误判溢出截断）
HEADER_INDENT = 13    # 小节标题因左侧竖线强调而右缩进的宽度
BODY_SIZES = (16, 15, 14, 12)  # 自适应字号候选：从大到小取第一个放得下的（16px 为目标字号，15 为长报告过渡档）
INSIGHT_BODY_SIZES = (16, 15, 14, 12)  # 页4专用：缩小字号以容纳更长内容
STOCK_BODY_SIZES = (18, 16, 15, 14, 12)  # 页5专用：取消风险提示后优先放大正文
SUMMARY_SIZE = 16     # 页首速览行字号
CHART_HEIGHT = 132    # 页5 分时折线面板总高（含价格叠加行与底部时间刻度）


def _segments(text):
    """把报告拆成 (是否小节标题, 行内容)，跳过空行。"""
    out = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped:
            out.append((stripped.startswith("【") and "】" in stripped, stripped))
    return out


def _measure(draw, segments, size, content_width):
    """按指定字号试排全部小节，返回 (总高度, 正文字体, 标题字体, 正文行距, 标题行距)。

    必须与实际绘制占用一致：标题除行高外还有下划线的 HEADER_UNDERLINE_GAP。
    """
    body_font = font(size)
    header_font = font(size + 2, FONT_STRONG)
    line_h = size + LINE_GAP
    header_h = size + HEADER_GAP
    total = 0
    for index, (is_header, seg) in enumerate(segments):
        fnt = header_font if is_header else body_font
        width = content_width - (HEADER_INDENT if is_header else 0)
        total += (header_h if is_header else line_h) * len(wrap_text(draw, seg, fnt, width))
        if is_header:
            total += HEADER_UNDERLINE_GAP
            if index > 0:
                total += HEADER_SPACE
    return total, body_font, header_font, line_h, header_h


def _select_body_size(draw, segments, content_width, height_budget, body_sizes=BODY_SIZES):
    """从大到小选择第一个能完整容纳的字号；都放不下时用最小字号并交给绘制层截断。"""
    for size in body_sizes:
        layout = _measure(draw, segments, size, content_width)
        if layout[0] <= height_budget:
            return size, *layout
    size = body_sizes[-1]
    return size, *_measure(draw, segments, size, content_width)


def _strip_insight_metadata(text):
    """页4正文不再重复主题/领域两个元信息小节，直接从核心知识开始。"""
    metadata_sections = {"【主题名称】", "【所属领域】"}
    content_sections = {
        "【核心知识】",
        "【背后的机制】",
        "【生活里的样子】",
        "【怎么用起来】",
    }
    output = []
    skipping = False
    for raw in text.splitlines():
        line = raw.strip()
        metadata_marker = next((section for section in metadata_sections if section in line), None)
        content_marker = next((section for section in content_sections if section in line), None)
        if metadata_marker:
            skipping = True
            continue
        if content_marker:
            skipping = False
            remainder = line.replace(content_marker, "", 1).strip()
            output.append(content_marker)
            if remainder:
                output.append(remainder)
            continue
        if line and not skipping:
            output.append(line)
    return "\n".join(output)


def _fit_join(draw, items, fnt, max_width):
    """把列表项用顿号连接，按整项粒度贪心装填（放不下的项整块舍去，绝不切半个数字）。"""
    parts = []
    for item in items:
        candidate = "、".join(parts + [item])
        if parts and draw.textlength(candidate, font=fnt) > max_width:
            break
        parts.append(item)
    return "、".join(parts)


def _fmt_hhmm(value):
    return f"{int(value) // 100:02d}:{int(value) % 100:02d}"


def _draw_chart(draw, chart, left, right, top):
    """绘制分时折线面板，返回面板底边 y。

    chart: {"price_text", "sub_text", "points": [(hhmm, price)...], "prev_close"}。
    面板 = 价格叠加行 + 折线区 + 底部时间刻度；昨收为虚线基准；午休跳档处标时刻。
    """
    bottom = top + CHART_HEIGHT
    draw.rectangle((left, top, right, bottom), outline=0, width=2)

    price_font = font(20, FONT_STRONG)
    small_font = font(SIZE_XXS)
    draw.text((left + 10, top + 7), chart.get("price_text", ""), font=price_font, fill=0)
    price_w = draw.textlength(chart.get("price_text", ""), font=price_font)
    p_ascent, p_descent = price_font.getmetrics()
    sub_text = chart.get("sub_text", "")
    sub_avail = right - left - 20 - price_w - 12
    if sub_text and sub_avail > 40:
        sub_text = truncate_text(draw, sub_text, small_font, sub_avail)
        draw.text((right - 10, top + 7 + (p_ascent + p_descent) - 13), sub_text,
                  font=small_font, fill=0, anchor="ra")

    points = [(int(t), float(p)) for t, p in (chart.get("points") or [])]
    if len(points) < 2:
        draw.text(((left + right) // 2, (top + bottom) // 2), "暂无分时数据（先刷新行情）",
                  font=font(SIZE_S), fill=0, anchor="mm")
        return bottom

    x0, x1 = left + 10, right - 10
    y0, y1 = top + 32, bottom - 16
    prices = [p for _, p in points]
    prev_close = float(chart.get("prev_close") or 0)
    if prev_close > 0:
        prices.append(prev_close)
    lo, hi = min(prices), max(prices)
    pad = (hi - lo) * 0.1 or max(1.0, hi * 0.002)
    lo, hi = lo - pad, hi + pad

    def xy(index, price):
        return (x0 + (x1 - x0) * index / (len(points) - 1),
                y1 - (price - lo) / (hi - lo) * (y1 - y0))

    # 昨收虚线基准线
    if prev_close > 0:
        _, y_pc = xy(0, prev_close)
        dash_x = x0
        while dash_x < x1:
            draw.line((dash_x, y_pc, min(dash_x + 5, x1), y_pc), fill=0, width=1)
            dash_x += 9

    draw.line([xy(i, p) for i, (_, p) in enumerate(points)], fill=0, width=2, joint="curve")

    # 底部时间刻度：开盘 / 午休跳档 / 最新
    label_y = y1 + 3
    draw.text((x0, label_y), _fmt_hhmm(points[0][0]), font=small_font, fill=0, anchor="la")
    draw.text((x1, label_y), _fmt_hhmm(points[-1][0]), font=small_font, fill=0, anchor="ra")
    gap_index, gap_size = -1, 0
    for i in range(len(points) - 1):
        delta = points[i + 1][0] - points[i][0]
        if delta > gap_size:
            gap_index, gap_size = i, delta
    if gap_size >= 30:  # 午休（1200→1300）
        mid_x = x0 + (x1 - x0) * (gap_index + 1) / (len(points) - 1)
        draw.text((mid_x, label_y), _fmt_hhmm(points[gap_index + 1][0]),
                  font=small_font, fill=0, anchor="ma")
    return bottom


def render_report_page(title, meta_text, summary_pairs, text, empty_notes, page_tag="",
                       chart=None, body_sizes=BODY_SIZES):
    """绘制一整页 AI 归因报告。

    title: 主标题；meta_text: 标题栏右侧文字（更新时间/模型/历史标注），过长时自动降级
    summary_pairs: [(粗体标签, 内容或字符串列表)] 页首速览表格行，内容建议带 ▲/▼ 涨跌箭头；
                   列表按整项粒度装填，放不下的项整块舍去
    text: 【】小节结构的报告正文；empty_notes: text 为空时逐段显示的引导文案
    page_tag: 右下角页码角标（如 "4/5"），轮播时便于辨认当前页
    chart: 可选分时图面板（见 _draw_chart），画在速览表格与正文之间，页5 使用
    """
    image = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=0, width=2)
    content_width = WIDTH - 2 * MARGIN_X

    # ---------- 标题栏（对齐 draw_panel 的头部规格）；右侧文字过长时降级避免与标题相撞 ----------
    title_font = font(22, FONT_STRONG)
    header_y = 17
    draw.text((MARGIN_X, header_y), title, font=title_font, fill=0)
    t_ascent, t_descent = title_font.getmetrics()
    title_w = draw.textlength(title, font=title_font)
    meta_avail = content_width - title_w - 16
    meta_font = font(SIZE_S, FONT_REGULAR)
    if draw.textlength(meta_text, font=meta_font) > meta_avail:
        meta_font = font(SIZE_XXS, FONT_REGULAR)
        if draw.textlength(meta_text, font=meta_font) > meta_avail and " · " in meta_text:
            # 仍放不下：去掉模型名，只留更新时间/历史标注
            meta_text = meta_text.split(" · ", 1)[0]
        if draw.textlength(meta_text, font=meta_font) > meta_avail:
            meta_text = truncate_text(draw, meta_text, meta_font, meta_avail)
    r_ascent, r_descent = meta_font.getmetrics()
    draw.text((WIDTH - MARGIN_X, header_y + (t_ascent + t_descent) - (r_ascent + r_descent)),
              meta_text, font=meta_font, fill=0, anchor="ra")
    line_y = header_y + 38
    draw.line((MARGIN_X - 2, line_y, WIDTH - MARGIN_X + 2, line_y), fill=0, width=3)

    # ---------- 页首速览表格（外框 + 行分隔线：标签居左加粗，数值居右，与行情页风格统一） ----------
    label_font = font(SUMMARY_SIZE, FONT_STRONG)
    value_font = font(SUMMARY_SIZE)
    row_h = SUMMARY_SIZE + 8
    box_top = line_y + 12
    box_left, box_right = MARGIN_X, WIDTH - MARGIN_X
    for index, (label, value) in enumerate(summary_pairs):
        row_top = box_top + index * row_h
        draw.text((box_left + 10, row_top + 4), label, font=label_font, fill=0)
        label_w = draw.textlength(label, font=label_font)
        value_avail = box_right - box_left - 20 - label_w - 12
        if isinstance(value, (list, tuple)):
            value = _fit_join(draw, list(value), value_font, value_avail)
        else:
            value = truncate_text(draw, value, value_font, value_avail)
        draw.text((box_right - 10, row_top + 4), value, font=value_font, fill=0, anchor="ra")
        if index < len(summary_pairs) - 1:
            draw.line((box_left + 1, row_top + row_h, box_right - 1, row_top + row_h), fill=0, width=1)
    box_bottom = box_top + len(summary_pairs) * row_h
    draw.rectangle((box_left, box_top, box_right, box_bottom), outline=0, width=2)
    if chart:
        chart_bottom = _draw_chart(draw, chart, box_left, box_right, box_bottom + 10)
        y = chart_bottom + 10
    else:
        y = box_bottom + 12
    draw.line((MARGIN_X - 2, y, WIDTH - MARGIN_X + 2, y), fill=0, width=2)
    y += 12

    # ---------- 正文（自适应字号，尽量填满页面） ----------
    text = (text or "").strip()
    content_width = WIDTH - 2 * MARGIN_X
    # 右下角有页码角标时，正文底部为其预留一行空间，避免正文与角标重叠
    bottom = HEIGHT - (34 if page_tag else 16)

    if not text:
        note_font = font(SIZE_S)
        for note in empty_notes:
            for line in wrap_text(draw, note, note_font, content_width):
                draw.text((MARGIN_X, y), line, font=note_font, fill=0)
                y += SIZE_S + 6
            y += 4
        return image

    segments = _segments(text)
    # 从大到小选第一个放得下的字号；页面有富余时把剩余高度均摊到各小节间距（上限 HEADER_SPACE_MAX），
    # 让短报告也铺满整页而不是堆在上半屏
    height_budget = bottom - y
    size, total, body_font, header_font, line_h, header_h = _select_body_size(
        draw, segments, content_width, height_budget, body_sizes
    )
    n_headers = sum(1 for is_header, _ in segments if is_header)
    extra_space = min(HEADER_SPACE_MAX, max(0, (height_budget - total) // max(1, n_headers - 1))) if n_headers > 1 else 0

    for index, (is_header, seg) in enumerate(segments):
        if is_header:
            if index > 0:
                y += HEADER_SPACE + extra_space
            n_lines = len(wrap_text(draw, seg, header_font, content_width - HEADER_INDENT))
            # 左侧竖线强调小节标题
            draw.rectangle((MARGIN_X, y + 2, MARGIN_X + 3, y + 2 + header_h * n_lines - 6), fill=0)
            for piece in wrap_text(draw, seg, header_font, content_width - HEADER_INDENT):
                if y + header_h > bottom:
                    draw.text((MARGIN_X, min(y, bottom - line_h)), "……（内容过长，已截断）",
                              font=body_font, fill=0)
                    return image
                draw.text((MARGIN_X + HEADER_INDENT, y), piece, font=header_font, fill=0)
                y += header_h
            # 标题下通栏细线：与竖线配合形成清晰的分节节奏
            draw.line((MARGIN_X, y + 2, WIDTH - MARGIN_X, y + 2), fill=0, width=1)
            y += HEADER_UNDERLINE_GAP
        else:
            for piece in wrap_text(draw, seg, body_font, content_width):
                if y + line_h > bottom:
                    draw.text((MARGIN_X, min(y, bottom - line_h)), "……（内容过长，已截断）",
                              font=body_font, fill=0)
                    return image
                draw.text((MARGIN_X, y), piece, font=body_font, fill=0)
                y += line_h

    # ---------- 右下角页码角标 ----------
    if page_tag:
        tag_font = font(SIZE_XXS, FONT_REGULAR)
        draw.text((WIDTH - MARGIN_X, HEIGHT - 24), page_tag, font=tag_font, fill=0, anchor="ra")
    return image


def _meta_text(analysis):
    """标题栏右侧：历史标注在前（空间不足被截断时也保证保留），之后更新时间 · 模型。"""
    a = analysis or {}
    updated = a.get("updated", "")
    stale = "（历史）" if a.get("stale") else ""
    if not updated:
        return "未生成"
    return f"{stale}更新 {updated} · {a.get('model', '')}"


def _pct_text(pct):
    """带涨跌箭头的百分比（与页3行情页同款视觉语言）。"""
    try:
        value = float(pct)
    except (TypeError, ValueError):
        return "--"
    return f"{'▲' if value >= 0 else '▼'}{value:+.2f}%"


def render_page4(analysis):
    """页4：多领域认知洞察紧凑版式。"""
    a = analysis or {}
    topic = (a.get("topic") or "待生成").strip().strip("【】")
    domain = a.get("domain") or "轮换生成"
    notes = (
        "暂无分析报告。",
        "自动生成：每次触发本页都会重新生成，并避开历史主题。",
        "手动生成：运行 dashboard_control.ps1 analysis。",
    )
    text = _strip_insight_metadata(a.get("text", "")) if a.get("kind") == "insight" else ""

    image = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=0, width=2)
    content_width = WIDTH - 2 * MARGIN_X
    box_right = WIDTH - MARGIN_X

    title_font = font(22, FONT_STRONG)
    title_y = 16
    draw.text((MARGIN_X, title_y), "认知洞察", font=title_font, fill=0)
    title_ascent, title_descent = title_font.getmetrics()
    meta_text = _meta_text(a)
    meta_font = font(SIZE_S, FONT_REGULAR)
    title_width = draw.textlength("认知洞察", font=title_font)
    meta_avail = content_width - title_width - 16
    if draw.textlength(meta_text, font=meta_font) > meta_avail:
        meta_font = font(SIZE_XXS, FONT_REGULAR)
        if " · " in meta_text and draw.textlength(meta_text, font=meta_font) > meta_avail:
            meta_text = meta_text.split(" · ", 1)[0]
        if draw.textlength(meta_text, font=meta_font) > meta_avail:
            meta_text = truncate_text(draw, meta_text, meta_font, meta_avail)
    meta_ascent, meta_descent = meta_font.getmetrics()
    draw.text((box_right, title_y + (title_ascent + title_descent) - (meta_ascent + meta_descent)),
              meta_text, font=meta_font, fill=0, anchor="ra")
    title_line_y = title_y + 38
    draw.line((MARGIN_X - 2, title_line_y, WIDTH - MARGIN_X + 2, title_line_y), fill=0, width=3)

    topic_font = font(24, FONT_STRONG)
    domain_font = font(SIZE_S, FONT_REGULAR)
    domain_text = f"[{domain}]"
    domain_width = draw.textlength(domain_text, font=domain_font)
    topic_avail = content_width - domain_width - 14
    display_topic = truncate_text(draw, topic, topic_font, topic_avail)
    topic_y = title_line_y + 11
    draw.text((MARGIN_X, topic_y), display_topic, font=topic_font, fill=0)
    topic_ascent, topic_descent = topic_font.getmetrics()
    domain_ascent, domain_descent = domain_font.getmetrics()
    draw.text((box_right,
               topic_y + (topic_ascent + topic_descent) - (domain_ascent + domain_descent)),
              domain_text, font=domain_font, fill=0, anchor="ra")
    topic_bottom = topic_y + topic_ascent + topic_descent
    draw.line((MARGIN_X - 2, topic_bottom + 7, WIDTH - MARGIN_X + 2, topic_bottom + 7),
              fill=0, width=2)

    y = topic_bottom + 19
    bottom = HEIGHT - 34
    if not text:
        note_font = font(SIZE_S)
        for note in notes:
            for line in wrap_text(draw, note, note_font, content_width):
                draw.text((MARGIN_X, y), line, font=note_font, fill=0)
                y += SIZE_S + 6
            y += 4
        draw.text((WIDTH - MARGIN_X, HEIGHT - 24), "4/5", font=font(SIZE_XXS), fill=0, anchor="ra")
        return image

    segments = _segments(text)
    height_budget = bottom - y
    size, total, body_font, header_font, line_h, header_h = _select_body_size(
        draw, segments, content_width, height_budget, INSIGHT_BODY_SIZES
    )
    n_headers = sum(1 for is_header, _ in segments if is_header)
    extra_space = min(HEADER_SPACE_MAX,
                      max(0, (height_budget - total) // max(1, n_headers - 1))) if n_headers > 1 else 0
    for index, (is_header, seg) in enumerate(segments):
        if is_header:
            if index > 0:
                y += HEADER_SPACE + extra_space
            n_lines = len(wrap_text(draw, seg, header_font, content_width - HEADER_INDENT))
            draw.rectangle((MARGIN_X, y + 2, MARGIN_X + 3,
                            y + 2 + header_h * n_lines - 6), fill=0)
            for piece in wrap_text(draw, seg, header_font, content_width - HEADER_INDENT):
                if y + header_h > bottom:
                    draw.text((MARGIN_X, min(y, bottom - line_h)), "……（内容过长，已截断）",
                              font=body_font, fill=0)
                    return image
                draw.text((MARGIN_X + HEADER_INDENT, y), piece, font=header_font, fill=0)
                y += header_h
            draw.line((MARGIN_X, y + 2, WIDTH - MARGIN_X, y + 2), fill=0, width=1)
            y += HEADER_UNDERLINE_GAP
        else:
            for piece in wrap_text(draw, seg, body_font, content_width):
                if y + line_h > bottom:
                    draw.text((MARGIN_X, min(y, bottom - line_h)), "……（内容过长，已截断）",
                              font=body_font, fill=0)
                    return image
                draw.text((MARGIN_X, y), piece, font=body_font, fill=0)
                y += line_h

    draw.text((WIDTH - MARGIN_X, HEIGHT - 24), "4/5", font=font(SIZE_XXS), fill=0, anchor="ra")
    return image
