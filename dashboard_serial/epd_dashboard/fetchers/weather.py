"""天气：open-meteo 实况 + 中央气象台预警（仅北京）。"""
import json
import re
from datetime import datetime

from epd_dashboard.config import WEATHER_ALERT_URL, WEATHER_URL
from epd_dashboard.httpclient import http_read


def fetch_weather():
    payload = json.loads(http_read(WEATHER_URL))
    current = payload["current"]
    daily = payload["daily"]
    code = int(current.get("weather_code", 3))
    descriptions = {
        0: "晴", 1: "晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾",
        51: "小雨", 53: "小雨", 55: "小雨", 61: "小雨", 63: "中雨", 65: "大雨",
        71: "小雪", 73: "中雪", 75: "大雪", 80: "阵雨", 81: "阵雨", 82: "强阵雨",
        95: "雷阵雨", 96: "雷阵雨", 99: "强雷阵雨",
    }
    weather = {
        "temperature": current["temperature_2m"],
        "humidity": current["relative_humidity_2m"],
        "precipitation": current.get("precipitation_probability", 0),
        "wind": current["wind_speed_10m"],
        "uv_index": current.get("uv_index", 0),
        "description": descriptions.get(code, "多云"),
        "high": daily["temperature_2m_max"][0],
        "low": daily["temperature_2m_min"][0],
        "updated": datetime.fromisoformat(current["time"]).strftime("%H:%M"),
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
