# -*- coding: utf-8 -*-
"""页2 AI 摘要并发化的行为测试（离线：GLM 调用全部打桩）。

背景（2026-11 实测）：新标题摘要逐篇串行，13~16 篇约 30~60 秒，是 full 刷新的第二大
耗时。改并发后必须保持原有语义：展示顺序、单篇失败只损失一篇、确定性失败负缓存、
预算到点即停。
"""
import importlib
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401

TITLES = [f"标题{i}" for i in range(8)]
CONTENT = {title: ("body", "正文" * 60) for title in TITLES}


def _fake_summarizer(delay=0.15):
    """打桩 _summarize_one：标题2 确定性失败（返回 None），标题3 网络异常，其余成功。
    记录并发峰值，用来证明确实并发执行。"""
    stat = {"calls": [], "active": 0, "peak": 0}
    lock = threading.Lock()

    def fake(title, payload, key):
        with lock:
            stat["calls"].append(title)
            stat["active"] += 1
            stat["peak"] = max(stat["peak"], stat["active"])
        try:
            time.sleep(delay)
            if title == "标题2":
                return None
            if title == "标题3":
                raise OSError("transient")
            return f"摘要:{title}"
        finally:
            with lock:
                stat["active"] -= 1
    return fake, stat


class ParallelSummaryTest(unittest.TestCase):
    def setUp(self):
        # 合跑时别的用例会在运行期切换变体，这里每个用例都重新按横版取当前模块对象
        _env.force_variant("landscape")
        self.summarize = importlib.import_module("epd_dashboard.fetchers.summarize")

    def _credentials(self, value=("key", "org", "proj")):
        return mock.patch("epd_dashboard.fetchers.glm._credentials", return_value=value)

    def test_runs_concurrently_and_keeps_order_and_semantics(self):
        fake, stat = _fake_summarizer()
        cache = {}
        with self._credentials(), mock.patch.object(self.summarize, "_summarize_one", fake):
            lines, cache, done, total, fresh = self.summarize.apply_summaries(
                TITLES, CONTENT, cache, allow_new=True)
        self.assertGreaterEqual(stat["peak"], 2)       # 确实并发，不再逐篇串行
        expected = [f"摘要:{title}" for title in TITLES]
        expected[2] = "标题2"                           # 确定性失败：负缓存为原标题
        expected[3] = "标题3"                           # 网络异常：本轮原标题，不缓存
        self.assertEqual(lines, expected)               # 展示顺序仍按标题顺序
        self.assertEqual(cache["标题2"], "标题2")
        self.assertNotIn("标题3", cache)
        self.assertEqual((done, total, fresh), (6, len(TITLES), 7))

    def test_cached_and_payloadless_titles_are_not_sent(self):
        fake, stat = _fake_summarizer(delay=0)
        content = dict(CONTENT)
        del content["标题0"]
        cache = {"标题1": "旧摘要"}
        with self._credentials(), mock.patch.object(self.summarize, "_summarize_one", fake):
            lines, cache, done, total, fresh = self.summarize.apply_summaries(
                TITLES, content, cache, allow_new=True)
        self.assertNotIn("标题0", stat["calls"])        # 无正文载荷：直接负缓存
        self.assertNotIn("标题1", stat["calls"])        # 已有缓存：不重调模型
        self.assertEqual(cache["标题0"], "标题0")
        self.assertEqual(lines[1], "旧摘要")
        self.assertEqual(len(stat["calls"]), 6)

    def test_budget_exhausted_sends_nothing(self):
        fake, stat = _fake_summarizer(delay=0)
        cache = {}
        with self._credentials(), mock.patch.object(self.summarize, "_summarize_one", fake), \
                mock.patch.object(self.summarize, "NEWS_SUMMARY_BUDGET_S", -1):
            lines, cache, done, total, fresh = self.summarize.apply_summaries(
                TITLES, CONTENT, cache, allow_new=True)
        self.assertEqual(stat["calls"], [])
        self.assertEqual((lines, cache, done, total, fresh), (TITLES, {}, 0, len(TITLES), 0))

    def test_no_credentials_negative_caches_without_calls(self):
        fake, stat = _fake_summarizer(delay=0)
        cache = {}
        with self._credentials(("", "", "")), mock.patch.object(self.summarize, "_summarize_one", fake):
            lines, cache, done, total, fresh = self.summarize.apply_summaries(
                TITLES, CONTENT, cache, allow_new=True)
        self.assertEqual(stat["calls"], [])
        self.assertEqual(lines, TITLES)
        self.assertEqual(cache, {title: title for title in TITLES})

    def test_allow_new_false_is_cache_only(self):
        fake, stat = _fake_summarizer(delay=0)
        with self._credentials(), mock.patch.object(self.summarize, "_summarize_one", fake):
            lines, cache, done, total, fresh = self.summarize.apply_summaries(
                TITLES, CONTENT, {"标题0": "旧摘要"}, allow_new=False)
        self.assertEqual(stat["calls"], [])
        self.assertEqual(lines, ["旧摘要"] + TITLES[1:])
        self.assertEqual((done, total, fresh), (1, len(TITLES), 0))


if __name__ == "__main__":
    unittest.main()
