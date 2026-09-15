"""极简 HTTP 读取：出口白名单校验 + 重试 + 自定义头，返回原始 bytes。"""
import time
import urllib.parse
import urllib.request

from epd_dashboard.config import ALLOWED_HTTP_HOSTS


def http_read(url, tries=2, timeout=15, headers=None, data=None):
    # 出口边界校验（SSRF 加固）：本工具只访问 config 白名单内的公网数据源
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"http_read: scheme not allowed: {parsed.scheme!r} ({url})")
    if parsed.hostname not in ALLOWED_HTTP_HOSTS:
        raise ValueError(f"http_read: host not allowed: {parsed.hostname!r} (add to ALLOWED_HTTP_HOSTS)")
    # data 非 None 时自动走 POST（urllib 约定），供 LLM 等需要 JSON body 的接口使用
    last = None
    request_headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        request_headers.update(headers)
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=request_headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last = exc
            if attempt < tries - 1:
                time.sleep(1)
    raise last
