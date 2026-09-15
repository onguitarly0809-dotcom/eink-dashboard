"""GLM Coding Plan 团队版额度。"""
import json
import os
import re
from datetime import datetime

from epd_dashboard.config import GLM_QUOTA_URL, GLM_USAGE_CONF
from epd_dashboard.httpclient import http_read


def _credentials():
    """GLM 凭据：环境变量优先，其次本地配置文件。"""
    values = {name: os.environ.get(name, "") for name in ("GLM_KEY", "GLM_ORG", "GLM_PROJ")}
    if all(values.values()):
        return values["GLM_KEY"], values["GLM_ORG"], values["GLM_PROJ"]
    try:
        for line in GLM_USAGE_CONF.read_text(encoding="utf-8").splitlines():
            match = re.match(r'^(GLM_KEY|GLM_ORG|GLM_PROJ)="(.*)"\s*$', line.strip())
            if match:
                values.setdefault(match.group(1), "")
                if not values[match.group(1)]:
                    values[match.group(1)] = match.group(2)
    except OSError:
        pass
    return values["GLM_KEY"], values["GLM_ORG"], values["GLM_PROJ"]


def fetch_glm_plan():
    """GLM Coding Plan 团队版额度：monitor 接口，unit=3 为 N 小时窗口、unit=6 为每周窗口，无月额度。
    返回 {"level": 档位, "quotas": {标题: {remaining,total,percent,reset}}}，与 Agent Plan 同构。
    接口的 percentage 是已用百分比，这里统一换算为剩余百分比。"""
    key, org, proj = _credentials()
    if not (key and org and proj):
        raise RuntimeError("GLM conf missing: GLM_KEY/GLM_ORG/GLM_PROJ")
    payload = json.loads(http_read(GLM_QUOTA_URL, headers={
        "Authorization": key,
        "Content-Type": "application/json",
        "bigmodel-organization": org,
        "bigmodel-project": proj,
    }))
    if payload.get("success") is False:
        raise RuntimeError(payload.get("msg") or "GLM api business error")
    limits = (payload.get("data") or {}).get("limits")
    if not isinstance(limits, list) or not limits:
        raise RuntimeError("GLM response missing data.limits")
    quotas = {}
    for item in limits:
        if item.get("unit") == 3:
            title = "5小时"
        elif item.get("unit") == 6:
            title = "周额度"
        else:
            continue
        total = item.get("usage")
        if not isinstance(total, (int, float)) or total <= 0:
            raise RuntimeError(f"GLM {title} window has no total credits")
        remaining = item.get("remaining")
        if not isinstance(remaining, (int, float)):
            remaining = max(0.0, total - (item.get("currentValue") or 0))
        reset_at = item.get("nextResetTime")
        if isinstance(reset_at, (int, float)):
            reset_dt = datetime.fromtimestamp(reset_at / 1000)
            reset_text = reset_dt.strftime("%H:%M") if title == "5小时" else reset_dt.strftime("%m/%d")
        else:
            reset_text = "-"
        quotas[title] = {
            "remaining": remaining,
            "total": total,
            "percent": round(remaining / total * 100),
            "reset": reset_text,
        }
    if not quotas:
        raise RuntimeError("GLM limits missing 5h/weekly windows")
    return {"level": (payload.get("data") or {}).get("level") or "", "quotas": quotas}
