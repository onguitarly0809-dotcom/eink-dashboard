# -*- coding: utf-8 -*-
"""上游源"停摆"处理的行为测试（全程离线，网络全部打桩）。

背景（2026-11 实测）：Google News 在本机网络下时通时断，不可达时每次请求都等到
超时；默认 15 秒 × 2 次重试，再加第二轮取源重试，一轮新闻刷新 93 秒耗在超时上。
各层处理各有用例：
- httpclient：等到超时才断的尝试不再重试；
- net_breaker：连续停摆的源按 key 熔断，冷却期内直接跳过；
- news.fetch_news：第一轮超时的源不进第二轮取源；
- markets：akshare 调用有硬超时，熔断时直接走腾讯兜底且不重复计数。
"""
import contextlib
import importlib
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401

GOOGLE_URL = "https://news.google.com/rss/search?q=test"
CHINANEWS_URL = "https://www.chinanews.com.cn/rss/scroll-news.xml"
WINDOW = 1800  # config 默认：失败窗口与冷却期都是 30 分钟


class _OfflineCase(unittest.TestCase):
    """每个用例开始时重新按横版解析核心包并取当前这一代的模块对象。

    合跑时别的用例会在运行期切换变体（test_insight 在测试方法里 force_variant），
    导入期拿到的模块对象会和被测代码实际使用的脱节——曾让熔断状态写进了真实目录。"""

    def setUp(self):
        _env.force_variant("landscape")
        self.breaker = importlib.import_module("epd_dashboard.net_breaker")
        self.http_read = importlib.import_module("epd_dashboard.httpclient").http_read
        self.news = importlib.import_module("epd_dashboard.fetchers.news")
        self.markets = importlib.import_module("epd_dashboard.fetchers.markets")


class _BreakerCase(_OfflineCase):
    """熔断状态文件指到临时目录（绝不碰运营目录里的真实状态），并提供可控时钟。"""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patcher in (mock.patch.object(self.breaker, "STATE_FILE",
                                          Path(tmp.name) / "net_breaker.json"),
                        mock.patch.object(self.breaker, "_state", None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.now = 1_000_000.0
        clock = mock.patch("time.time", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)


class _Response:
    def read(self):
        return b"<rss/>"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen(plan):
    """按 plan 逐次响应的假 urlopen："ok" / "fast"（立即失败）/ "stall"（等到超时才断）。
    plan 用完后重复最后一项。返回 (假函数, 调用记录)。"""
    calls = []

    def fake(req, timeout=None):
        action = plan[min(len(calls), len(plan) - 1)]
        calls.append(action)
        if action == "ok":
            return _Response()
        if action == "stall":
            time.sleep(timeout)
            raise TimeoutError("timed out")
        raise urllib.error.URLError(ConnectionResetError("blip"))
    return fake, calls


class BreakerStateTest(_BreakerCase):
    def test_opens_after_consecutive_failures_then_probes_after_cooldown(self):
        breaker, key = self.breaker, "news.google.com"
        self.assertFalse(breaker.failure(key))
        self.assertFalse(breaker.failure(key))
        self.assertTrue(breaker.allow(key))            # 两次还没到阈值
        self.assertTrue(breaker.failure(key))          # 第 3 次：打开
        self.assertFalse(breaker.allow(key))
        self.now += WINDOW + 1                         # 冷却到期：放行探测
        self.assertTrue(breaker.allow(key))
        self.assertTrue(breaker.failure(key))          # 探测失败：立即重新打开
        self.assertFalse(breaker.allow(key))

    def test_failures_outside_window_start_over(self):
        breaker, key = self.breaker, "k"
        breaker.failure(key)
        breaker.failure(key)
        self.now += WINDOW + 1
        breaker.failure(key)
        self.assertTrue(breaker.allow(key))            # 上次失败已久，这次算第 1 次

    def test_success_resets(self):
        breaker, key = self.breaker, "k"
        breaker.failure(key)
        breaker.failure(key)
        breaker.success(key)
        breaker.failure(key)
        breaker.failure(key)
        self.assertTrue(breaker.allow(key))            # 重新累计只到 2，未打开

    def test_stale_open_entry_does_not_trip_on_a_single_failure(self):
        breaker, key = self.breaker, "k"
        for _ in range(3):
            breaker.failure(key)
        self.now += 2 * WINDOW + 1                     # 冷却期过去已久
        breaker.failure(key)
        self.assertTrue(breaker.allow(key))

    def test_state_survives_restart_and_corrupt_file_disables_breaker(self):
        breaker, key = self.breaker, "k"
        for _ in range(3):
            breaker.failure(key)
        with mock.patch.object(breaker, "_state", None):       # 新进程：重新读盘
            self.assertFalse(breaker.allow(key))
        breaker.STATE_FILE.write_text("not json", encoding="utf-8")
        with mock.patch.object(breaker, "_state", None):
            self.assertTrue(breaker.allow(key))                # 状态坏了按不熔断处理


class HttpReadRetryTest(_OfflineCase):
    def test_stall_is_not_retried(self):
        fake, calls = _urlopen(["stall"])
        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(TimeoutError):
                self.http_read(GOOGLE_URL, tries=3, timeout=0.2)
        self.assertEqual(calls, ["stall"])

    def test_fast_failure_is_retried(self):
        fake, calls = _urlopen(["fast", "ok"])
        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            self.assertEqual(self.http_read(GOOGLE_URL, tries=2, timeout=5), b"<rss/>")
        self.assertEqual(calls, ["fast", "ok"])

    def test_without_breaker_stalls_never_touch_persisted_state(self):
        # 不开 breaker 的调用方（天气/行情/额度）照旧各自失败，不落盘、不影响别的主机
        fake, calls = _urlopen(["stall"])
        with mock.patch("urllib.request.urlopen", fake), \
                mock.patch.object(self.breaker, "failure") as failure, \
                mock.patch.object(self.breaker, "success") as success:
            for _ in range(4):
                with self.assertRaises(TimeoutError):
                    self.http_read("https://api.open-meteo.com/v1/forecast", tries=2, timeout=0.2)
        failure.assert_not_called()
        success.assert_not_called()
        self.assertEqual(len(calls), 4)


class HttpReadBreakerTest(_BreakerCase):
    def _stall_google(self, times):
        fake, calls = _urlopen(["stall"])
        with mock.patch("urllib.request.urlopen", fake):
            for _ in range(times):
                with self.assertRaises(TimeoutError):
                    self.http_read(GOOGLE_URL, tries=2, timeout=0.2, breaker=True)
        return calls

    def test_skips_requests_once_open_then_probes_after_cooldown(self):
        self._stall_google(3)
        with mock.patch("urllib.request.urlopen") as request:
            with self.assertRaises(self.breaker.CircuitOpen):
                self.http_read(GOOGLE_URL, tries=2, timeout=0.2, breaker=True)
        request.assert_not_called()                    # 熔断后不再发请求
        self.now += WINDOW + 1
        fake, _ = _urlopen(["ok"])
        with mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(self.http_read(GOOGLE_URL, tries=2, timeout=5, breaker=True), b"<rss/>")
        self.assertTrue(self.breaker.allow("news.google.com"))   # 探测成功即复位

    def test_only_stalls_count_toward_the_breaker(self):
        fake, _ = _urlopen(["fast"])
        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            for _ in range(5):
                with self.assertRaises(urllib.error.URLError):
                    self.http_read(GOOGLE_URL, tries=2, timeout=5, breaker=True)
        self.assertTrue(self.breaker.allow("news.google.com"))

    def test_other_hosts_are_not_affected(self):
        self._stall_google(3)
        fake, _ = _urlopen(["ok"])
        with mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(self.http_read(CHINANEWS_URL, tries=2, timeout=5, breaker=True), b"<rss/>")
        self.assertTrue(self.breaker.allow("www.chinanews.com.cn"))


class NewsRetryRuleTest(_OfflineCase):
    def test_stalled_source_skips_second_round_but_fast_failure_is_retried(self):
        news, calls = self.news, {}

        def fake_entries(url, source_name):
            calls[url] = calls.get(url, 0) + 1
            if "news.google.com" in url:
                time.sleep(0.2)                        # 等到超时才断
                raise TimeoutError("timed out")
            if "qbitai" in url:
                raise ConnectionResetError("blip")     # 快速失败（如间歇性 SSL 中断）
            return []                                  # 其余源可达，但没给够条目

        with mock.patch.object(news, "_fetch_entries", fake_entries), \
                mock.patch.object(news, "NEWS_RSS_TIMEOUT_S", 0.2), \
                mock.patch.object(news, "fetch_model_release", lambda now=None: None), \
                mock.patch.object(news, "run_temp_task", lambda: {"off": True}), \
                contextlib.redirect_stderr(io.StringIO()):
            news.fetch_news(None, summarize=False)
        self.assertEqual(sorted(n for u, n in calls.items() if "news.google.com" in u), [1, 1, 1],
                         "三个 Google 源各只在第一轮尝试一次")
        self.assertEqual([n for u, n in calls.items() if "qbitai" in u], [2],
                         "快速失败的源照常进第二轮")


class AkshareGuardTest(_BreakerCase):
    def test_call_with_timeout_bounds_a_hung_call(self):
        released = threading.Event()

        def hung():
            released.wait(5)                           # 模拟连接假死
            return "late"

        def boom():
            raise ValueError("boom")

        began = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.markets._call_with_timeout(hung, 0.2)
        self.assertLess(time.monotonic() - began, 2)
        released.set()
        self.assertEqual(self.markets._call_with_timeout(lambda: 42, 1), 42)
        with self.assertRaises(ValueError):
            self.markets._call_with_timeout(boom, 1)
        with self.assertRaises(TimeoutError):
            self.markets._call_with_timeout(lambda: 42, 0)   # 预算已用尽：不再发起

    def test_open_breaker_skips_akshare_and_tencent_fallback_still_runs(self):
        breaker, markets = self.breaker, self.markets
        for _ in range(3):
            breaker.failure(markets.AKSHARE_BREAKER_KEY)
        tencent_payload = json.dumps({"data": {"rank_list": []}}).encode("utf-8")
        with mock.patch.object(markets, "_load_akshare", return_value=object()), \
                mock.patch.object(markets, "http_read", return_value=tencent_payload), \
                mock.patch.object(breaker, "failure", wraps=breaker.failure) as failure, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = markets.fetch_markets(None)
        failure.assert_not_called()                    # 熔断跳过不算新失败，不会越跳越久
        self.assertFalse(breaker.allow(markets.AKSHARE_BREAKER_KEY))
        self.assertEqual(result.get("raw_sectors"), [])

    def test_real_failure_counts_toward_the_breaker(self):
        breaker, markets = self.breaker, self.markets
        tencent_payload = json.dumps({"data": {"rank_list": []}}).encode("utf-8")
        with mock.patch.object(markets, "fetch_sector_with_akshare", side_effect=RuntimeError("down")), \
                mock.patch.object(markets, "http_read", return_value=tencent_payload), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            markets.fetch_markets(None)
        self.assertTrue(breaker.allow(markets.AKSHARE_BREAKER_KEY))   # 第 1 次失败：尚未打开
        state_file = breaker.STATE_FILE
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))
                         [markets.AKSHARE_BREAKER_KEY]["fails"], 1)


if __name__ == "__main__":
    unittest.main()
