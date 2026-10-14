# 测试环境引导：仓库根挂 sys.path + 默认横版运营目录（个别测试自行覆盖变体）
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("EPD_VARIANT", "landscape")
os.environ.setdefault("EPD_BASE_DIR", str(ROOT / "dashboard_serial_landscape"))


def force_variant(name):
    """合跑隔离：显式指定变体并清掉前序测试留下的核心包模块缓存。

    config 在 import 时按 EPD_VARIANT 平铺常量，同进程先后跑不同变体的测试
    必须各自 force_variant 后再 import 相关模块。"""
    import os as _os
    import sys as _sys
    root = Path(__file__).resolve().parent.parent
    _os.environ["EPD_VARIANT"] = name
    _os.environ["EPD_BASE_DIR"] = str(root / ("dashboard_serial_landscape" if name == "landscape" else "dashboard_serial"))
    for m in [m for m in list(_sys.modules) if m.startswith("epd_dashboard")]:
        del _sys.modules[m]
