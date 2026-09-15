# -*- coding: utf-8 -*-
import unittest

from epd_dashboard.fetchers.insight import (
    _extract_topic,
    _normalize_text,
    _response_error,
)


class InsightFormatTest(unittest.TestCase):
    def test_preserves_complete_response(self):
        text = (
            "【主题名称】测试主题\n"
            "【所属领域】认知提升\n"
            "【核心知识】核心内容\n"
            "【背后的机制】机制内容\n"
            "【生活里的样子】场景内容\n"
            "【怎么用起来】行动内容\n"
        )
        normalized = _normalize_text(text)
        self.assertEqual(normalized.count("【主题名称】"), 1)
        self.assertEqual(_response_error(normalized, "认知提升"), "")
        self.assertEqual(_extract_topic(normalized), "测试主题")

    def test_infers_missing_topic_header(self):
        text = (
            "测试主题\n"
            "【所属领域】认知提升\n"
            "【核心知识】核心内容\n"
            "【背后的机制】机制内容\n"
            "【生活里的样子】场景内容\n"
            "【怎么用起来】行动内容\n"
        )
        normalized = _normalize_text(text)
        self.assertTrue(normalized.startswith("【主题名称】\n测试主题\n"))
        self.assertEqual(_response_error(normalized, "认知提升"), "")
        self.assertEqual(_extract_topic(normalized), "测试主题")

    def test_extracts_topic_without_display_brackets(self):
        text = (
            "【主题名称】\n"
            "【峰终定律】\n"
            "【所属领域】心理学现象\n"
            "【核心知识】核心内容\n"
            "【背后的机制】机制内容\n"
            "【生活里的样子】场景内容\n"
            "【怎么用起来】行动内容\n"
        )
        self.assertEqual(_extract_topic(text), "峰终定律")

    def test_rejects_ambiguous_missing_topic_header(self):
        text = (
            "第一行\n"
            "第二行\n"
            "【所属领域】认知提升\n"
            "【核心知识】核心内容\n"
            "【背后的机制】机制内容\n"
            "【生活里的样子】场景内容\n"
            "【怎么用起来】行动内容\n"
        )
        normalized = _normalize_text(text)
        self.assertIn("missing sections: 【主题名称】", _response_error(normalized, "认知提升"))

    def test_strips_metadata_values_for_page4(self):
        from epd_dashboard.renderers.page4_analysis import _strip_insight_metadata

        text = (
            "【主题名称】\n"
            "【峰终定律】\n"
            "【所属领域】\n"
            "心理学现象\n"
            "【核心知识】核心内容\n"
            "【背后的机制】机制内容\n"
            "【生活里的样子】场景内容\n"
            "【怎么用起来】行动内容\n"
        )
        self.assertEqual(
            _strip_insight_metadata(text),
            "【核心知识】\n核心内容\n"
            "【背后的机制】\n机制内容\n"
            "【生活里的样子】\n场景内容\n"
            "【怎么用起来】\n行动内容",
        )


if __name__ == "__main__":
    unittest.main()
