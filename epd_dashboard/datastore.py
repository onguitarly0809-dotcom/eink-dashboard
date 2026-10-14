"""本地数据缓存（dashboard_data.json）与工作计划（plans.txt）的读写。"""
import json
import os
from datetime import datetime, timedelta

from epd_dashboard.config import DATA_CACHE_FILE

EMPTY_CACHE = {"weather": None, "glm": None, "plans": None, "news": None, "markets": None}


def load_cache():
    if DATA_CACHE_FILE.exists():
        try:
            cache = json.loads(DATA_CACHE_FILE.read_text(encoding="utf-8"))
            cache.pop("quotas", None)  # 火山方舟已退订，丢弃历史缓存中的残留键
            return cache
        except Exception:
            pass
    return dict(EMPTY_CACHE)


def save_cache(cache):
    # 先写临时文件再原子替换，并发的读方（web/控制台）不会读到半截 JSON
    tmp = DATA_CACHE_FILE.with_name(DATA_CACHE_FILE.name + ".tmp")
    tmp.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, DATA_CACHE_FILE)


def is_fresh(cache, module, ttl_minutes, now=None):
    """该模块缓存是否仍在 TTL 内（平行元数据 _meta，不侵入数据结构）。"""
    fetched = ((cache.get("_meta") or {}).get(module) or {}).get("fetched_at")
    if not fetched:
        return False
    try:
        fetched_at = datetime.fromisoformat(fetched)
    except ValueError:
        return False
    age = (now or datetime.now()) - fetched_at
    if age < timedelta(0):
        return False
    return age < timedelta(minutes=ttl_minutes)


def mark_fetched(cache, module, now=None):
    meta = cache.setdefault("_meta", {})
    meta[module] = {"fetched_at": (now or datetime.now()).isoformat(timespec="seconds")}


def read_plans(plans_path):
    return [line.strip() for line in plans_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
