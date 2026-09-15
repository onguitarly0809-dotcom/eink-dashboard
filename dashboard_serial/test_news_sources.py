# -*- coding: utf-8 -*-
"""逐个检测新闻源可达性。用法: python test_news_sources.py"""
import time
import urllib.parse
import urllib.request
import render_dashboard as r
from epd_dashboard.config import ALLOWED_HTTP_HOSTS

# 已实测可用的国内"滚动/最新"源（备查）
CANDIDATES = {
    "人民网时政": "http://www.people.com.cn/rss/politics.xml",
    "量子位":    "https://www.qbitai.com/feed",
    "钛媒体":    "https://www.tmtpost.com/feed",
    "爱范儿":    "https://www.ifanr.com/feed",
    "少数派":    "https://sspai.com/feed",
}

def check(url, timeout=8):
    # 与运行时同一出口白名单：只允许 http(s) + config 登记过的主机
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ALLOWED_HTTP_HOSTS:
        return "FAIL (0.0s) host/scheme not allowed: %s" % url
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            head = resp.read()[:60]
            return "OK   (%.1fs) %r" % (time.time() - t0, head)
    except Exception as e:
        return "FAIL (%.1fs) %s: %s" % (time.time() - t0, type(e).__name__, e)

print("#### 当前配置源 ####")
for band, sources in r.NEWS_SOURCES.items():
    print("== %s ==" % band)
    for name, url in sources:
        print("  %-12s %s" % (name, check(url)))

print("\n#### 已实测可用的国内滚动/最新源 ####")
for name, url in CANDIDATES.items():
    print("  %-12s %s" % (name, check(url)))
