"""版式注册表：横竖两个运营变体的版面常量与配额都在这里登记。

布局模块是纯常量（不 import 任何工程内模块），由 config.py 按当前变体
合并导出；页面渲染器与 fetchers 一律 `from epd_dashboard.config import X`。
"""
from importlib import import_module

VARIANTS = ("landscape", "portrait")


def get_layout(name):
    if name not in VARIANTS:
        raise RuntimeError(f"unknown layout variant: {name!r} (expected one of {VARIANTS})")
    return import_module(f"epd_dashboard.layouts.{name}")
