"""页1（今日看板）：日期天气面板、Agent Plan + GLM 双栏额度面板、工作计划面板。"""
from epd_dashboard.calendar_cn import lunar_extra
from epd_dashboard.config import PANEL_HEIGHT, PANEL_WIDTH, PANEL_X, PANEL_Y, WIDTH, HEIGHT
from epd_dashboard.fonts import FONT_REGULAR, FONT_STRONG, SIZE_L, SIZE_M, SIZE_S, SIZE_XS, font
from epd_dashboard.placeholders import placeholder_glm
from epd_dashboard.renderers.common import draw_panel
from PIL import Image, ImageDraw


def render_weather(draw, panel_y, weather, now):
    # 日期 · 天气：与Agent Plan保持统一布局逻辑
    draw_panel(draw, panel_y, "日期 · 天气", "北京", right_size=SIZE_S, title_weight=700)
    p0 = panel_y

    # 统一布局区域（与Agent Plan保持一致）
    top_rule = p0 + 55  # 标题下划线位置
    bottom_rule = p0 + PANEL_HEIGHT - 60  # 底部详细信息区上划线位置

    # 主要信息区域：保持原有位置，但基于top_rule
    draw.text((PANEL_X + 18, top_rule + 1), now.strftime("%m/%d"), font=font(52), fill=0)
    weekday = f"星期{'一二三四五六日'[now.weekday()]}"
    lunar_str, extra_str = lunar_extra(now)
    line2 = f"{lunar_str} · {weekday}" if lunar_str else weekday
    draw.text((PANEL_X + 18, top_rule + 71), line2, font=font(26), fill=0)
    temperature = f'{weather["temperature"]:.1f}°C'
    draw.text((PANEL_X + PANEL_WIDTH - 18, top_rule + 23), temperature, font=font(SIZE_L, FONT_STRONG), fill=0, anchor="ra")
    weather_line = f'{weather["description"]} {weather["high"]:.0f}/{weather["low"]:.0f}°C'
    draw.text((PANEL_X + PANEL_WIDTH - 18, top_rule + 77), weather_line, font=font(SIZE_S), fill=0, anchor="ra")
    if extra_str:
        draw.text((PANEL_X + 18, top_rule + 111), extra_str, font=font(SIZE_S), fill=0)
    alert = weather.get("alert")
    if alert:
        alert_text = f'{alert["type"]}{alert["level"]}预警'
        text_width = int(draw.textlength(alert_text, font=font(SIZE_S)))
        icon_x = PANEL_X + PANEL_WIDTH - 18 - text_width - 33
        icon_y = top_rule + 111
        draw.polygon(
            ((icon_x + 12, icon_y), (icon_x + 24, icon_y + 21), (icon_x, icon_y + 21)),
            outline=0,
            width=3,
        )
        draw.line((icon_x + 12, icon_y + 6, icon_x + 12, icon_y + 13), fill=0, width=3)
        draw.ellipse((icon_x + 10, icon_y + 16, icon_x + 14, icon_y + 20), fill=0)
        draw.text(
            (PANEL_X + PANEL_WIDTH - 18, icon_y + 2),
            alert_text,
            font=font(SIZE_S, FONT_STRONG),
            fill=0,
            anchor="ra",
        )

    # 底部详细信息区（与Agent Plan保持一致）
    reset_y = bottom_rule
    draw.line((PANEL_X + 16, reset_y, PANEL_X + PANEL_WIDTH - 16, reset_y), fill=0, width=2)

    metrics = [
        (f'{weather["humidity"]:.0f}%', "湿度"),
        (f'{weather.get("uv_index", 0):.1f}', "紫外线"),
        (f'{weather["precipitation"]:.0f}%', "降水概率"),
    ]
    metric_w = (PANEL_WIDTH - 32) / 3
    for index, (value, label) in enumerate(metrics):
        x = PANEL_X + 16 + int(index * metric_w)
        center = x + metric_w / 2
        draw.text((center, reset_y + 6), value, font=font(SIZE_M, FONT_STRONG), fill=0, anchor="ma")
        draw.text((center, reset_y + 27), label, font=font(SIZE_S), fill=0, anchor="ma")
        if index:
            draw.line((x, reset_y + 6, x, p0 + PANEL_HEIGHT - 13), fill=0, width=2)


def _quota_half(draw, x0, x1, panel_y, subtitle, sub_right, items):
    """半区小栏：栏标题+下划线，下方若干“标签/剩余% + 进度条”行按行数自适应分布。"""
    header_font = font(SIZE_M, FONT_STRONG)
    draw.text((x0, panel_y + 16), subtitle, font=header_font, fill=0)
    if sub_right:
        tag_font = font(SIZE_XS)
        header_w = draw.textlength(subtitle, font=header_font)
        tag_w = draw.textlength(sub_right, font=tag_font)
        if header_w + tag_w + 10 <= x1 - x0:  # 放不下就舍弃档位标签，避免与栏标题重叠
            draw.text((x1, panel_y + 25), sub_right, font=tag_font, fill=0, anchor="ra")
    rule_y = panel_y + 48
    draw.line((x0, rule_y, x1, rule_y), fill=0, width=2)
    rows_top = panel_y + 58
    rows_bottom = panel_y + PANEL_HEIGHT - 68  # 重置区上划线（-60）再留 8px 间距
    n = len(items)
    group_h = (rows_bottom - rows_top) / n
    bar_h = 12 if n <= 2 else 11
    offset = 4 if n <= 2 else 2
    for index, (title, quota) in enumerate(items):
        group_top = rows_top + index * group_h
        draw.text((x0, group_top + offset), title, font=font(SIZE_S, FONT_STRONG), fill=0)
        draw.text((x1, group_top + offset), f'{quota["percent"]}%', font=font(SIZE_M, FONT_STRONG), fill=0, anchor="ra")
        bar_y = int(group_top + offset + 24)
        draw.rectangle((x0, bar_y, x1, bar_y + bar_h), outline=0, width=2)
        fill_w = int((x1 - x0) * quota["percent"] / 100)
        draw.rectangle((x0 + 2, bar_y + 2, x0 + 2 + max(0, fill_w - 4), bar_y + bar_h - 2), fill=0)


def _reset_strip(draw, x0, x1, reset_y, panel_bottom, items):
    """底部重置时间条：等分列，label 上、时间下。"""
    n = len(items)
    col_w = (x1 - x0) / n
    for index, (label, value) in enumerate(items):
        x = x0 + index * col_w
        center = x + col_w / 2
        draw.text((center, reset_y + 6), label, font=font(SIZE_S), fill=0, anchor="ma")
        draw.text((center, reset_y + 27), value, font=font(SIZE_S), fill=0, anchor="ma")
        if index:
            draw.line((x, reset_y + 6, x, panel_bottom), fill=0, width=2)


def render_agentplan(draw, panel_y, quotas, glm):
    # Plan 额度：取消总标题行，整块左右一分为二，左=火山方舟 Agent Plan（5h/周/月），右=GLM Coding Plan（5h/每周，无月额度）
    if not (glm and glm.get("quotas")):
        glm = placeholder_glm()
    p1 = panel_y
    draw.rectangle((PANEL_X, p1, PANEL_X + PANEL_WIDTH, p1 + PANEL_HEIGHT), outline=0, width=3)
    mid_x = PANEL_X + PANEL_WIDTH // 2
    left_x, left_end = PANEL_X + 16, mid_x - 12
    right_x, right_end = mid_x + 12, PANEL_X + PANEL_WIDTH - 16
    reset_y = p1 + PANEL_HEIGHT - 60  # 重置区上划线
    panel_bottom = p1 + PANEL_HEIGHT - 13
    draw.line((mid_x, p1 + 3, mid_x, p1 + PANEL_HEIGHT - 3), fill=0, width=2)

    glm_level = glm.get("level") or ""
    _quota_half(draw, left_x, left_end, p1, "火山方舟 Agent Plan", "", list(quotas.items()))
    _quota_half(
        draw, right_x, right_end, p1,
        "GLM Coding Plan", f"{glm_level}档" if glm_level else "", list(glm["quotas"].items()),
    )

    draw.line((PANEL_X + 16, reset_y, PANEL_X + PANEL_WIDTH - 16, reset_y), fill=0, width=2)
    reset_labels = {"5小时": "5h重置", "周额度": "周重置", "月额度": "月重置"}
    left_resets = [
        (reset_labels.get(title, f"{title[:2]}重置"), quota["reset"]) for title, quota in quotas.items()
    ]
    right_resets = [
        (reset_labels.get(title, f"{title[:2]}重置"), quota["reset"]) for title, quota in glm["quotas"].items()
    ]
    _reset_strip(draw, left_x, left_end, reset_y, panel_bottom, left_resets)
    _reset_strip(draw, right_x, right_end, reset_y, panel_bottom, right_resets)


def render_plans(draw, panel_y, plans, now):
    # 工作计划：内容区按条数均匀分格，分割线在各格边界（均匀分布），文字在格内垂直居中
    draw_panel(draw, panel_y, "工作计划", now.strftime("%Y-%m-%d"), right_size=SIZE_S, title_weight=700)
    p2 = panel_y
    visible_plans = plans[:5]
    header_line_y = p2 + 17 + 38
    top_limit = header_line_y + 10
    bottom_limit = p2 + PANEL_HEIGHT - 20
    if len(plans) > 5:
        bottom_limit = p2 + PANEL_HEIGHT - 44  # 给“还有 N 项”留位
    available_h = bottom_limit - top_limit
    n = len(visible_plans)
    text_h = SIZE_S
    cell_h = available_h / n
    for index, plan in enumerate(visible_plans, 1):
        cell_top = top_limit + (index - 1) * cell_h
        task_y = int(cell_top + max(0, (cell_h - text_h) / 2))
        draw.text((PANEL_X + 18, task_y), f"{index:02d}", font=font(17), fill=0)
        draw.text((PANEL_X + 61, task_y), plan, font=font(17), fill=0)
        if index < n:
            line_y = int(top_limit + index * cell_h)
            draw.line((PANEL_X + 18, line_y, PANEL_X + PANEL_WIDTH - 18, line_y), fill=0, width=2)
    if len(plans) > 5:
        draw.text((PANEL_X + 18, p2 + PANEL_HEIGHT - 30), f"还有 {len(plans) - 5} 项", font=font(SIZE_S), fill=0)


def render_dashboard(weather, plans, quotas, glm, now):
    image = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=0, width=2)
    # 三个模块组件化布局，区域由 PANEL_Y 统一决定
    render_weather(draw, PANEL_Y[0], weather, now)
    render_agentplan(draw, PANEL_Y[1], quotas, glm)
    render_plans(draw, PANEL_Y[2], plans, now)
    return image
