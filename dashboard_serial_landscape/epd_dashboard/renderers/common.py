"""横版渲染公共件（V3 墨水屏设计体系）。

- draw_box：栏目外框+黑底白字标题 chip（全页统一"家族脸"），1px 线纪律
- dither：1-bit 屏灰阶模拟（TRMNL 式抖动纹理），用于分区底纹/图表填充/电量条空格
- draw_chip / draw_label：黑底白字标签块 / 手工字距小标签
- text_bold：像素字描边加粗（像素字无字重，强调靠描边与字号）
"""
import functools
import json
from pathlib import Path

from PIL import Image

from epd_dashboard.config import HEIGHT, WIDTH
from epd_dashboard.fonts import FONT_STRONG, SIZE_S, font

# ---------- Tabler Icons 线稿图标字体（MIT，全页共用） ----------
_TABLER_DIR = Path(__file__).resolve().parent.parent.parent / "fonts" / "tabler"
TABLER_MAP = json.loads((_TABLER_DIR / "mapping.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=16)
def tabler_font(size):
    from PIL import ImageFont
    return ImageFont.truetype(str(_TABLER_DIR / "tabler-icons.ttf"), size)


def tabler_glyph(name):
    return chr(TABLER_MAP[name])


def draw_tabler(draw, cx, cy, size, name, fill=0):
    """在 (cx, cy) 中心绘制 Tabler 线稿图标。"""
    draw.text((cx, cy), tabler_glyph(name), font=tabler_font(size), fill=fill, anchor="mm")


def weather_glyph_name(code):
    """天气码 → Tabler 图标名；多云(2) 需太阳+云双字形（见 draw_weather_icon）。"""
    code = int(code)
    if code in (0, 1):
        return "sun"
    if code in (45, 48):
        return "cloud-fog"
    if code in (51, 53, 55, 61, 63, 65, 66, 67, 80, 81, 82):
        return "cloud-rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "cloud-snow"
    if code >= 95:
        return "cloud-storm"
    return "cloud"


def draw_weather_icon(draw, cx, cy, size, code):
    """天气码 → 线稿天气图标；多云(2) 用 太阳+云 双字形叠画。"""
    code = int(code)
    if code == 2:
        draw_tabler(draw, cx - size * 0.16, cy - size * 0.14, size * 0.62, "sun-high")
        draw_tabler(draw, cx + size * 0.06, cy + size * 0.08, size * 0.78, "cloud")
    else:
        draw_tabler(draw, cx, cy, size, weather_glyph_name(code))


def truncate_text(draw, text, fnt, max_width):
    # 单行截断：超出 max_width 时从尾部截断加省略号
    if draw.textlength(text, font=fnt) <= max_width:
        return text
    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=fnt) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def _is_wordch(ch):
    # ASCII 字母/数字/常见连接符视为词元：横版窄栏换行时不拆英文单词/品牌名/数字
    return ch.isascii() and (ch.isalnum() or ch in "-._/@#&+'\"")


def _tokens(raw):
    out = []
    i = 0
    n = len(raw)
    while i < n:
        if _is_wordch(raw[i]):
            j = i
            while j < n and _is_wordch(raw[j]):
                j += 1
            # 超长词元（长URL等）按 40 字符强制分段，避免单行溢出
            while j - i > 40:
                out.append(raw[i:i + 40])
                i += 40
            out.append(raw[i:j])
            i = j
        else:
            out.append(raw[i])
            i += 1
    return out


_CLOSING_PUNCT = "，。、；：！？）》」』”’,.:;!?%…"
_HANG_LIMIT = 18  # 禁则悬挂的允许出格量（px）：一个全角标点位。标点墨迹只占左半格，
                  # 视觉出格≈9px < 栏内边距，不会触碰相邻元素


def wrap_text(draw, text, fnt, max_width):
    """多行排版：词元贪心断行——中文逐字、英文单词/数字串整体，行首不保留空格；
    闭合标点按中文禁则不落行首，悬挂在上一行行尾（允许少量出格）。返回行列表。"""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = ""
        for token in _tokens(raw):
            candidate = line + token
            if draw.textlength(candidate, font=fnt) <= max_width:
                line = candidate
                continue
            if (line and len(token) <= 2 and token[0] in _CLOSING_PUNCT
                    and draw.textlength(line + token, font=fnt) <= max_width + _HANG_LIMIT):
                line = candidate  # 禁则悬挂
                continue
            if line:
                lines.append(line)
            line = token
        lines.append(line)
    return lines


def text_right(draw, xy, value, fnt, fill=0):
    x, y = xy
    draw.text((x, y), value, font=fnt, fill=fill)
    return draw.textlength(value, font=fnt)


def draw_box(draw, box, title, right="", right_size=SIZE_S, title_weight=FONT_STRONG):
    """栏目外框（1px）+ 黑底白字标题 chip + 右侧元信息 + 1px 下划线。

    返回内容区起始 y。right_size/title_weight 参数仅为兼容旧调用方保留。
    """
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=0, width=1)
    chip_top = y0 + 9
    chip_x1, chip_y1 = draw_chip(draw, (x0 + 10, chip_top), title, size=12)
    line_y = y0 + 40
    draw.line((x0 + 10, line_y, x1 - 10, line_y), fill=0, width=1)
    if right:
        right_font = font(12)
        if draw.textlength(right, font=right_font) > x1 - 12 - chip_x1 - 12:
            right = truncate_text(draw, right, right_font, x1 - 12 - chip_x1 - 12)
        chip_mid = (chip_top + chip_y1) / 2
        draw.text((x1 - 12, chip_mid), right, font=right_font, fill=0, anchor="rm")
    return line_y + 8


def frame(draw):
    """整页外框，1px 线纪律。"""
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=0, width=1)


# ---------- 1-bit 灰阶抖动（TRMNL 式：用黑白点阵密度模拟灰阶） ----------

# ---------- 1-bit 灰阶抖动（TRMNL 式：用黑白点阵密度模拟灰阶） ----------

def _dither_tile(ratio):
    """生成 4x4 抖动 tile（L 模式，黑=0 白=255）。ratio 为黑点密度 0..1。"""
    order = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]
    threshold = round(ratio * 16)
    return Image.frombytes("L", (4, 4),
                           bytes(0 if order[i] < threshold else 255 for i in range(16)))


_TILES = {}


def _tile_for(ratio):
    tile = _TILES.get(ratio)
    if tile is None:
        tile = _dither_tile(ratio)
        _TILES[ratio] = tile
    return tile


def dither_rect(image, box, level="mid"):
    """把抖动纹理铺进 box 区域（覆盖底色）。
    level: "light"=12.5% "mid"=25% "heavy"=50% "dark"=75%（读作深灰）。"""
    ratio = {"light": 0.125, "mid": 0.25, "heavy": 0.5, "dark": 0.75}[level]
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    tile = _tile_for(ratio)
    pattern = Image.new("L", (w, h), 255)
    for ty in range(0, h, 4):
        for tx in range(0, w, 4):
            pattern.paste(tile, (tx, ty))
    image.paste(pattern, (x0, y0))


def dither_polygon(image, pts, level="mid"):
    """把抖动纹理按多边形填充（用于折线图下方区域填充）。"""
    if len(pts) < 3:
        return
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
    if x1 <= x0 or y1 <= y0:
        return
    mask = Image.new("L", (x1 - x0 + 1, y1 - y0 + 1), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in pts], fill=255)
    tile = _tile_for({"light": 0.125, "mid": 0.25, "heavy": 0.5}[level])
    pattern = Image.new("L", mask.size, 255)
    for ty in range(0, mask.size[1], 4):
        for tx in range(0, mask.size[0], 4):
            pattern.paste(tile, (tx, ty))
    image.paste(pattern, (x0, y0), mask)


def text_bold(draw, xy, value, fnt, fill=0, anchor=None):
    """像素字描边加粗：1px stroke 让重点数值在无字重的像素体系里获得强调。"""
    draw.text(xy, value, font=fnt, fill=fill, anchor=anchor,
              stroke_width=1, stroke_fill=fill)


def draw_chip(draw, xy, text, size=14, pad_x=7, pad_y=4, tracking=2, fill=0, glyph=None):
    """黑底白字标签块，可带前置 Tabler 图标（白色）。按实际字体度量定形，返回 (结束x, 底y)。"""
    fnt = font(size)
    ascent, descent = fnt.getmetrics()
    text_h = ascent + descent
    text_w = sum(draw.textlength(ch, font=fnt) + tracking for ch in text) - tracking
    glyph_w = 0
    gf = None
    if glyph:
        gf = tabler_font(size)
        glyph_w = draw.textlength(tabler_glyph(glyph), font=gf) + 8
    x, y = xy
    rect_h = text_h + pad_y * 2 - 4
    draw.rectangle((x, y, x + text_w + glyph_w + pad_x * 2, y + rect_h), fill=fill)
    tx = x + pad_x
    ty = y + (rect_h - text_h) // 2
    if glyph:
        g_size = size + 4
        draw_tabler(draw, tx + g_size / 2, y + rect_h / 2, g_size, glyph, fill=255)
        tx += glyph_w
    for ch in text:
        draw.text((tx, ty), ch, font=fnt, fill=255)
        tx += draw.textlength(ch, font=fnt) + tracking
    return x + text_w + glyph_w + pad_x * 2, y + rect_h

