"""页4（认知洞察）/ 页5（智谱走势）报告排版（横版 V4）。

页1-3 定稿规则集的收尾应用：
- 标题带：黑底 44px + 白字黑体 20px + Tabler 图标 20px（页4 bulb / 页5 chart-candle）+ 右侧 16px 元信息
- 主题行（页4）：1px 黑框；左侧"主题：xxx"与标题带同字号（20/700），右侧领域右对齐（20/500）
- 内容区外框 (8,9,791,471)：与页1-3 栏目框同几何，跨页边框观感一致
- 正文：思源黑体双栏 17px/BODY_TEXT_WEIGHT 固定字号（页4/页5 统一，2026-09-23 字体同步定稿），
  小节头宋体 SERIF_TITLE_WEIGHT；小节头黑竖条+发丝线（19/650），跨栏自然对齐
"""
from PIL import Image, ImageDraw

from epd_dashboard.config import EPD_HEIGHT, EPD_WIDTH
from epd_dashboard.fonts import FONT_STRONG, noto, serif
from epd_dashboard.renderers.landscape.common import (
    _tokens,
    binarize_region,
    draw_tabler,
    frame,
    truncate_text,
    wrap_text,
)

MARGIN_X = 0   # 全屏顶满（2026-09-23）：外圈灰晕即最外圈，内容框贴屏幕四缘
BAND_H = 44
STRIP_H = 40
BAND_TOP = 0
# 内容区外框：与页1-3 栏目框同几何（8/9/791/471），配合 frame() 整页 1px 框，跨页观感一致
CONTENT_BOX = (MARGIN_X, BAND_TOP, EPD_WIDTH - MARGIN_X - 1, EPD_HEIGHT - 1)
LINE_GAP = 6            # 正文字号与行距的差值（约1.3倍行距）
HEADER_GAP = 4          # 小节标题字号与行高的差值
HEADER_RULE_GAP = 11    # 小节标题下细线与首行正文的净空（6→16→11，用户逐档微调+5px；计高/装箱/绘制共用）
HEADER_INDENT = 13      # 小节标题因左侧竖条强调而右缩进的宽度
SECTION_GAP = 5         # 小节之间的统一节距（2026-09-23 用户逐档定稿：20→10→5。恒定值、左右栏
                        # 每条缝恒等、取消逐栏齐行拉伸——拉伸按各栏剩余独立均摊会让左栏单缝
                        # 30px/右栏双缝 10px 不对称；恒定 20px 挤掉约 30px 版面致配额贴满时
                        # 截断出屏。5px 节缝+小节头竖条/下划线仍清晰分组；余量留栏底）
COLUMN_GAP = 28         # 双栏正文中缝宽度
INSIGHT_BODY_SIZES = (17,)             # 页4：恒定 17px（生成端配额按 17px 版面容量约束，硬校验不超）
STOCK_BODY_SIZES = (17,)               # 页5：2026-09-23 与页4字体字号同步（14→17，配额390→265）
CHART_HEIGHT = 102      # 页5 分时折线面板总高：112→102 给 17px 正文让一行缓冲（275字贴容量上限曾溢出一行）
# 标题层宋体字重：真机逐档调优 700→600→650（650 与 450 正文拉开层次且细横画稳定）
SERIF_TITLE_WEIGHT = 650
# 正文字重：四灰模式下抗锯齿灰边参与成字（浅灰档=墨），视觉增粗，
# 550→500→450 逐档真机调优 + pack_4gray 白界 192→160 收窄灰边（真机反馈）
BODY_TEXT_WEIGHT = 450


def _band_head(draw, title, meta, icon):
    """报告页顶部黑标题带（44px，页3 同款）：Tabler 图标 + 20px 白字标题 + 右侧 16px 元信息。"""
    y0, y1 = BAND_TOP, BAND_TOP + BAND_H
    draw.rectangle((MARGIN_X, y0, CONTENT_BOX[2], y1), fill=0)
    draw_tabler(draw, MARGIN_X + 21, (y0 + y1) / 2, 20, icon, fill=255)
    draw.text((MARGIN_X + 44, (y0 + y1) / 2), title, font=noto(20, FONT_STRONG), fill=255, anchor="lm")
    if meta:
        draw.text((EPD_WIDTH - MARGIN_X - 12, (y0 + y1) / 2), meta, font=noto(16, 500),
                  fill=255, anchor="rm")
    return y1


def _topic_line(image, draw, y, left_text, right_text):
    """主题独立行：1px 黑框；左侧主题为思源宋体（20/700，绘制后层内阈值160保细横画），
    右侧领域等大字右对齐（黑体 20/500）。返回底 y。"""
    draw.rectangle((MARGIN_X, y, CONTENT_BOX[2], y + STRIP_H), outline=0, width=1)
    mid_y = y + STRIP_H / 2
    pad = 14
    main_font = serif(20, SERIF_TITLE_WEIGHT)
    meta_font = noto(20, 500)
    right_w = 0
    if right_text:
        right_text = truncate_text(draw, right_text, meta_font, 240)
        right_w = draw.textlength(right_text, font=meta_font)
        draw.text((CONTENT_BOX[2] - pad, mid_y), right_text, font=meta_font, fill=0, anchor="rm")
    if left_text:
        max_w = CONTENT_BOX[2] - MARGIN_X - pad * 2 - right_w - (12 if right_w else 0)
        left_text = truncate_text(draw, left_text, main_font, max_w)
        draw.text((MARGIN_X + pad, mid_y), left_text, font=main_font, fill=0, anchor="lm")
        box = draw.textbbox((MARGIN_X + pad, mid_y), left_text, font=main_font, anchor="lm")
        binarize_region(image, (box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2))
    return y + STRIP_H


def _meta_text(analysis):
    """标题带右侧：历史标注在前（空间不足被截断时也保证保留），之后更新时间 · 模型。"""
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


def _fmt_hhmm(value):
    return f"{int(value) // 100:02d}:{int(value) % 100:02d}"


def _draw_chart(image, draw, chart, left, right, top):
    """绘制分时折线面板，返回面板底边 y。

    chart: {"price_text", "sub_text", "points": [(hhmm, price)...], "prev_close"}。
    面板 = 价格行（右上角挂名称·昨收·高低小字）+ 折线区（下方 25% 抖动填充，
    2026-09-23 头部/时间轴压缩后上下扩展到约 53px、曲线 2px）+ 底部时间刻度。
    """
    bottom = top + CHART_HEIGHT
    draw.rectangle((left, top, right, bottom), outline=0, width=1)

    price_font = noto(20, FONT_STRONG)
    axis_font = noto(12, 400)          # 时间轴小字：16→12，给折线区让高度
    corner_font = noto(14, 400)        # 右上角名称·昨收信息：12→16实测截掉高低值，退回14
    draw.text((left + 10, top + 7), chart.get("price_text", ""), font=price_font, fill=0)
    # 名称 · 昨收 · 高低：右上角与价格行同基线。名称段加粗（2026-09-24 用户要求：
    # 智谱AI/人工智能 两个面板名更醒目），昨收/高低维持细字；超宽截细字尾部、名称不截
    sub_text = chart.get("sub_text", "")
    if sub_text:
        price_w = draw.textlength(chart.get("price_text", ""), font=price_font)
        baseline = top + 7 + price_font.getmetrics()[0]
        avail = right - 10 - (left + 10) - price_w - 10
        name = chart.get("name") or ""
        if name and sub_text.startswith(name):
            rest = sub_text[len(name):]
        else:
            name, rest = "", sub_text
        name_font = noto(14, FONT_STRONG)
        name_w = draw.textlength(name, font=name_font) if name else 0
        if rest:
            rest = truncate_text(draw, rest, corner_font, max(avail - name_w, 0))
        rest_w = draw.textlength(rest, font=corner_font) if rest else 0
        if rest:
            draw.text((right - 10, baseline), rest, font=corner_font, fill=0, anchor="rs")
        if name:
            draw.text((right - 10 - rest_w, baseline), name, font=name_font, fill=0, anchor="rs")

    points = [(int(t), float(p)) for t, p in (chart.get("points") or [])]
    if len(points) < 2:
        draw.text(((left + right) // 2, (top + bottom) // 2), "暂无分时数据（先刷新行情）",
                  font=noto(16, 400), fill=0, anchor="mm")
        return bottom

    x0, x1 = left + 10, right - 10
    # 折线区上下扩展：头部只留价格行（+32），底部只留 12px 刻度行（−17）——
    # 高度 18px → 53px，曲线加粗一倍后趋势更醒目
    y0, y1 = top + 32, bottom - 17
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

    if prev_close > 0:  # 昨收虚线基准线
        _, y_pc = xy(0, prev_close)
        dash_x = x0
        while dash_x < x1:
            draw.line((dash_x, y_pc, min(dash_x + 5, x1), y_pc), fill=0, width=1)
            dash_x += 9

    curve = [xy(i, p) for i, (_, p) in enumerate(points)]
    # 曲线下方不再做 25% 点阵填充（2026-09-30 移除）：单像素孤立黑点是四灰温和波形的
    # 最差工况——高频翻转驱动不透，点阵发育不良显成灰点/深浅不均，两块图表面板看起来
    # 就是灰蒙蒙的"残影"脏块（真机定位：全系统仅此处用点阵，页5 特有症状的来源；
    # 点阵是 1-bit 时代设计，全幅波形下才锐利）。只留 2px 曲线+昨收虚线+时间轴
    draw.line(curve, fill=0, width=2, joint="curve")  # 曲线 1→2px：折线区拉高后视觉重心

    label_y = y1 + 2
    draw.text((x0, label_y), _fmt_hhmm(points[0][0]), font=axis_font, fill=0, anchor="la")
    draw.text((x1, label_y), _fmt_hhmm(points[-1][0]), font=axis_font, fill=0, anchor="ra")
    gap_index, gap_size = -1, 0
    for i in range(len(points) - 1):
        delta = points[i + 1][0] - points[i][0]
        if delta > gap_size:
            gap_index, gap_size = i, delta
    if gap_size >= 30:  # 午休（1200→1300）跳档处标时刻
        mid_x = x0 + (x1 - x0) * (gap_index + 1) / (len(points) - 1)
        draw.text((mid_x, label_y), _fmt_hhmm(points[gap_index + 1][0]),
                  font=axis_font, fill=0, anchor="ma")
    return bottom


def _strip_insight_metadata(text):
    """页4正文不再重复主题/领域两个元信息小节，直接从小节正文开始。"""
    metadata_sections = {"【主题名称】", "【所属领域】"}
    content_sections = {"【核心知识】", "【背后的机制】", "【生活里的样子】", "【怎么用起来】"}
    output = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(key in line for key in metadata_sections):
            continue
        marker = next((key for key in content_sections if key in line), None)
        if marker:
            output.append(marker)
            continue
        output.append(line)
    return "\n".join(output)


def _parse_sections(text):
    """【】小节流 → [(header, [para,...])]；首节前的散行并入第一个小节。"""
    sections = []
    pending = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("【") and "】" in s:
            header, _, rest = s.partition("】")
            sections.append((header + "】", [rest.strip()] if rest.strip() else []))
        elif sections:
            sections[-1][1].append(s)
        else:
            pending.append(s)
    if pending and sections:
        sections[0] = (sections[0][0], pending + sections[0][1])
    elif pending:
        sections.append(("", pending))
    return sections


# 页4 阅读顺序（用户指定）：核心知识 → 背后的机制 → 生活里的样子 → 怎么用起来；
# 生成端偶发把主题/领域行重复写进首个小节正文，靠下面的元信息回声过滤剔除
SECTION_ORDER = ("核心知识", "背后的机制", "生活里的样子", "怎么用起来")


def _ordered_sections(sections):
    def rank(item):
        for i, key in enumerate(SECTION_ORDER):
            if key in item[0]:
                return i
        return len(SECTION_ORDER)  # 未命中（新生成的小节名）：稳定排在已知小节之后
    return sorted(sections, key=rank)


def _split_balanced(draw, sections, col_width, size):
    """按小节高度贪心均衡分两栏（页5 用）。"""
    heights = [_section_height(draw, h, ps, col_width, size) for h, ps in sections]
    best_k, best_diff = max(1, len(sections) - 1), None
    for k in range(1, len(sections)):
        diff = abs(sum(heights[:k]) - sum(heights[k:]))
        if best_diff is None or diff < best_diff:
            best_k, best_diff = k, diff
    return sections[:best_k], sections[best_k:]


def _section_height(draw, header, paras, col_width, size):
    line_h, header_h = _line_metrics(size)
    height = 0
    if header:
        height += len(wrap_text(draw, header, serif(size + 2, SERIF_TITLE_WEIGHT),
                                col_width - HEADER_INDENT)) * header_h
        height += HEADER_RULE_GAP
    for p in paras:
        height += len(wrap_text(draw, p, noto(size, BODY_TEXT_WEIGHT), col_width)) * line_h
    return height


def _line_metrics(size):
    """按字体真实度量取行高（字号≠字高，按字号算会把小节下划线压到文字上）。"""
    body = noto(size, BODY_TEXT_WEIGHT)
    head = serif(size + 2, SERIF_TITLE_WEIGHT)
    b_asc, b_desc = body.getmetrics()
    h_asc, h_desc = head.getmetrics()
    return (b_asc + b_desc) + 4, (h_asc + h_desc) + 2  # 正文行距 / 小节标题行距


def _layout_sections(draw, sections, col_width, size):
    """小节列表 → 换行后的绘制块 [(header_lines, body_lines, height)]（真实度量计高）。"""
    h_font = serif(size + 2, SERIF_TITLE_WEIGHT)
    b_font = noto(size, BODY_TEXT_WEIGHT)
    line_h, header_h = _line_metrics(size)
    blocks = []
    for header, paras in sections:
        h_lines = wrap_text(draw, header, h_font, col_width - HEADER_INDENT) if header else []
        b_lines = []
        for p in paras:
            b_lines.extend(wrap_text(draw, p, b_font, col_width))
        height = len(h_lines) * header_h + (HEADER_RULE_GAP if h_lines else 0) + len(b_lines) * line_h
        blocks.append((h_lines, b_lines, height))
    return blocks


def _column_height(blocks, size):
    """一栏的总高（含基础节间距）。"""
    if not blocks:
        return 0
    return sum(b[2] for b in blocks) + SECTION_GAP * (len(blocks) - 1)


def _aligned_starts(blocks_a, blocks_b, top):
    """两栏小节自然起点逐行取较大值 → 跨栏对齐的小节起点（两栏同行小节头齐平，
    版面成行栅格；某栏多出的尾节保持自然排布）。取较大值保证永不重叠。"""
    def natural_starts(blocks):
        starts, y = [], top
        for i, b in enumerate(blocks):
            starts.append(y)
            y += b[2] + (SECTION_GAP if i < len(blocks) - 1 else 0)
        return starts
    sa, sb = natural_starts(blocks_a), natural_starts(blocks_b)
    n = min(len(sa), len(sb))
    return (list(map(max, sa[:n], sb[:n])) + sa[n:],
            list(map(max, sa[:n], sb[:n])) + sb[n:])


def _fit_column(draw, sections, col_width, height, body_sizes):
    """单栏独立取能完整容纳的最大字号（内容少的栏自动放大，减少空白）。"""
    for size in body_sizes:
        blocks = _layout_sections(draw, sections, col_width, size)
        if _column_height(blocks, size) <= height:
            return size, blocks
    size = body_sizes[-1]
    return size, _layout_sections(draw, sections, col_width, size)


def _wrap_units(draw, sections, col_width, size):
    """小节 → [(h_lines, b_lines)]（与 _layout_sections 同度量），供流式分栏按行装填。"""
    h_font = serif(size + 2, SERIF_TITLE_WEIGHT)
    b_font = noto(size, BODY_TEXT_WEIGHT)
    units = []
    for header, paras in sections:
        h_lines = wrap_text(draw, header, h_font, col_width - HEADER_INDENT) if header else []
        b_lines = []
        for p in paras:
            b_lines.extend(wrap_text(draw, p, b_font, col_width))
        units.append((h_lines, b_lines))
    return units


def _flow_fill(units, height, line_h, header_h):
    """把 (h_lines, b_lines) 流按行装进一栏，装不下的整节/剩余行交还下一栏。

    半节切分：小节头+若干正文行留在本栏（至少头+1行，不孤儿头），剩余正文行
    变无头续块回到流首，在下一栏顶部接排。返回 (栏内块, 剩余流)。"""
    blocks, queue = [], list(units)
    space = height
    while queue:
        h_lines, b_lines = queue[0]
        gap = SECTION_GAP if blocks else 0
        header_cost = len(h_lines) * header_h + (HEADER_RULE_GAP if h_lines else 0)
        body_cost = len(b_lines) * line_h
        if gap + header_cost + body_cost <= space:
            blocks.append((h_lines, b_lines, gap + header_cost + body_cost))
            space -= gap + header_cost + body_cost
            queue.pop(0)
            continue
        n_fit = int((space - gap - header_cost) // line_h)
        if n_fit >= 1 and b_lines:  # 至少头+1行（续块至少1行）才在本栏切分
            blocks.append((h_lines, b_lines[:n_fit], gap + header_cost + n_fit * line_h))
            queue[0] = ([], b_lines[n_fit:])
        break  # 本栏已装满（或连头+1行都放不下）：整节/剩余留给下一栏
    return blocks, queue


_JUSTIFY_MAX_SLACK = 30  # 行尾余量超过此值不两端对齐（段落末行保持自然收尾，不硬拉伸）


def _draw_body_line(draw, x, y, piece, size, col_width, justify):
    """正文行绘制；justify=True 时两端对齐——行尾余量摊进词元间隙（中文逐字、英文整词），
    墨迹右缘贴齐栏宽（左栏用：中缝两侧间隔与右栏一致）。余量过大的行（段落末行）不拉伸。"""
    fnt = noto(size, BODY_TEXT_WEIGHT)
    if not justify:
        draw.text((x, y), piece, font=fnt, fill=0)
        return
    tokens = _tokens(piece)
    if len(tokens) < 2:
        draw.text((x, y), piece, font=fnt, fill=0)
        return
    total = sum(draw.textlength(t, font=fnt) for t in tokens)
    slack = col_width - total
    if slack > _JUSTIFY_MAX_SLACK or slack < 0:
        draw.text((x, y), piece, font=fnt, fill=0)
        return
    extra = slack / (len(tokens) - 1)
    cursor = x
    for t in tokens:
        # 绘制位置取整：亚像素坐标会让字形落在像素格中间、抗锯齿边缘发虚
        # （2026-09-30 清晰度修复；间距累计量保持浮点，分布精度不受影响）
        draw.text((round(cursor), y), t, font=fnt, fill=0)
        cursor += draw.textlength(t, font=fnt) + extra


def _draw_column(image, draw, blocks, x, col_width, top, bottom, size, starts=None, line_extra=0.0,
                 justify=False):
    """绘制一栏小节（真实行高），小节自顶部按固定节距排布；无头续块（流式分栏
    半节切分的剩余正文）直接从栏顶接排。starts 可传跨栏行对齐栅格（备用模式）。
    小节标题为思源宋体：绘制后按文字 bbox 层内阈值160（细横画保真，见 fonts.serif）。
    统一节距：所有节缝恒为 SECTION_GAP（两栏/两页一致），剩余空间留在栏底，
    不再做逐栏差异化的齐行拉伸。"""
    n = len(blocks)
    if not n:
        return top
    line_h, header_h = _line_metrics(size)
    body_line_h = line_h + line_extra  # 自适应行距：余量摊进正文行距（小节头不变）
    h_font = serif(size + 2, SERIF_TITLE_WEIGHT)
    # 统一节距：每条缝恒为 SECTION_GAP，两栏完全一致（2026-09-23 用户定稿；
    # 此前的逐栏齐行拉伸按各栏剩余独立均摊，左栏单缝被撑大而右栏双缝不涨，
    # 形成"左栏节距>右栏节距"的可见不对称）。装不下的余量留在栏底。
    gaps = [SECTION_GAP] * (n - 1)
    y = top
    content_bottom = top
    for index, (h_lines, b_lines, height) in enumerate(blocks):
        if starts is not None and index < len(starts):
            y = starts[index]
        if h_lines and y + header_h > bottom:
            # 连小节头首行都放不下：整节放弃，只给截断说明
            draw.text((x, min(y, bottom - size)), "……（内容过长，已截断）",
                      font=noto(size, 400), fill=0)
            y = bottom
            content_bottom = max(content_bottom, y)
        else:
            if h_lines:
                block_bottom = y + len(h_lines) * header_h
                draw.rectangle((x, y + 2, x + 3, block_bottom - 6), fill=0)
                for piece in h_lines:
                    draw.text((x + HEADER_INDENT, y), piece, font=h_font, fill=0)
                    box = draw.textbbox((x + HEADER_INDENT, y), piece, font=h_font)
                    binarize_region(image, (box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2))
                    y += header_h
                # 小节下划线在标题文字下方留 3px 净空，不再压字
                draw.line((x, y + 3, x + col_width, y + 3), fill=0, width=1)
                y += HEADER_RULE_GAP
            drawn = 0
            for piece in b_lines:
                if y + size > bottom:
                    break
                _draw_body_line(draw, x, y, piece, size, col_width, justify)
                y += body_line_h
                drawn += 1
            if drawn < len(b_lines) and y + size <= bottom:  # 正文有剩余且有空间：标出截断
                draw.text((x, y), "……（内容过长，已截断）",
                          font=noto(size, 400), fill=0)
                y = bottom
            content_bottom = max(content_bottom, y)
        if index < n - 1:
            y += gaps[index]
    return content_bottom


# 双栏几何：左右各距外框/中缝 14px 对称（文字不贴竖线、不贴边框）
BODY_PAD = 14
MID_X = 400
# 左栏正文两端对齐（2026-09-23 用户定稿）：左栏右缘参差（ragged），墨迹距中缝中位
# 33px，而右栏墨迹左缘距中缝仅 16px——起收窄/右移都改变不了参差缘的分布，只有
# 两端对齐能让左栏墨迹右缘贴齐 386，使中缝两侧间隔一致（≈14px，实测对齐）
# 自适应行距上限（px/行）：两栏共用同一增量（取较满栏的可摊值），内容贴满时增量为 0
LINE_EXTRA_MAX = 3.0


def _render_body(image, draw, sections, top, split_mode, body_sizes):
    """双栏正文：flow=页4/页5 报纸式流式分栏（按阅读顺序装满左栏，装不下的半节在
    右栏顶部接排、后续小节顺延——内容长短自适应，不再整节截断）；
    balanced=备用模式（两栏独立装填+跨栏行对齐，当前无调用方）。"""
    # 文本区下限：末行行槽底距底部框线 12px（434+25=459，2026-09-23 用户要求再深一行），
    # 页4/页5 共用；内容没写满时靠下方齐行把节缝拉开，末行贴近下限
    bottom = EPD_HEIGHT - 13  # 框内净空 12px 不变（框底 479，正文下限 467）
    left_x = MARGIN_X + BODY_PAD
    right_x = MID_X + BODY_PAD
    col_width = MID_X - left_x - BODY_PAD  # 左右栏等宽，两侧各留 14px（外框侧=中缝侧对称）
    budget = bottom - top
    if split_mode == "flow":
        for size in body_sizes:
            line_h, header_h = _line_metrics(size)
            units = _wrap_units(draw, sections, col_width, size)
            left_blocks, rest = _flow_fill(units, budget, line_h, header_h)
            right_blocks, leftover = _flow_fill(rest, budget, line_h, header_h)
            if not leftover:
                break  # 两栏完整装下：用当前字号
        # 最小字号仍装不下：尾部并入右栏（_flow_fill 的剩余流是2元组，补齐3元组高度），
        # 绘制层按行截断兜底——不补齐会在此崩溃（行距/字号调整使内容溢出时暴露）
        right_blocks += [(h, b, len(b) * line_h) for h, b in leftover]
        # 纵向余量用进行距（2026-09-23 用户要求）：两栏共用同一增量——取较满栏的可摊
        # 值（各自摊会重现左右行距不齐），上限 3px；内容贴满时增量 0，永不放大行距致截断
        def _affordable(blocks):
            lines = sum(len(b) for _h, b, _c in blocks)
            if not lines:
                return 0.0
            return max(0.0, (budget - sum(b[2] for b in blocks)) / lines)
        line_extra = min(_affordable(left_blocks), _affordable(right_blocks), LINE_EXTRA_MAX)
        left_end = _draw_column(image, draw, left_blocks, left_x, col_width, top, bottom, size,
                                line_extra=line_extra, justify=True)
        right_end = _draw_column(image, draw, right_blocks, right_x, col_width, top, bottom, size,
                                 line_extra=line_extra)
        draw.line((MID_X, top, MID_X, bottom), fill=0, width=1)
        return left_end, right_end
    left_secs, right_secs = _split_balanced(draw, sections, col_width, body_sizes[0])
    left_size, left_blocks = _fit_column(draw, left_secs, col_width, budget, body_sizes)
    # 页5：两栏统一字号，取双栏都能完整放下的最大字号
    unified = None
    for size in body_sizes:
        trial_left = _layout_sections(draw, left_secs, col_width, size)
        trial_right = _layout_sections(draw, right_secs, col_width, size)
        if (_column_height(trial_left, size) <= budget
                and _column_height(trial_right, size) <= budget):
            unified = (size, trial_left, trial_right)
            break
    if unified is None:
        size = body_sizes[-1]
        unified = (size, _layout_sections(draw, left_secs, col_width, size),
                   _layout_sections(draw, right_secs, col_width, size))
    left_size, left_blocks, right_blocks = unified
    # 跨栏行对齐：两栏同行小节头齐平（如左【消息面归因】与右【政策与国际环境】）
    left_starts, right_starts = _aligned_starts(left_blocks, right_blocks, top)
    left_end = _draw_column(image, draw, left_blocks, left_x, col_width, top, bottom, left_size,
                            left_starts)
    right_end = _draw_column(image, draw, right_blocks, right_x, col_width, top, bottom, left_size,
                             right_starts)
    divider_bottom = max(left_end, right_end)
    draw.line((MID_X, top, MID_X, min(bottom, divider_bottom)), fill=0, width=1)
    return left_end, right_end


def render_page4(analysis):
    """页4：认知洞察。黑标题带（bulb 图标）+ 主题行 + 固定分栏双栏正文（18/550）。"""
    a = analysis or {}
    topic = (a.get("topic") or "待生成").strip().strip("【】")
    domain = a.get("domain") or "轮换生成"
    text = _strip_insight_metadata(a.get("text", "")) if a.get("kind") == "insight" else ""

    image = Image.new("L", (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    frame(draw)
    draw.rectangle(CONTENT_BOX, outline=0, width=1)

    y = _band_head(draw, "认知洞察", _meta_text(a), "bulb")
    y = _topic_line(image, draw, y, f"主题：{topic}" if topic else "", domain)
    body_top = y + 6  # 主题行→正文间隙 10→6：纵向余量改投行距（2026-09-23）

    sections = _parse_sections(text)
    # 主题已展示在标题行：与主题同名的整节不再排版——比较前两侧都剥引号，
    # 防取数端单侧剥引号（如“xx”只剩开头引号）导致同名节漏网、末尾多出一块；
    # 【机制图示】小节整体移除（用户判定信息量低），让出空间给正文字号
    _q = "“”\"'"
    sections = [(h, ps) for h, ps in sections
                if "机制图示" not in h
                and h.strip("【】" + _q) != topic.strip(_q)]
    if not sections:
        draw.text((EPD_WIDTH / 2, (body_top + EPD_HEIGHT - 26) / 2), "— 暂无分析报告 —",
                  font=noto(16, 400), fill=0, anchor="mm")
        return image
    # 偶发回声：模型把主题名/领域整行重复写进小节正文（尤其首个小节），逐行剔除
    meta_echo = {t for t in (topic, domain) if t}
    sections = [(h, [p for p in ps if p not in meta_echo]) for h, ps in sections]
    sections = _ordered_sections(sections)
    # 首行缩进：每节正文首段前置两个全角空格（U+3000 会作为词元保留在行首，
    # 换行/流式分栏/计高共用同一 wrap_text，度量自动一致）
    sections = [(h, (["　　" + ps[0]] + ps[1:]) if ps else ps) for h, ps in sections]
    _left_end, _right_end = _render_body(image, draw, sections, body_top, "flow", INSIGHT_BODY_SIZES)
    return image


def render_report_page(title, meta_text, text, empty_notes,
                       charts=None, body_sizes=None):
    """页5：智谱AI 走势归因。黑标题带 + 分时图（一行两列：个股/指数对比）+ 双栏黑体正文。"""
    body_sizes = body_sizes or (14,)
    image = Image.new("L", (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    frame(draw)
    draw.rectangle(CONTENT_BOX, outline=0, width=1)

    y = _band_head(draw, title, meta_text, "chart-candle")
    charts = [c for c in (charts or []) if c]
    if charts:
        # 图表左右各内缩 8px：与内容框线（x=0/799）留缝，保持两个独立小框
        # ——此前外边缘与框线重合会视觉融合成一根粗线
        panels = ([(MARGIN_X + 8, MID_X - 6), (MID_X + 6, CONTENT_BOX[2] - 8)]
                  if len(charts) >= 2 else [(MARGIN_X + 8, CONTENT_BOX[2] - 8)])
        chart_top = y + 8  # 一行两列：所有面板同一顶部，等高并列
        for chart, (chart_l, chart_r) in zip(charts, panels):
            _draw_chart(image, draw, chart, chart_l, chart_r, chart_top)
        y = chart_top + CHART_HEIGHT

    body_top = y + 6  # 图表→正文间隙 10→6：310字配额贴版面极限，能省则省
    sections = _parse_sections(text)
    if not sections:
        note = empty_notes[0] if empty_notes else "暂无分析报告"
        draw.text((EPD_WIDTH / 2, (body_top + EPD_HEIGHT - 26) / 2), f"— {note} —",
                  font=noto(16, 400), fill=0, anchor="mm")
        return image
    # 首行缩进：与页4同步（见 render_page4 同款注释）
    sections = [(h, (["　　" + ps[0]] + ps[1:]) if ps else ps) for h, ps in sections]
    # 2026-09-23 与页4同步：流式分栏（先填满左栏、余文右栏接排，按内容自适应）
    _render_body(image, draw, sections, body_top, "flow", body_sizes)
    return image
