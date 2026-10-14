"""天气：open-meteo 实况/逐时/多日 + 中央气象台预警（仅北京）。

页1只用实况子集（temperature/humidity/precipitation/wind/uv_index/description/high/low/updated），
扩展字段 feels/pressure/wind_degree/rain_mm/sunrise/sunset/moon/hourly/days 按全量抓取。
旧缓存缺新键时由渲染端 .get() 兜底，不在这里做版本迁移。
"""
import json
import re
from datetime import datetime, timezone

from epd_dashboard.config import WEATHER_ALERT_URL, WEATHER_CITY, WEATHER_URL
from epd_dashboard.httpclient import http_read

DESCRIPTIONS = {
    0: "晴", 1: "晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾",
    51: "小雨", 53: "小雨", 55: "小雨", 61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨", 71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨", 99: "强雷阵雨",
}


def describe(code):
    return DESCRIPTIONS.get(int(code), "多云")


def _moon_phase(now):
    # 月相本地计算：0=新月 0.5=满月，参考新月 2000-01-06 18:14 UTC，朔望月 29.5306 天
    reference = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    days = (now.astimezone(timezone.utc) - reference).total_seconds() / 86400.0
    return (days % 29.53058867) / 29.53058867


def _hourly_slice(hourly, start_key, hours=36):
    # 从当前小时起取 hours 个逐时点；start_key 为 "YYYY-MM-DDTHH:00" 字符串可直接字典序比较
    times = hourly["time"]
    start = next((i for i, t in enumerate(times) if t >= start_key), 0)
    end = min(len(times), start + hours)
    pop = hourly.get("precipitation_probability") or [0] * len(times)
    return {
        "time": times[start:end],
        "temp": hourly["temperature_2m"][start:end],
        "pop": [p or 0 for p in pop[start:end]],
    }


def _daily_list(daily, days=5):
    pops = daily.get("precipitation_probability_max") or [0] * len(daily["time"])
    result = []
    for i in range(min(days, len(daily["time"]))):
        day = datetime.fromisoformat(daily["time"][i])
        result.append({
            "label": "今天" if i == 0 else f"周{'一二三四五六日'[day.weekday()]}",
            "code": int(daily.get("weather_code", [2] * len(daily["time"]))[i]),
            "high": daily["temperature_2m_max"][i],
            "low": daily["temperature_2m_min"][i],
            "pop": pops[i] or 0,
        })
    return result


def _hhmm(iso):
    return iso[-5:] if iso else "--:--"


def _car_wash_index(days):
    """洗车指数（本地推导，Open-Meteo 无此生活指数）：未来 3 天内有雨/雪天气码
    或最大降水概率 ≥60% → 不宜；≥30% → 一般；否则 适宜。"""
    if not days:
        return "一般"
    max_pop = max(d["pop"] for d in days)
    wet_code = any(51 <= d["code"] <= 99 for d in days)
    if wet_code or max_pop >= 60:
        return "不宜"
    if max_pop >= 30:
        return "一般"
    return "适宜"


def fetch_weather(now=None):
    now = now or datetime.now().astimezone()
    payload = json.loads(http_read(WEATHER_URL))
    current = payload["current"]
    daily = payload["daily"]
    code = int(current.get("weather_code", 3))
    days = _daily_list(daily)
    weather = {
        # 页1在用的实况子集
        "temperature": current["temperature_2m"],
        "humidity": current["relative_humidity_2m"],
        "precipitation": current.get("precipitation_probability", 0),
        "wind": current["wind_speed_10m"],
        "uv_index": current.get("uv_index", 0),
        "description": DESCRIPTIONS.get(code, "多云"),
        "high": daily["temperature_2m_max"][0],
        "low": daily["temperature_2m_min"][0],
        "updated": datetime.fromisoformat(current["time"]).strftime("%H:%M"),
        # 扩展字段（全量抓取，页面按需消费）
        "city": WEATHER_CITY,
        "code": code,
        "feels": current.get("apparent_temperature"),
        "rain_mm": current.get("precipitation", 0.0),
        "pressure": current.get("surface_pressure"),
        "wind_degree": current.get("wind_direction_10m", 0),
        "sunrise": _hhmm(daily.get("sunrise", [None])[0]),
        "sunset": _hhmm(daily.get("sunset", [None])[0]),
        "moon": _moon_phase(now),
        "hourly": _hourly_slice(payload["hourly"], current["time"][:13] + ":00"),
        "days": days,
        "car_wash": _car_wash_index(days),
    }
    try:
        weather["alert"] = fetch_weather_alert()
    except Exception:
        weather["alert"] = None
    return weather


def fetch_weather_alert():
    payload = json.loads(http_read(WEATHER_ALERT_URL, tries=1))
    alarms = payload.get("data", {}).get("page", {}).get("list", [])
    alert_levels = {"蓝色": 1, "黄色": 2, "橙色": 3, "红色": 4}
    alerts = []
    for alarm in alarms:
        title = alarm.get("title", "")
        if not title.startswith("北京市"):
            continue
        match = re.search(r"发布(.+?)预警(?:信号)?$", title)
        if not match:
            continue
        signal = match.group(1)
        level = next((name for name in alert_levels if signal.endswith(name)), "")
        alert_type = signal[: -len(level)] if level else signal
        if not level or not alert_type:
            continue
        alerts.append({
            "type": alert_type,
            "level": level,
            "rank": alert_levels[level],
            "title": title,
            "time": alarm.get("issuetime", ""),
        })
    return max(alerts, key=lambda alert: alert["rank"]) if alerts else None
