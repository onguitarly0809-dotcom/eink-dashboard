"""页6（横版天气整页）：800×480 直接按 EPD 原生横屏方向绘制。

硬件从竖放顺时针转 90° 后面板回到原生横向，帧缓冲无需旋转（cli 里 orientation=none）。
版式参考经典黑红白 e-paper 天气面板：顶部定位条 / 大数字温度 + 天况 + 图标 + 风向罗盘 +
四格元数据侧栏 / 5日预报卡列 / 底部 36h 气温与 30h 降水概率双图表。
纯黑白面板：照片里红色承担的"元信息层"用小字号标签、细虚线和反白色块等价表达。
"""
import math

from PIL import Image, ImageDraw

from epd_dashboard.config import EPD_HEIGHT, EPD_WIDTH
from epd_dashboard.fonts import font
from epd_dashboard.fetchers.weather import describe

WEEKDAY = "一二三四五六日"

# 横向分区（y 向）：顶条 14..62 / 主区 66..254 / 预报卡 262..372 / 图表 380..470
CARD_BOX = (20, 262, 780, 372)
TEMP_CHART_BOX = (20, 380, 530, 470)
POP_CHART_BOX = (538, 380, 780, 470)
SIDEBAR_BOX = (530, 66, 778, 254)


def _dashed_line(draw, p0, p1, dash=4, gap=3, width=1, fill=0):
    x0, y0 = p0
    x1, y1 = p1
    length = math.hypot(x1 - x0, y1 - y0)
    if length == 0:
        return
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    pos = 0.0
    while pos < length:
        end = min(pos + dash, length)
        draw.line((x0 + dx * pos, y0 + dy * pos, x0 + dx * end, y0 + dy * end), fill=fill, width=width)
        pos = end + gap


def _pixel_text(image, xy, text, size, scale, weight=700):
    # 点阵大数字：小字号绘制后按 NEAREST 整数倍放大，得到墨水屏友好的位图像素风格
    fnt = font(size, weight)
    pad = 2
    tmp = Image.new("L", (int(fnt.getlength(text)) + pad * 2, size * 2), 255)
    ImageDraw.Draw(tmp).text((pad, pad), text, font=fnt, fill=0)
    bbox = tmp.point(lambda v: 255 - v).getbbox()  # 反相后取黑色内容的紧致包围盒
    if bbox:
        tmp = tmp.crop(bbox)
    tmp = tmp.resize((tmp.width * scale, tmp.height * scale), Image.NEAREST)
    image.paste(tmp, xy)
    return tmp.width, tmp.height


def _cloud(draw, cx, cy, s):
    # 实心云：双椭圆 + 底部矩形，宽约 1.2s、高约 0.75s（s 为名义尺寸）
    draw.ellipse((cx - 0.65 * s, cy - 0.05 * s, cx - 0.05 * s, cy + 0.45 * s), fill=0)
    draw.ellipse((cx - 0.40 * s, cy - 0.30 * s, cx + 0.45 * s, cy + 0.45 * s), fill=0)
    draw.rectangle((cx - 0.55 * s, cy + 0.20 * s, cx + 0.35 * s, cy + 0.45 * s), fill=0)


def _sun(draw, cx, cy, r, width):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
    for i in range(8):
        ang = math.pi / 4 * i
        draw.line((cx + math.cos(ang) * r * 1.5, cy + math.sin(ang) * r * 1.5,
                   cx + math.cos(ang) * r * 2.1, cy + math.sin(ang) * r * 2.1), fill=0, width=width)


def draw_icon(draw, cx, cy, s, code):
    """WMO 天气码 -> 单色矢量图标，cx/cy 为中心，s 为名义直径。"""
    code = int(code)
    width = max(2, int(s / 16))
    if code in (0, 1):
        _sun(draw, cx, cy, s * 0.22, width)
    elif code == 2:
        _sun(draw, cx - s * 0.30, cy - s * 0.30, s * 0.16, max(2, width - 1))
        _cloud(draw, cx + s * 0.08, cy + s * 0.10, s * 0.72)
    elif code in (45, 48):
        _cloud(draw, cx, cy - s * 0.28, s * 0.85)
        for k in range(3):
            y = cy + s * 0.12 + k * s * 0.18
            draw.line((cx - 0.45 * s, y, cx + 0.45 * s, y), fill=0, width=width)
    elif code in (51, 53, 55, 61, 63, 65, 66, 67, 80, 81, 82):
        _cloud(draw, cx, cy - s * 0.28, s * 0.85)
        for xr in (-0.28, 0.0, 0.28):
            x = cx + xr * s
            draw.line((x, cy + s * 0.18, x - s * 0.10, cy + s * 0.42), fill=0, width=width)
    elif code in (71, 73, 75, 77, 85, 86):
        _cloud(draw, cx, cy - s * 0.28, s * 0.85)
        r2 = max(1.5, s * 0.06)
        for xr in (-0.26, 0.02, 0.30):
            draw.ellipse((cx + xr * s - r2, cy + s * 0.30 - r2, cx + xr * s + r2, cy + s * 0.30 + r2), fill=0)
    elif code >= 95:
        _cloud(draw, cx, cy - s * 0.30, s * 0.85)
        draw.polygon(((cx + 0.10 * s, cy + 0.05 * s), (cx - 0.18 * s, cy + 0.42 * s), (cx - 0.02 * s, cy + 0.42 * s),
                      (cx - 0.12 * s, cy + 0.72 * s), (cx + 0.18 * s, cy + 0.30 * s), (cx + 0.02 * s, cy + 0.30 * s)),
                     fill=0)
    else:
        _cloud(draw, cx, cy, s * 0.85)


def draw_moon(draw, cx, cy, r, phase, outline_w=2):
    """月相：0=新月 0.5=满月。北半球视角，盈月右亮。先填暗面再描边。"""
    disc = (cx - r, cy - r, cx + r, cy + r)
    p = phase % 1.0
    if p < 0.02 or p > 0.98:
        draw.ellipse(disc, fill=0)
    elif abs(p - 0.5) < 0.02:
        pass
    else:
        waxing = p < 0.5
        k = math.cos(2 * math.pi * p)  # 1=新月 -> -1=满月
        if waxing:  # 暗面在左半圆
            draw.pieslice(disc, 90, 270, fill=0)
        else:       # 暗面在右半圆
            draw.pieslice(disc, -90, 90, fill=0)
        a = abs(k) * r  # 明暗界线椭圆的半宽
        if a >= 1:
            ebox = (cx - a, cy - r, cx + a, cy + r)
            if waxing:
                if k > 0:   # 眉月：暗面越过中线凸向右
                    draw.pieslice(ebox, -90, 90, fill=0)
                else:       # 盈凸：亮面越过中线，从暗半圆上擦回
                    draw.pieslice(ebox, 90, 270, fill=255)
            else:
                if k > 0:   # 亏眉月：暗面凸向左
                    draw.pieslice(ebox, 90, 270, fill=0)
                else:       # 亏凸：亮面凸向右擦回
                    draw.pieslice(ebox, -90, 90, fill=255)
    draw.ellipse(disc, outline=0, width=outline_w)


def draw_compass(draw, cx, cy, r, degree, speed, speed_font):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=0, width=2)
    label_font = font(13)
    for label, ang in (("N", -90), ("E", 0), ("S", 90), ("W", 180)):
        rr = r + 10
        x = cx + math.cos(math.radians(ang)) * rr
        y = cy + math.sin(math.radians(ang)) * rr
        draw.text((x, y), label, font=label_font, fill=0, anchor="mm")
    rad = math.radians(degree)  # 气象风向（风的来向），0=北风指向南……箭头指向风的去向更直观
    tip_x = cx + math.sin(rad) * r * 0.78
    tip_y = cy - math.cos(rad) * r * 0.78
    tail_x = cx - math.sin(rad) * r * 0.30
    tail_y = cy + math.cos(rad) * r * 0.30
    draw.line((tail_x, tail_y, tip_x, tip_y), fill=0, width=4)
    ang = math.radians(degree)
    wing = math.radians(degree + 150)
    wing2 = math.radians(degree - 150)
    head = r * 0.30
    draw.polygon((
        (tip_x, tip_y),
        (tip_x + math.sin(wing) * head, tip_y - math.cos(wing) * head),
        (tip_x + math.sin(wing2) * head, tip_y - math.cos(wing2) * head),
    ), fill=0)
    draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=0)
    draw.text((cx, cy + r + 22), speed, font=speed_font, fill=0, anchor="mm")


def _top_bar(draw, weather, now):
    city = weather.get("city", "北京")
    city_font = font(30, 700)
    draw.text((22, 12), city, font=city_font, fill=0)
    date_font = font(17)
    draw.text((22 + draw.textlength(city, font=city_font) + 18, 25),
              f'{now.strftime("%m/%d")} 周{WEEKDAY[now.weekday()]}', font=date_font, fill=0)
    update_font = font(15)
    update_text = f'更新 {weather.get("updated", now.strftime("%H:%M"))}'
    update_width = draw.textlength(update_text, font=update_font)
    draw.text((778, 27), update_text, font=update_font, fill=0, anchor="rs")
    alert = weather.get("alert")
    if alert:
        text = f'{alert["type"]}{alert["level"]}预警'
        alert_font = font(15, 700)
        text_width = draw.textlength(text, font=alert_font)
        x1 = 778 - update_width - 14
        draw.rectangle((x1 - text_width - 18, 18, x1, 44), fill=0)
        draw.text((x1 - 9, 31), text, font=alert_font, fill=255, anchor="mm")
    draw.line((20, 62, 780, 62), fill=0, width=2)


def _main_zone(image, draw, weather, now):
    # 左：巨型位图温度 + °C；下接天况与体感
    temp = weather.get("temperature", 0.0)
    big_w, big_h = _pixel_text(image, (22, 64), f"{temp:.0f}", 46, 3)
    degree_font = font(28, 700)
    draw.text((22 + big_w + 6, 64 + big_h), "°C", font=degree_font, fill=0, anchor="ls")
    draw.text((24, 186), weather.get("description", "—"), font=font(24, 700), fill=0)
    feels = weather.get("feels")
    feels_text = f"体感 {feels:.0f}°C" if feels is not None else "体感 --°C"
    draw.text((24, 220), feels_text, font=font(17), fill=0)

    # 中：天气图标 + 月相 + 风向罗盘
    draw_icon(draw, 300, 138, 96, weather.get("code", 3))
    draw_moon(draw, 300, 226, 13, weather.get("moon", 0.5))
    draw.text((320, 226), "月相", font=font(11), fill=0, anchor="lm")
    speed_font = font(16, 700)
    draw_compass(draw, 428, 136, 48, weather.get("wind_degree", 0),
                 f'{weather.get("wind", 0):.0f} 公里/时', speed_font)

    # 右：四格元数据侧栏
    draw.rectangle(SIDEBAR_BOX, outline=0, width=2)
    mx = (SIDEBAR_BOX[0] + SIDEBAR_BOX[2]) // 2
    my = (SIDEBAR_BOX[1] + SIDEBAR_BOX[3]) // 2
    draw.line((mx, SIDEBAR_BOX[1], mx, SIDEBAR_BOX[3]), fill=0, width=1)
    draw.line((SIDEBAR_BOX[0], my, SIDEBAR_BOX[2], my), fill=0, width=1)
    pressure = weather.get("pressure")
    cells = [
        (SIDEBAR_BOX[0], SIDEBAR_BOX[1], "湿度", f'{weather.get("humidity", 0):.0f}%', 26),
        (mx, SIDEBAR_BOX[1], "气压", (f"{pressure:.0f}hPa" if pressure else "--"), 21),
        (SIDEBAR_BOX[0], my, "降水", f'{weather.get("rain_mm", 0) or 0:.1f} mm', 23),
        (mx, my, "日落", weather.get("sunset", "--:--"), 25),
    ]
    for cx, cy, label, value, value_size in cells:
        draw.text((cx + 18, cy + 14), label, font=font(13), fill=0)
        draw.text((cx + 18, cy + 40), value, font=font(value_size, 700), fill=0)


def _daily_cards(draw, days):
    x0, y0, x1, y1 = CARD_BOX
    if not days:
        draw.rectangle(CARD_BOX, outline=0, width=2)
        draw.text(((x0 + x1) / 2, (y0 + y1) / 2), "预报数据待刷新", font=font(16), fill=0, anchor="mm")
        return
    count = len(days)
    gap = 8
    card_w = (x1 - x0 - gap * (count - 1)) / count
    for i, day in enumerate(days):
        cx0 = x0 + i * (card_w + gap)
        draw.rectangle((cx0, y0, cx0 + card_w, y1), outline=0, width=2)
        draw.text((cx0 + 12, y0 + 9), day["label"], font=font(17, 700), fill=0)
        draw_icon(draw, cx0 + card_w - 26, y0 + 24, 26, day["code"])
        draw.text((cx0 + 12, y0 + 42), f'{day["high"]:.0f}/{day["low"]:.0f}°', font=font(24, 700), fill=0)
        draw.text((cx0 + 12, y0 + 72), "高 / 低", font=font(11), fill=0)
        draw.text((cx0 + 12, y0 + 88), f'降水 {day["pop"]:.0f}%', font=font(13), fill=0)


def _temp_chart(draw, hourly):
    x0, y0, x1, y1 = TEMP_CHART_BOX
    draw.rectangle(TEMP_CHART_BOX, outline=0, width=2)
    draw.text((x0 + 12, y0 + 7), "气温 · 未来36小时", font=font(14, 700), fill=0)
    times = hourly.get("time") or []
    temps = [t if t is not None else 0 for t in (hourly.get("temp") or [])]
    if len(temps) < 2:
        draw.text((x0 + 12, y0 + 44), "逐时数据待刷新", font=font(14), fill=0)
        return
    plot = (x0 + 64, y0 + 34, x1 - 16, y1 - 26)
    vmin, vmax = min(temps), max(temps)
    if vmax - vmin < 1:
        vmax = vmin + 1
    plot_w, plot_h = plot[2] - plot[0], plot[3] - plot[1]

    def px(i):
        return plot[0] + plot_w * i / (len(temps) - 1)

    def py(t):
        return plot[3] - plot_h * (t - vmin) / (vmax - vmin)

    for v in (vmax, vmin):  # 最值参考虚线 + 左侧刻度
        _dashed_line(draw, (plot[0], py(v)), (plot[2], py(v)), width=1)
        draw.text((plot[0] - 8, py(v)), f"{v:.0f}°", font=font(12), fill=0, anchor="rm")
    for i, t in enumerate(times):  # 零点分界虚线
        if t.endswith("T00:00"):
            _dashed_line(draw, (px(i), plot[1]), (px(i), plot[3]), width=1)
    draw.line([(px(i), py(t)) for i, t in enumerate(temps)], fill=0, width=2, joint="curve")
    for i, t in enumerate(temps):
        x, y = px(i), py(t)
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=0)
    for i, t in enumerate(times):
        if i % 6 == 0:
            draw.text((px(i), y1 - 13), f"{int(t[11:13])}时", font=font(11), fill=0, anchor="mm")


def _pop_chart(draw, hourly, hours=30):
    x0, y0, x1, y1 = POP_CHART_BOX
    draw.rectangle(POP_CHART_BOX, outline=0, width=2)
    draw.text((x0 + 12, y0 + 7), "降水概率 · 未来30小时", font=font(14, 700), fill=0)
    times = (hourly.get("time") or [])[:hours]
    pops = [p or 0 for p in (hourly.get("pop") or [])[:hours]]
    plot = (x0 + 16, y0 + 34, x1 - 12, y1 - 26)
    baseline = plot[3]
    plot_w = plot[2] - plot[0]
    step = plot_w / hours
    bar_w = max(2.0, step * 0.6)
    if pops:
        vmax = max(pops)
        for i, p in enumerate(pops):
            if p > 0:
                bx = plot[0] + step * (i + 0.5)
                h = (plot[3] - plot[1]) * p / 100.0
                draw.rectangle((bx - bar_w / 2, baseline - h, bx + bar_w / 2, baseline), fill=0)
        if vmax >= 10:
            i_max = pops.index(vmax)
            bx = plot[0] + step * (i_max + 0.5)
            top = baseline - (plot[3] - plot[1]) * vmax / 100.0
            draw.text((bx, top - 4), f"{vmax:.0f}%", font=font(11), fill=0, anchor="ms")
    draw.line((plot[0], baseline, plot[2], baseline), fill=0, width=1)
    for i, t in enumerate(times):
        if i % 6 == 0:
            bx = plot[0] + step * (i + 0.5)
            draw.text((bx, y1 - 13), f"{int(t[11:13])}时", font=font(11), fill=0, anchor="mm")


def render_page6(weather, now):
    image = Image.new("L", (EPD_WIDTH, EPD_HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    _top_bar(draw, weather, now)
    _main_zone(image, draw, weather, now)
    _daily_cards(draw, weather.get("days") or [])
    hourly = weather.get("hourly") or {}
    _temp_chart(draw, hourly)
    _pop_chart(draw, hourly)
    return image
