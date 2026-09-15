"""通用小工具。"""


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
