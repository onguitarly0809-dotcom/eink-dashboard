"""字体加载与字号档位。

统一字体：思源黑体（Noto Sans SC，可变字体，字重可调）。中英文混排天然统一，适合墨水屏。
"""
import functools
from pathlib import Path

from PIL import ImageFont

NOTO_FONT = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")
FONT_REGULAR = 600
FONT_STRONG = 600
FONT_BOLD = 600

# 统一字号档位
SIZE_XL = 40
SIZE_L = 32
SIZE_M = 18
SIZE_S = 16
SIZE_XS = 12
SIZE_XXS = 11


# 可变字体文件约 17.8MB，重复解析单页可达秒级，必须按 (size, weight) 缓存
@functools.lru_cache(maxsize=64)
def _load_noto(size: int, weight: int):
    fnt = ImageFont.truetype(str(NOTO_FONT), size)
    fnt.set_variation_by_axes([weight])
    return fnt


def font(size: int, weight: int = FONT_REGULAR):
    if NOTO_FONT.exists():
        try:
            return _load_noto(size, weight)
        except Exception:
            pass
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if weight >= FONT_BOLD else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()
