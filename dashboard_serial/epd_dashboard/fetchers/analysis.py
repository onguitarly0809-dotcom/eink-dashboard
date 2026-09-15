"""共享 GLM 报告通道与页5智谱AI走势分析时效工具。"""
import json
import sys
import time
import urllib.error
from datetime import datetime, time as dtime, timedelta

from epd_dashboard.calendar_cn import is_statutory_holiday
from epd_dashboard.config import ANALYSIS_TTL_MINUTES
from epd_dashboard.httpclient import http_read


def _request_chat(key, model, payload_base, url, timeout=60):
    """以指定模型向 url 请求一次补全，返回 (报告文本, 完整响应)。"""
    payload = dict(payload_base, model=model, max_tokens=2048)
    if str(model).startswith("glm-5"):
        payload["thinking"] = {"type": "disabled"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for attempt in (1, 2):
        try:
            raw = http_read(url, tries=1, timeout=timeout, headers=headers, data=body)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt == 1:
                print("WARN GLM 429 rate limited, retry in 10s", file=sys.stderr)
                time.sleep(10)
            else:
                raise
    data = json.loads(raw.decode("utf-8"))
    err = data.get("error")
    if err:
        raise RuntimeError(f"{err.get('code')}: {err.get('message') or err}")
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
    if not text:
        raise RuntimeError("GLM returned empty content")
    return text, data


def should_refresh(analysis, now=None, force=False):
    """force 或缓存缺失/超过 TTL 时重生成。"""
    if force:
        return True
    if not isinstance(analysis, dict) or not analysis.get("text"):
        return True
    try:
        generated_at = datetime.fromisoformat(analysis.get("generated_at"))
    except (TypeError, ValueError):
        return True
    now = now or datetime.now()
    return now - generated_at > timedelta(minutes=ANALYSIS_TTL_MINUTES)


def in_generation_window(now=None, end_time=None):
    """工作日（非法定节假日）09:31至指定收盘余量。"""
    now = now or datetime.now()
    if now.weekday() >= 5 or is_statutory_holiday(now.date()):
        return False
    return dtime(9, 31) <= now.time() <= (end_time or dtime(15, 20))
