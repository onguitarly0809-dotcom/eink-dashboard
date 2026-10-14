"""渲染结果落盘：竖屏 PNG、横屏预览 PNG、固件用打包二进制（1bpp 快刷 / 4灰两平面）。"""
import os

from PIL import Image, ImageFilter

from epd_dashboard.config import EPD_IMAGE_BYTES, EPD_IMAGE_BYTES_4G


def rotate_for_epd(image, orientation):
    if orientation == "cw":
        return image.transpose(Image.Transpose.ROTATE_270)
    if orientation == "ccw":
        return image.transpose(Image.Transpose.ROTATE_90)
    if orientation == "none":
        return image
    raise ValueError(f"Unsupported orientation: {orientation}")


# 四灰量化分档（L 值）：白界 160（真机调优：192 时正文灰边过宽显粗）：
#   <64 黑(00) / 64-127 深灰(01) / 128-159 浅灰(10) / >=160 白(11)
# 位平面提取自微雪 EPD_7IN5_V2_Display_4Gray（结合 demo 常量 GRAY2=0xC0 浅灰、
# GRAY3=0x80 深灰核定明暗，勿按 C 注释字面读——两灰注释与常量是反的）：
#   0x10 平面（先发）：位=1 ⇔ 黑或浅灰
#   0x13 平面（后发）：位=1 ⇔ 黑或深灰（v<128）
# 位序 MSB-first 光栅序，与 PIL convert("1") 打包一致（现有 1-bit 链路已验证）
_PLANE10_LUT = [255] * 64 + [0] * 64 + [255] * 32 + [0] * 96


def pack_4gray(image):
    """灰度图 → 4灰两平面二进制（96000B = 0x10 平面 + 0x13 平面，不反转）。

    局部已二值化的区域（标题层阈值160产物）只有 0/255，落黑/白两档保持锐利；
    正文抗锯齿边缘灰度进入深/浅灰档，即 4 灰模式的全部收益来源。
    """
    g = image.convert("L")
    plane10 = g.point(_PLANE10_LUT).convert("1")
    plane13 = g.point(lambda v: 255 if v < 128 else 0).convert("1")
    return plane10.tobytes() + plane13.tobytes()


# 四灰落屏前的轻量锐化（2026-09-30 清晰度调优）：unsharp 增强抗锯齿边缘对比后再
# 量化——中间灰像素减少、文字边缘更利。瓶颈判断：四灰只有 4 档灰，渲染端做 2× 超采样
# 的细腻灰阶会被量化抹平，故选择在量化前的这一步直接塑形。参数真机可调（percent 0=关）。
# 只作用于四灰路径；1-bit 无灰阶可塑，不适用。
SHARPEN_RADIUS = 2
SHARPEN_PERCENT = 130
SHARPEN_THRESHOLD = 2


def _sharpen_for_gray(image):
    if SHARPEN_PERCENT <= 0:
        return image
    return image.filter(ImageFilter.UnsharpMask(
        radius=SHARPEN_RADIUS, percent=SHARPEN_PERCENT, threshold=SHARPEN_THRESHOLD))


def _atomic_write(path, writer):
    # 先写临时文件再原子替换，并发的读方（web 的 /preview.png）不会读到半个文件
    tmp = path.with_name(path.name + ".tmp")
    writer(tmp)
    os.replace(tmp, path)


def write_outputs(portrait, args):
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # 页6横版天气用 _page6 后缀独立落盘，避免覆盖轮播正在推送的 dashboard.bin/preview
    suffix = getattr(args, "output_suffix", "")
    portrait_path = args.output_dir / f"dashboard{suffix}_portrait.png"
    preview_path = args.output_dir / f"dashboard{suffix}_preview.png"
    binary_path = args.output_dir / f"dashboard{suffix}.bin"
    landscape = rotate_for_epd(portrait, args.orientation)
    if getattr(args, "gray", False):
        packed = pack_4gray(_sharpen_for_gray(landscape))
        expected = EPD_IMAGE_BYTES_4G
    else:
        one_bit = landscape.convert("1", dither=Image.Dither.NONE)
        # EPD 固件 1=黑，PIL 打包 1=白，整体反转位 -> 屏幕白底黑字（浅色模式）
        packed = bytes(b ^ 0xFF for b in one_bit.tobytes())
        expected = EPD_IMAGE_BYTES
    if len(packed) != expected:
        raise RuntimeError(f"Unexpected packed size: {len(packed)} (expected {expected})")
    _atomic_write(portrait_path, lambda p: portrait.save(p, format="PNG"))
    _atomic_write(preview_path, lambda p: landscape.save(p, format="PNG"))
    _atomic_write(binary_path, lambda p: p.write_bytes(packed))
    return portrait_path, preview_path, binary_path, len(packed)
