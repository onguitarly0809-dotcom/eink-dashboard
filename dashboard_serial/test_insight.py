# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from epd_dashboard.fetchers.insight import (
    _extract_topic,
    _normalize_text,
    _response_error,
)
from epd_dashboard.obsidian_export import (
    _safe_filename,
    archive_insight,
    build_insight_markdown,
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


class InsightArchiveTest(unittest.TestCase):
    def _sample(self):
        return {
            "kind": "insight",
            "domain": "心理学现象",
            "topic": "峰终定律",
            "text": (
                "【主题名称】\n峰终定律\n【所属领域】\n心理学现象\n"
                "【核心知识】核心内容\n【背后的机制】机制内容\n"
                "【生活里的样子】场景内容\n【怎么用起来】行动内容"
            ),
            "model": "glm-5.3",
            "generated_at": "2026-09-17T09:35:00",
        }

    def test_builds_markdown_with_frontmatter_and_sections(self):
        md = build_insight_markdown(self._sample())
        self.assertIn("created: 2026-09-17T09:35:00", md)
        self.assertIn("# 峰终定律", md)
        self.assertIn("## 核心知识", md)
        self.assertIn("## 怎么用起来", md)
        self.assertIn("行动内容", md)
        self.assertNotIn("【", md)  # 六段【】小节标题全部转为 markdown 结构

    def test_archive_writes_dated_file_and_dedups_on_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = archive_insight(self._sample(), archive_dir=Path(tmp))
            self.assertIsNotNone(out)
            self.assertEqual(out.name, "2026-09-17 峰终定律.md")
            self.assertTrue(out.exists())
            self.assertIn("# 峰终定律", out.read_text(encoding="utf-8"))
            # 同日同主题重生成：不覆盖已有笔记，追加时间后缀
            out2 = archive_insight(self._sample(), archive_dir=Path(tmp))
            self.assertEqual(out2.name, "2026-09-17 峰终定律 0935.md")
            # 非 insight 内容（页5 stock_analysis 等）不归档；写盘失败不影响主链路返回 None
            self.assertIsNone(archive_insight({"kind": "psychology"}, archive_dir=Path(tmp)))

    def test_safe_filename_strips_windows_invalid_chars(self):
        self.assertEqual(_safe_filename('a/b\\c:d*e?f"g<h>i|j'), "a b c d e f g h i j")
        self.assertEqual(_safe_filename("  结尾点.  "), "结尾点")


if __name__ == "__main__":
    unittest.main()
