"""数据缺失/获取失败时的占位数据。"""


def placeholder_weather(now):
    return {
        "temperature": 0.0, "humidity": 0, "precipitation": 0, "wind": 0.0, "uv_index": 0.0,
        "description": "数据待更新", "high": 0.0, "low": 0.0, "updated": now.strftime("%H:%M"),
    }


def placeholder_quotas():
    # 当arkcli不可用时，显示提示信息而不是全部为0
    return {
        "5小时": {"remaining": 0, "total": 100, "percent": 0, "reset": "权限问题"},
        "周额度": {"remaining": 0, "total": 1000, "percent": 0, "reset": "权限问题"},
        "月额度": {"remaining": 0, "total": 5000, "percent": 0, "reset": "权限问题"}
    }


def placeholder_glm():
    # GLM Coding Plan 获取失败时的占位：只有 5小时/每周两个窗口，无月额度
    return {
        "level": "",
        "quotas": {
            "5小时": {"remaining": 0, "total": 100, "percent": 0, "reset": "获取失败"},
            "周额度": {"remaining": 0, "total": 1000, "percent": 0, "reset": "获取失败"},
        },
    }
