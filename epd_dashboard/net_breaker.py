"""上游源熔断（状态落盘、跨进程生效）：连续停摆的源在冷却期内直接跳过。

背景（2026-11 实测）：Google News 在本机网络下每次请求都等到超时，一轮新闻刷新
93 秒耗在超时上，占整轮 full 刷新的 47%；东方财富（akshare）同理每轮白等十几秒。
渲染是短命进程，熔断状态必须落盘才能跨轮次生效：BASE_DIR/net_breaker.json
（运行期文件，不入库）。

每个 key 独立计数：
- failure：失败窗口内连续失败累计到阈值即"打开"，冷却期内 allow 返回 False；
  冷却到期后的探测若再失败，直接重新打开（不必再攒满阈值）。
- success：复位清零。
熔断只是省时间的手段：状态读写失败一律按"不熔断"处理，绝不影响主链路。
"""
import json
import os
import sys
import time

from epd_dashboard.config import (
    BASE_DIR,
    BREAKER_COOLDOWN_S,
    BREAKER_FAIL_THRESHOLD,
    BREAKER_FAIL_WINDOW_S,
)

STATE_FILE = BASE_DIR / "net_breaker.json"
_state = None  # 进程内缓存：渲染进程只活几分钟，首次用到时读一次即可


class CircuitOpen(OSError):
    """熔断打开中：调用方按"本次没取到"处理（与网络不可达同类）。"""


def _load():
    global _state
    if _state is None:
        try:
            loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None
        _state = loaded if isinstance(loaded, dict) else {}
    return _state


def _save():
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    try:
        tmp.write_text(json.dumps(_state), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass  # 并发写/文件被占：丢这一次状态，后果只是少熔断一轮


def allow(key):
    """未熔断，或冷却已到期（放行一次探测）时返回 True。"""
    entry = _load().get(key)
    return not (isinstance(entry, dict) and entry.get("open_until", 0) > time.time())


def success(key):
    if _load().pop(key, None) is not None:
        _save()


def failure(key):
    """记一次失败并落盘；熔断在本次调用打开时打一行 WARN（各调用方共用，免得重复措辞）。"""
    state = _load()
    now = time.time()
    old = state.get(key) if isinstance(state.get(key), dict) else {}
    open_until = float(old.get("open_until") or 0)
    fails = int(old.get("fails") or 0)
    if 0 < open_until <= now <= open_until + BREAKER_FAIL_WINDOW_S:
        fails = max(BREAKER_FAIL_THRESHOLD, fails)  # 冷却到期后的探测失败：立即重新打开
    elif now - float(old.get("last_fail") or 0) > BREAKER_FAIL_WINDOW_S:
        fails = 1  # 上次失败已久，重新累计
    else:
        fails += 1
    opened = fails >= BREAKER_FAIL_THRESHOLD
    state[key] = {"fails": fails, "last_fail": now,
                  "open_until": now + BREAKER_COOLDOWN_S if opened else 0.0}
    _save()
    if opened:
        print(f"WARN {key} 连续失败 {BREAKER_FAIL_THRESHOLD} 次，熔断 {BREAKER_COOLDOWN_S // 60} 分钟",
              file=sys.stderr)
    return opened
