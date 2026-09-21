"""页1（今日看板，横版 V4）田字格：天气｜月历｜工作计划｜GLM 额度。

布局：黄金分割列宽（左列 天气+计划 长边，右列 月历+GLM 短边），四象限面积对等。
规则集（页2/3 同款）：8px 紧边距 + 1px 外框、黑标题带（白字黑体 20px、带高44、图标20px）、
1px 线纪律、阅读层思源黑体、辅助小字 16px、正文主体 18/550。
图标：Tabler Icons 线稿字体（MIT），用 PIL 当字体直接渲染，粗细均匀风格统一；
天气码 → 图标映射见 _weather_glyph_name（多云 = 太阳+云 双字形叠画）。
月历法定节假日/调休数据表见 config.HOLIDAY_PLAN。
洗车指数由未来 3 天降水概率/天气码本地推导（fetchers/weather._car_wash_index）。
"""
import calendar
import re
from datetime import timedelta

from PIL import Image, ImageDraw

from epd_dashboard.calendar_cn import lunar_extra
from epd_dashboard.config import EPD_HEIGHT, EPD_WIDTH, HOLIDAY_PLAN
from epd_dashboard.fetchers.weather import describe
from epd_dashboard.fonts import FONT_STRONG, noto
from epd_dashboard.placeholders import placeholder_glm
from epd_dashboard.renderers.common import (
    draw_tabler,
    draw_weather_icon,
    frame,
    truncate_text,
)

WEEKDAY = "一二三四五六日"
BAND_H = 44

# 田字格几何：列宽按黄金分割（长边=左列 天气+计划，短边=右列 月历+GLM）。
# 上下边距与横向外框间距统一（~8px）：上排顶边 9、下排底边 471
MARGIN = 8
GAP = 6
LONG_W = round((EPD_WIDTH - 2 * MARGIN - GAP) * 0.618)  # 480：黄金分割长边
TOP_Y0, TOP_Y1 = 9, 237
BOT_Y0, BOT_Y1 = 243, 471
QUADS = {
    "weather": (MARGIN, TOP_Y0, MARGIN + LONG_W, TOP_Y1),
    "calendar": (MARGIN + LONG_W + GAP, TOP_Y0, EPD_WIDTH - MARGIN - 1, TOP_Y1),
    "plans": (MARGIN, BOT_Y0, MARGIN + LONG_W, BOT_Y1),
    "glm": (MARGIN + LONG_W + GAP, BOT_Y0, EPD_WIDTH - MARGIN - 1, BOT_Y1),
}

# ---------- Tabler Icons 线稿图标字体（MIT）：全局助手已移至 common ----------


def _wind_dir_name(degree):
    """风向角度 → 8 方位中文。"""
    dirs = ("北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风")
    try:
        return dirs[int(((float(degree) % 360) + 22.5) // 45) % 8]
    except (TypeError, ValueError):
        return "风"


def _beaufort(speed_kmh):
    """风速 km/h → 蒲福风级中文名（阈值按 m/s 标准折算：km/h ÷ 3.6）。"""
    try:
        speed = float(speed_kmh) / 3.6
    except (TypeError, ValueError):
        return "--"
    for th, name in ((0.3, "无风"), (1.6, "软风"), (3.4, "轻风"), (5.5, "微风"), (8.0, "和风"),
                     (10.8, "清风"), (13.9, "强风"), (17.2, "疾风"), (20.8, "大风"), (24.5, "烈风"),
                     (28.5, "狂风"), (32.7, "暴风")):
        if speed < th:
            return name
    return "飓风"


def _quad_head(draw, box, title, right_text="", icon=None):
    """象限头：黑标题带（34px，可带 18px 白色 Tabler 图标），右侧小字 16px。返回内容区顶 y。"""
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=0, width=1)
    draw.rectangle((x0, y0, x1, y0 + BAND_H), fill=0)
    text_x = x0 + 14
    if icon:
        draw_tabler(draw, x0 + 21, y0 + BAND_H // 2, 20, icon, fill=255)
        text_x = x0 + 44
    draw.text((text_x, y0 + BAND_H // 2), title, font=noto(20, FONT_STRONG), fill=255, anchor="lm")
    if right_text:
        draw.text((x1 - 12, y0 + BAND_H // 2), right_text, font=noto(16, 500), fill=255, anchor="rm")
    return y0 + BAND_H


def _weather_quad(image, draw, box, weather, now):
    """天气象限：左区大温度（含小数）水平居中 + 四指标列（Tabler 图标+标签+数值，
    等间隙分布，左右边界对称收窄）；右区纯白 3 日预报面板（星期/图标/高低温/天况/降水
    五行均分，列间竖分隔）。"""
    x0, y0, x1, y1 = box
    alert = weather.get("alert")
    right_text = (f'{alert["type"]}{alert["level"]}预警' if alert
                  else f'更新 {weather.get("updated", now.strftime("%H:%M"))}')
    top = _quad_head(draw, box, f'天气 · {weather.get("city", "北京")}', right_text, icon="temperature")

    split_x = x0 + 232
    left_cx = (x0 + split_x) / 2
    slot_h = (y1 - top) / 5

    # 左：大温度（含小数，℃ 与数字同字号），中心对齐预报面板星期名行
    temp_text = f'{weather.get("temperature", 0.0):.1f}'
    temp_font = noto(44, FONT_STRONG)
    deg_font = noto(44, FONT_STRONG)
    row1_cy = top + slot_h * 1.0
    temp_w = draw.textlength(temp_text, font=temp_font)
    deg_w = draw.textlength("°C", font=deg_font)
    start_x = left_cx - (temp_w + 8 + deg_w) / 2
    draw.text((start_x, row1_cy), temp_text, font=temp_font, fill=0, anchor="lm")
    draw.text((start_x + temp_w + 8, row1_cy), "°C", font=deg_font, fill=0, anchor="lm")

    # 左：四指标列（图标 + 标签 + 数值），三行分别对齐预报面板的高低温/天况/降水行
    metrics = [
        ("car", "洗车", weather.get("car_wash", "--")),
        ("wind", _wind_dir_name(weather.get("wind_degree", 0)), _beaufort(weather.get("wind", 0))),
        ("droplet", "湿度", f'{weather.get("humidity", 0):.0f}%'),
        ("sun-high", "紫外线", f'{weather.get("uv_index", 0):.1f}'),
    ]
    m_x0, m_x1 = x0 + 16.5, split_x - 16.5
    label_font = noto(16, 500)
    value_font = noto(16, FONT_STRONG)
    icon_y = top + slot_h * 2.5
    label_y = top + slot_h * 3.5
    value_y = top + slot_h * 4.5
    widths = [max(draw.textlength(label, font=label_font),
                  draw.textlength(value, font=value_font), 24)
              for _, label, value in metrics]
    gap = (m_x1 - m_x0 - sum(widths)) / (len(metrics) - 1)
    cursor = m_x0
    for (icon_name, label, value), col_w in zip(metrics, widths):
        cx = cursor + col_w / 2
        draw_tabler(draw, cx, icon_y, 22, icon_name)
        draw.text((cx, label_y), label, font=label_font, fill=0, anchor="mm")
        draw.text((cx, value_y), value, font=value_font, fill=0, anchor="mm")
        cursor += col_w + gap

    # 右：3 日预报面板（纯白底，列间竖分隔，五行均分：星期名/图标/高低温/天况/降水）
    panel_x0 = split_x + 6
    draw.line((split_x, top, split_x, y1), fill=0, width=1)
    days = (weather.get("days") or [])[:3]
    col_w = (x1 - panel_x0) / 3
    if not days:
        draw.text(((panel_x0 + x1) / 2, (top + y1) / 2), "— 预报待刷新 —",
                  font=noto(16, 400), fill=0, anchor="mm")
    else:
        for index, day in enumerate(days):
            cx = panel_x0 + col_w * (index + 0.5)
            centers = [top + slot_h * (i + 0.5) for i in range(5)]
            # 首列"今天"，其余列显示具体日期（跨周时星期几无对照意义）
            if index == 0:
                label = day["label"]
            else:
                d = (now + timedelta(days=index)).date()
                label = f"{d.month}/{d.day}"
            draw.text((cx, centers[0]), label, font=noto(16, FONT_STRONG), fill=0, anchor="mm")
            draw_weather_icon(draw, cx, centers[1], 30, day.get("code", 3))
            draw.text((cx, centers[2]), f'{day["high"]:.0f}°/{day["low"]:.0f}°',
                      font=noto(16, FONT_STRONG), fill=0, anchor="mm")
            draw.text((cx, centers[3]), describe(day.get("code", 3)), font=noto(16, 500), fill=0, anchor="mm")
            draw.text((cx, centers[4]), f'降水 {day.get("pop", 0):.0f}%',
                      font=noto(16, 500), fill=0, anchor="mm")
    for index in range(1, 3):
        vx = panel_x0 + col_w * index
        draw.line((vx, top + 2, vx, y1 - 2), fill=0, width=1)


def _calendar_quad(draw, box, now):
    x0, y0, x1, y1 = box
    # 标题压缩为无空格"YYYY年M月"（20px 下与右侧"今日 N 日"同带共存；日历语义由图标承担）
    top = _quad_head(draw, box, f"{now.year}年{now.month}月", f"今日 {now.day} 日", icon="calendar")
    # 星期表头（周一起）；网格铺满至图例行上方，行高随周数自适应（上下均匀）
    header_font = noto(16, FONT_STRONG)
    day_font = noto(16, 500)
    today_font = noto(16, FONT_STRONG)
    grid_x0, grid_x1 = x0 + 14, x1 - 14
    col_w = (grid_x1 - grid_x0) / 7
    header_y = top + 8
    for i, name in enumerate(WEEKDAY):
        draw.text((grid_x0 + col_w * (i + 0.5), header_y + 9), name, font=header_font, fill=0, anchor="mm")
    grid_top = header_y + 26
    weeks = calendar.monthcalendar(now.year, now.month)
    grid_bottom = y1 - 32   # 底部给图例行留位（图例不再贴边框）
    row_h = (grid_bottom - grid_top) / len(weeks)
    for r, week in enumerate(weeks):
        for c, day in enumerate(week):
            if not day:
                continue
            cx = grid_x0 + col_w * (c + 0.5)
            cy = grid_top + row_h * (r + 0.5)
            mark = HOLIDAY_PLAN.get((now.month, day))
            if day == now.day:
                # 今日：黑底反白数字（锚点与其他日期一致 cy-2，保证上下对齐）
                draw.rectangle((cx - 15, cy - 14, cx + 15, cy + 10), fill=0)
                draw.text((cx, cy - 2), f"{day}", font=today_font, fill=255, anchor="mm")
            else:
                draw.text((cx, cy - 2), f"{day}", font=day_font, fill=0, anchor="mm")
            if mark == "休":
                draw.rectangle((cx - 4, cy + 9, cx + 4, cy + 12), fill=0)     # 实心方块（上移2px避免贴下一行）
            elif mark == "班":
                draw.rectangle((cx - 4, cy + 9, cx + 4, cy + 12), outline=0, width=1)  # 空心方块
    # 底部图例行（与底边框保持间距，不贴线）；字号字重与天气指标行（洗车等）一致
    draw.text(((x0 + x1) / 2, y1 - 17), "■ 节假日　□ 调休上班",
              font=noto(16, 500), fill=0, anchor="mm")


def _plans_quad(draw, box, plans):
    x0, y0, x1, y1 = box
    plans = plans or []
    top = _quad_head(draw, box, "工作计划", f"共 {len(plans)} 项", icon="clipboard")
    if not plans:
        draw.text(((x0 + x1) / 2, (top + y1) / 2), "— 暂无计划 —",
                  font=noto(16, 400), fill=0, anchor="mm")
        return
    visible = plans[:3]
    foot_reserve = y1 - 14 if len(plans) > 3 else y1 - 8
    slot_h = (foot_reserve - top) / len(visible)
    for gap_index in range(1, len(visible)):
        divider_y = top + gap_index * slot_h
        draw.line((x0 + 12, divider_y, x1 - 12, divider_y), fill=0, width=1)
    for index, plan in enumerate(visible):
        slot_top = top + index * slot_h
        first_y = slot_top + (slot_h - 24) / 2
        cursor = x0 + 14
        match = re.match(r"^\[([^\[\]]{1,6})\]\s*", plan)
        title = plan
        if match:
            # 优先级标签与正文同字号（18px 加粗），序号已按用户要求删除
            title = plan[match.end():]
            draw.text((cursor, first_y), match.group(1), font=noto(18, FONT_STRONG), fill=0)
            cursor += draw.textlength(match.group(1), font=noto(18, FONT_STRONG)) + 12
        draw.text((cursor, first_y), truncate_text(draw, title, noto(18, 550), x1 - 12 - cursor),
                  font=noto(18, 550), fill=0)
    if len(plans) > 3:
        draw.text(((x0 + x1) / 2, y1 - 13), f"— 还有 {len(plans) - 3} 项 —",
                  font=noto(16, 400), fill=0, anchor="mm")


def _quota_bar(draw, x0, x1, y, percent, segments=20, height=24):
    """电量条：完全按纵向排版样式——一圈黑框，框距色块 4px 留白，空槽纯白，
    黑色实心色块、块间 2px 白隙。高度 24px。"""
    draw.rectangle((x0, y, x1, y + height), outline=0, width=1)
    inner_x0, inner_x1 = x0 + 4, x1 - 4
    inner_y0, inner_y1 = y + 4, y + height - 4
    pitch = (inner_x1 - inner_x0) / segments
    lit = round(max(0, min(100, percent)) / 100 * segments)
    for index in range(lit):
        sx0 = inner_x0 + index * pitch
        draw.rectangle((sx0 + 1, inner_y0 + 1, sx0 + pitch - 1, inner_y1 - 1), fill=0)


def _glm_quad(draw, box, glm):
    x0, y0, x1, y1 = box
    if not (glm and glm.get("quotas")):
        glm = placeholder_glm()
    level = glm.get("level") or ""
    top = _quad_head(draw, box, "CODING PLAN", f"{level}档" if level else "", icon="cpu")
    titles = {"5小时": "5小时额度", "周额度": "每周额度"}
    items = list(glm["quotas"].items())[:2]
    group_h = (y1 - 8 - top) / max(1, len(items))
    for index, (title, quota) in enumerate(items):
        group_top = top + index * group_h
        group_mid = group_top + group_h / 2
        reset = quota["reset"]
        reset_text = reset if any(word in reset for word in ("失败", "权限")) else f"重置 {reset}"
        # 名称行与工作计划正文同字号（18px/550）；空间变大后进度条上下间距加大
        name_text = truncate_text(draw, f"{titles.get(title, title)} · {reset_text}",
                                  noto(18, 550), x1 - 12 - 70 - (x0 + 14))
        draw.text((x0 + 14, group_mid - 32), name_text, font=noto(18, 550), fill=0)
        draw.text((x1 - 12, group_mid - 36), f'{quota["percent"]}%',
                  font=noto(22, FONT_STRONG), fill=0, anchor="ra")
        _quota_bar(draw, x0 + 14, x1 - 12, group_mid + 14, quota["percent"])


def render_dashboard(weather, plans, glm, now):
    image = Image.new("L", (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    frame(draw)
    _weather_quad(image, draw, QUADS["weather"], weather, now)
    _calendar_quad(draw, QUADS["calendar"], now)
    _plans_quad(draw, QUADS["plans"], plans)
    _glm_quad(draw, QUADS["glm"], glm)
    return image
