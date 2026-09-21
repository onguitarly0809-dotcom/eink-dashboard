"""字体加载（横版 V3）：Fusion Pixel 中文像素字体优先，墨水屏 1-bit 全页统一点阵纹理。

设计规则（TRMNL Framework 同款）：
- 全页只用像素字，字号必须落在 8/10/12px 原生字号的整数倍格栅上；
  font(size) 会把任意请求尺寸吸附到最近的格栅档，调用方无需逐处改字号。
- 像素字为单一字重：font() 的 weight 参数在像素模式下仅作兼容保留，
  强调一律靠字号与反白/描边（common.text_bold）表达，不再依赖字重。
- px(native, scale) 直接按原生字号×倍数取字，供位图放大型巨号数字使用。
"""
import functools
from pathlib import Path

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
_PIXEL_FILES = {
    8: FONT_DIR / "fusion-pixel-8px-proportional-zh_hans.otf",
    10: FONT_DIR / "fusion-pixel-10px-proportional-zh_hans.otf",
    12: FONT_DIR / "fusion-pixel-12px-proportional-zh_hans.otf",
}

# 兼容旧调用方的字重常量与字号档（会被吸附到像素格栅，见 font()）
FONT_REGULAR = 400
FONT_STRONG = 700
FONT_BOLD = 700

SIZE_XL = 40
SIZE_L = 32
SIZE_M = 18
SIZE_S = 16
SIZE_XS = 12
SIZE_XXS = 11

_NATIVE_BASES = (8, 10, 12)
_MAX_SCALE = 8
MIN_DISPLAY_SIZE = 16  # 真屏下限：12px 原生字高仅 2.5mm，40-60cm 观看距离不可读（V3.1 实机反馈）


def _lattice():
    return sorted(n * k for n in _NATIVE_BASES for k in range(1, _MAX_SCALE + 1))


_LATTICE = tuple(_lattice())


def snap_size(size):
    """把请求字号吸附到最近的像素格栅档（8/10/12 的整数倍）。"""
    return min(_LATTICE, key=lambda cand: (abs(cand - size), -cand))


def pixel_available():
    return all(path.exists() for path in _PIXEL_FILES.values())


@functools.lru_cache(maxsize=8)
def _load_pixel(native, scale):
    return ImageFont.truetype(str(_PIXEL_FILES[native]), native * scale)


# 像素字不可用时回退思源黑体（保留竖版同款逻辑）
NOTO_FONT = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")


@functools.lru_cache(maxsize=64)
def _load_noto(size: int, weight: int):
    fnt = ImageFont.truetype(str(NOTO_FONT), size)
    fnt.set_variation_by_axes([weight])
    return fnt


def px(native, scale):
    """按原生字号 × 整数倍取像素字体（8/10/12 中任选一个原生档）。"""
    return _load_pixel(native, scale)


def noto(size: int, weight: int = FONT_REGULAR):
    """正文阅读字体：思源黑体。

    像素字适合展示层（巨号数字/短标签），长句中文正文在真屏上
    笔画发糊（实机反馈），阅读性文字一律走本接口。
    """
    if NOTO_FONT.exists():
        try:
            return _load_noto(size, weight)
        except Exception:
            pass
    return ImageFont.load_default()


def font(size: int, weight: int = FONT_REGULAR):
    """取展示字体：像素模式下吸附格栅并钳制到可读下限、字重折叠。"""
    if pixel_available():
        snapped = max(MIN_DISPLAY_SIZE, snap_size(size))
        # 同一档位优先更精细的原生字号（24 = 12×2 优于 8×3），字形细节更多
        for native in sorted(_NATIVE_BASES, reverse=True):
            if snapped % native == 0 and snapped // native <= _MAX_SCALE:
                return _load_pixel(native, snapped // native)
        return _load_pixel(12, snapped // 12)
    if NOTO_FONT.exists():
        try:
            return _load_noto(size, weight)
        except Exception:
            pass
    return ImageFont.load_default()
