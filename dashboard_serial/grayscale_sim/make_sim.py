# -*- coding: utf-8 -*-
"""四灰改善效果模拟：同一张灰度 AA 原图，走不同落屏管线后的观感对比。

源图 = 渲染管线落盘的 preview PNG（阈值化之前的 mode L 灰度图），
变体：
  A 现状    1bit 硬阈值128（= output.py convert("1", dither=NONE) 的等效复现）
  D 零成本  1bit 阈值160（只改一行，细笔画更连贯、略粗）
  B 四灰    2bit 量化到 0/85/170/255（微雪 7.5V2 4灰模式的等距近似模拟）
  C 参考    原始灰度不动（16灰+抗锯齿，Kindle 级渲染的天花板）
输出 gray_sim_full.png（整页+观看距离模拟）与 gray_sim_crops.png（局部4x放大）。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent.parent          # dashboard_serial/
# 快照而非活文件：轮播每20分钟重写 dashboard_preview.png，快照保证模拟可复现
SRC = Path(__file__).resolve().parent / "source_snapshot.png"
OUT = Path(__file__).resolve().parent

src = Image.open(SRC).convert("L")

# ---- 四条落屏管线 ----
A = src.point(lambda v: 255 if v > 127 else 0)          # 现状
D = src.point(lambda v: 255 if v > 159 else 0)          # 阈值160
B = src.point(lambda v: int(round(v / 85)) * 85)        # 四灰量化
C = src                                                 # 灰度天花板

VARIANTS = [
    ("A 现状 1bit 阈值128", A),
    ("D 1bit 阈值160（零成本）", D),
    ("B 四灰 2bit（模拟）", B),
    ("C 16灰 参考（Kindle级）", C),
]

# ---- 像素统计：现状扔掉了多少灰度信息 ----
h = src.histogram()
mid_total = sum(h[32:224])
text_px = sum(h[:240])
diff = sum(1 for a, b in zip(A.getdata(), B.getdata()) if a != b)
print(f"中间调像素 32-223: {mid_total} ({100*mid_total/src.size[0]/src.size[1]:.1f}% 全屏)")
print(f"A/B 落屏结果不同的像素: {diff} ({100*diff/src.size[0]/src.size[1]:.1f}% 全屏) —— 四灰能改写的信息量")
print(f"文字区(灰度<240)中落在中间调的比例: {100*mid_total/max(text_px,1):.1f}%")

# ---- 标注工具 ----
LABEL_FONT = ImageFont.truetype(r"C:\Windows\Fonts\NotoSansSC-VF.ttf", 22)
CAPTION_FONT = ImageFont.truetype(r"C:\Windows\Fonts\NotoSansSC-VF.ttf", 24)


def labeled(img, text, pad=8):
    w, hgt = img.size
    tile = Image.new("L", (w, hgt + 34), 255)
    tile.paste(img, (0, 34))
    d = ImageDraw.Draw(tile)
    d.text((pad, 4), text, font=LABEL_FONT, fill=0)
    return tile


# ---- 整页对比：A/B/C 1:1 一行 + A/B 50%缩小再放大模拟60cm观看一行 ----
def perceived(img):
    """50% LANCZOS 缩小再放大回原尺寸：近似 60cm 观看距离下人眼的低通。"""
    return img.resize((img.width // 2, img.height // 2), Image.LANCZOS).resize(img.size, Image.BICUBIC)


GAP = 6
page_tiles = [labeled(im, t) for t, im in VARIANTS]
pw = max(t.width for t in page_tiles)
full1 = Image.new("L", (pw * 4 + GAP * 3, max(t.height for t in page_tiles)), 255)
for i, t in enumerate(page_tiles):
    full1.paste(t, (i * (pw + GAP), 0))

per_tiles = [labeled(perceived(im), t + " · 模拟60cm观看", ) for t, im in VARIANTS]
full2 = Image.new("L", (full1.width, max(t.height for t in per_tiles)), 255)
for i, t in enumerate(per_tiles):
    full2.paste(t, (i * (pw + GAP), 0))

sheet = Image.new("L", (full1.width, full1.height + full2.height + 40), 255)
sheet.paste(full1, (0, 0))
d = ImageDraw.Draw(sheet)
d.text((GAP, full1.height + 4), "↑ 1:1 像素级                ↓ 60cm 观看距离模拟（50%缩小再放大）", font=LABEL_FONT, fill=0)
sheet.paste(full2, (0, full1.height + 40))
sheet.save(OUT / "gray_sim_full.png")
print("saved gray_sim_full.png", sheet.size)

# ---- 局部 4x 放大：三个代表区 ----
# rotate=90：页4正文为竖排渲染（源图里字是横躺的），裁剪后转正便于阅读，仅影响展示
CROPS = {
    "标题区（26px上下）": ((656, 10, 800, 150), None),
    "正文密排（16-18px）": ((330, 120, 470, 260), 90),
    "小节标题+正文": ((398, 8, 552, 178), 90),
}
ZOOM = 4
rows = []
for name, (box, rot) in CROPS.items():
    def crop_upright(im):
        tile = im.crop(box)
        if rot:
            tile = tile.transpose(Image.Transpose.ROTATE_90)
        return tile.resize((tile.width * ZOOM, tile.height * ZOOM), Image.NEAREST)

    note = "，已转正显示" if rot else ""
    tiles = [labeled(crop_upright(im), t) for t, im in VARIANTS]
    row = Image.new("L", (max(t.width for t in tiles) * 4 + GAP * 3,
                          max(t.height for t in tiles) + 40), 255)
    for i, t in enumerate(tiles):
        row.paste(t, (i * (t.width + GAP), 0))
    d = ImageDraw.Draw(row)
    d.text((GAP, row.height - 32), f"■ {name} （局部 {ZOOM}x 最近邻放大{note}）", font=CAPTION_FONT, fill=0)
    rows.append(row)

cw = max(r.width for r in rows)
crops_sheet = Image.new("L", (cw, sum(r.height for r in rows) + GAP * (len(rows) - 1)), 255)
y = 0
for r in rows:
    crops_sheet.paste(r, (0, y))
    y += r.height + GAP
crops_sheet.save(OUT / "gray_sim_crops.png")
print("saved gray_sim_crops.png", crops_sheet.size)
