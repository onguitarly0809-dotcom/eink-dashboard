"""屏幕自检测试图：棋盘格 / 全黑 / 全白 / 信息页。"""
from PIL import Image, ImageDraw

from epd_dashboard.config import HEIGHT, WIDTH
from epd_dashboard.fonts import FONT_STRONG, SIZE_L, font


def render_test(pattern, now):
    image = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(image)
    if pattern == "chess":
        cell = 40
        for y in range(0, HEIGHT, cell):
            for x in range(0, WIDTH, cell):
                if (x // cell + y // cell) % 2 == 0:
                    draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=0)
    elif pattern == "black":
        draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), fill=0)
    elif pattern == "white":
        pass
    else:  # info
        draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=0, width=3)
        lines = [
            "EPD 测试页",
            now.strftime("%Y-%m-%d %H:%M:%S"),
            f"分辨率 {WIDTH}x{HEIGHT}",
            "7.5in V2 · 串口 115200",
            "若显示正常则屏幕 OK",
        ]
        y = 120
        for line in lines:
            draw.text((24, y), line, font=font(SIZE_L, FONT_STRONG), fill=0)
            y += 60
    return image
