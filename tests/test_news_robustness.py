# -*- coding: utf-8 -*-
"""新闻抓取的两个健壮性问题（2026-11 审计；全部用合成标题，不联网）。

- _clean_title 此前对一切标题按首个 " - " 截断：只有 Google 新闻 RSS 的标题是
  "正文 - 来源名"，其他来源"A - B"式的正经标题被拦腰截掉后半句；
- run_temp_task 编译任务正则没有保护：任务文件被手工改坏后，每一轮新闻刷新都在这里
  抛异常，整个新闻抓取随之失败。
"""
import contextlib
import importlib
import io
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401

LONG_TAIL = "合成乙丙丁戊己庚辛壬癸子丑寅卯辰巳"     # 15 字：超过"来源尾巴"规则的 12 字上限
SHORT_TAIL = "合成乙"


def _item(title, source=None):
    """按 RSS 条目的结构直接构建元素树（不经 XML 文本解析）。"""
    item = ET.Element("item")
    ET.SubElement(item, "title").text = title
    if source is not None:
        ET.SubElement(item, "source", {"url": "https://example.invalid"}).text = source
    return item


class CleanTitleTest(unittest.TestCase):
    def setUp(self):
        _env.force_variant("landscape")
        self.news = importlib.import_module("epd_dashboard.fetchers.news")

    def test_google_source_suffix_is_removed_and_the_rest_kept(self):
        clean = self.news._clean_title
        self.assertEqual(clean(_item("合成标题甲 - 合成来源乙", "合成来源乙")), "合成标题甲")
        # 正文自身的 " - " 带长副题：只剥结尾的来源，副题保留（此前按首个 " - " 截成"合成甲"）
        self.assertEqual(clean(_item(f"合成甲 - {LONG_TAIL} - 合成来源乙", "合成来源乙")),
                         f"合成甲 - {LONG_TAIL}")
        # 来源名与标题尾巴对不上：仍按最后一节剥离
        self.assertEqual(clean(_item(f"合成甲 - {LONG_TAIL} - 丙来源", "丁来源")),
                         f"合成甲 - {LONG_TAIL}")

    def test_other_feeds_keep_their_own_long_subtitles(self):
        clean = self.news._clean_title
        self.assertEqual(clean(_item(f"合成甲 - {LONG_TAIL}")), f"合成甲 - {LONG_TAIL}")
        self.assertEqual(clean(_item("合成标题-国内频道")), "合成标题")   # 没有 <source> 就不是 Google

    def test_short_tail_rule_is_unchanged(self):
        # 既有设计：结尾 "- 短尾巴（≤12字）"视为来源标记剥掉（为"标题-国内频道"而设）。
        # 这条不是本次要改的行为，写下来是让以后改动它的人是有意识的
        clean = self.news._clean_title
        self.assertEqual(clean(_item(f"新品发布 - {SHORT_TAIL}")), "新品发布")
        self.assertEqual(clean(_item("甲 - 乙 - 丙 - 丁")), "甲 - 乙 - 丙")


class TempTaskRegexTest(unittest.TestCase):
    def setUp(self):
        _env.force_variant("landscape")
        self.news = importlib.import_module("epd_dashboard.fetchers.news")

    def _run(self, task):
        err = io.StringIO()
        with mock.patch.object(self.news, "_load_temp_task", return_value=task), \
                mock.patch.object(self.news, "_read_rss") as fetch, \
                contextlib.redirect_stderr(err):
            signal = self.news.run_temp_task()
        return signal, fetch, err.getvalue()

    def test_invalid_regex_disables_the_task_instead_of_breaking_the_news_fetch(self):
        signal, fetch, err = self._run({"enabled": True, "query": "合成关键词", "match": "([unclosed"})
        self.assertEqual(signal, {"off": True})            # 调用方据此清理残留的置顶标志
        fetch.assert_not_called()                           # 规则本身坏了，不去白抓一轮
        self.assertIn("regex invalid", err)

    def test_missing_match_field_is_treated_the_same_way(self):
        for task in ({"enabled": True, "query": "合成关键词"},                 # 没有 match
                     {"enabled": True, "query": "合成关键词", "match": 123}):  # 类型不对
            with self.subTest(task=task):
                signal, fetch, err = self._run(task)
                self.assertEqual(signal, {"off": True})
                fetch.assert_not_called()
                self.assertIn("regex invalid", err)

    def test_valid_regex_still_runs(self):
        with mock.patch.object(self.news, "_load_temp_task",
                               return_value={"enabled": True, "query": "合成关键词",
                                             "match": "合成型号", "band": "ai", "badge": "价"}), \
                mock.patch.object(self.news, "_read_rss", return_value=ET.Element("rss")) as fetch, \
                contextlib.redirect_stderr(io.StringIO()):
            signal = self.news.run_temp_task()
        self.assertEqual(signal, {"clear": "ai"})          # 空结果：任务在跑但本轮无命中
        fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
