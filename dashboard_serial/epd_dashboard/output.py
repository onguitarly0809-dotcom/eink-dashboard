"""渲染结果落盘：竖屏 PNG、横屏预览 PNG、固件用的 1bpp 打包二进制。"""
import os

from PIL import Image

from epd_dashboard.config import EPD_IMAGE_BYTES


def rotate_for_epd(image, orientation):
    if orientation == "cw":
        return image.transpose(Image.Transpose.ROTATE_270)
    if orientation == "ccw":
        return image.transpose(Image.Transpose.ROTATE_90)
    if orientation == "none":
        return image
    raise ValueError(f"Unsupported orientation: {orientation}")


def _atomic_write(path, writer):
    # 先写临时文件再原子替换，并发的读方（web 的 /preview.png）不会读到半个文件
    tmp = path.with_name(path.name + ".tmp")
    writer(tmp)
    os.replace(tmp, path)


def write_outputs(portrait, args):
    args.output_dir.mkdir(parents=True, exist_ok=True)
    portrait_path = args.output_dir / "dashboard_portrait.png"
    preview_path = args.output_dir / "dashboard_preview.png"
    binary_path = args.output_dir / "dashboard.bin"
    landscape = rotate_for_epd(portrait, args.orientation)
    one_bit = landscape.convert("1", dither=Image.Dither.NONE)
    # EPD 固件 1=黑，PIL 打包 1=白，整体反转位 -> 屏幕白底黑字（浅色模式）
    packed = bytes(b ^ 0xFF for b in one_bit.tobytes())
    if len(packed) != EPD_IMAGE_BYTES:
        raise RuntimeError(f"Unexpected packed size: {len(packed)}")
    _atomic_write(portrait_path, lambda p: portrait.save(p, format="PNG"))
    _atomic_write(preview_path, lambda p: landscape.save(p, format="PNG"))
    _atomic_write(binary_path, lambda p: p.write_bytes(packed))
    return portrait_path, preview_path, binary_path, len(packed)
