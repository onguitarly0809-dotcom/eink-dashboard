"""极简 HTTP 读取：出口白名单校验 + 重试 + 自定义头，返回原始 bytes。"""
import time
import urllib.parse
import urllib.request

from epd_dashboard import net_breaker
from epd_dashboard.config import ALLOWED_HTTP_HOSTS

# 一次尝试耗时达到超时的这个比例仍失败，判为"停摆"（等到超时才断）
STALL_RATIO = 0.8


def http_read(url, tries=2, timeout=15, headers=None, data=None, breaker=False):
    """breaker=True 时按主机熔断：连续停摆的源在冷却期内直接抛 CircuitOpen。"""
    # 出口边界校验（SSRF 加固）：本工具只访问 config 白名单内的公网数据源
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"http_read: scheme not allowed: {parsed.scheme!r} ({url})")
    if parsed.hostname not in ALLOWED_HTTP_HOSTS:
        raise ValueError(f"http_read: host not allowed: {parsed.hostname!r} (add to ALLOWED_HTTP_HOSTS)")
    host = parsed.hostname if breaker else None
    if host and not net_breaker.allow(host):
        raise net_breaker.CircuitOpen(f"{host} 熔断中（近期连续停摆），本轮跳过")
    # data 非 None 时自动走 POST（urllib 约定），供 LLM 等需要 JSON body 的接口使用
    last = None
    stalled = False
    request_headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        request_headers.update(headers)
    for attempt in range(tries):
        began = time.monotonic()
        try:
            req = urllib.request.Request(url, data=data, headers=request_headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read()
            if host:
                net_breaker.success(host)
            return body
        except Exception as exc:
            last = exc
            stalled = time.monotonic() - began >= (timeout or 0) * STALL_RATIO
            if stalled:
                break  # 等到超时才断：重试只会再等一个完整超时，把刷新拖长一倍
            if attempt < tries - 1:
                time.sleep(1)
    if host and stalled:
        net_breaker.failure(host)
    raise last
