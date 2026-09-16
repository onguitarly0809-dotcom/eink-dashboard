"""页1（今日看板）：日期天气面板、GLM Coding Plan 圆环额度面板、工作计划面板。"""

from epd_dashboard.calendar_cn import lunar_extra
from epd_dashboard.config import PANEL_HEIGHT, PANEL_WIDTH, PANEL_X, PANEL_Y, WIDTH, HEIGHT
from epd_dashboard.fonts import FONT_REGULAR, FONT_STRONG, SIZE_L, SIZE_M, SIZE_S, font
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


def _quota_bar(draw, x0, x1, y, percent, segments=20, height=13, gap=3):
    """分段电量条：黑色外框包住20格区域，框线与色块之间四周留2px空白，
    色块完整可见、不与边框粘连。点亮格数=剩余比例，未点亮的空格留在框内，
    93%时一眼能看出与满格的差距。"""
    inner_x0, inner_x1 = x0 + 4, x1 - 4  # 左右框线2px+空白2px
    pitch = (inner_x1 - inner_x0) / segments
    seg_w = pitch - gap
    lit = round(max(0, min(100, percent)) / 100 * segments)
    for index in range(lit):
        sx0 = inner_x0 + index * pitch
        draw.rectangle((sx0, y, sx0 + seg_w, y + height), fill=0)
    draw.rectangle((x0, y - 4, x1, y + height + 4), outline=0, width=2)


def render_agentplan(draw, panel_y, quotas, glm):
    # Plan 额度：火山方舟已退订不再显示，GLM Coding Plan 单独成板。每个窗口一行：
    # 窗口名+同字号剩余%（20px，刻意低于日期52px/温度32px，页面视觉重心仍归日期）
    # + 带外框的分段电量条 + 重置时间。quotas 参数保留只是兼容调用链。
    if not (glm and glm.get("quotas")):
        glm = placeholder_glm()
    p1 = panel_y
    glm_level = glm.get("level") or ""
    draw_panel(draw, p1, "GLM Coding Plan", f"{glm_level}档" if glm_level else "",
               right_size=SIZE_S, title_weight=700)

    items = list(glm["quotas"].items())
    titles = {"5小时": "5小时额度", "周额度": "每周额度"}
    n = max(1, len(items))
    content_top = p1 + 66
    content_bottom = p1 + PANEL_HEIGHT - 18
    row_h = (content_bottom - content_top) / n
    right_x = PANEL_X + PANEL_WIDTH - 16
    for index, (title, quota) in enumerate(items):
        row_cy = content_top + row_h * (index + 0.5)
        if index:
            draw.line((PANEL_X + 16, row_cy - row_h / 2, PANEL_X + PANEL_WIDTH - 16, row_cy - row_h / 2),
                      fill=0, width=2)
        draw.text((PANEL_X + 16, row_cy - 16), titles.get(title, title),
                  font=font(20), fill=0, anchor="ls")
        draw.text((right_x, row_cy - 16), f'{quota["percent"]}%',
                  font=font(20), fill=0, anchor="rs")
        _quota_bar(draw, PANEL_X + 16, right_x, row_cy - 4, quota["percent"])
        reset = quota["reset"]
        reset_text = reset if any(word in reset for word in ("失败", "权限")) else f"重置 {reset}"
        draw.text((PANEL_X + 16, row_cy + 21), reset_text, font=font(SIZE_S), fill=0, anchor="la")


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
