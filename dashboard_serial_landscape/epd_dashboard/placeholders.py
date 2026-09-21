"""数据缺失/获取失败时的占位数据。"""


def placeholder_weather(now):
    # 页1只读实况子集；页6横版额外字段给安全缺省（hourly/days 故意缺省，渲染端画"待刷新"）
    return {
        "temperature": 0.0, "humidity": 0, "precipitation": 0, "wind": 0.0, "uv_index": 0.0,
        "description": "数据待更新", "high": 0.0, "low": 0.0, "updated": now.strftime("%H:%M"),
        "city": "北京", "code": 3, "feels": 0.0, "rain_mm": 0.0, "pressure": 1013.0,
        "wind_degree": 0, "sunrise": "--:--", "sunset": "--:--", "moon": 0.5,
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
