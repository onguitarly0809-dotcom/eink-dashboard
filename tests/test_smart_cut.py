# -*- coding: utf-8 -*-
"""页2摘要宽度截断（_smart_cut）的行为测试：全角1/半角0.5 计宽。

背景（2026-09-23 真机反馈）：AI 栏第二条"DeepSeek论文公开Agent训练，梁文锋署…"
被按字符数=24 误截——英文词只占半宽，屏上两行物理放得下。改按显示宽度截断后，
英文混排行不再出现多余省略号；纯中文超宽行为与旧版一致。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401

_env.force_variant("landscape")  # 上限 24 为横版口径；合跑时防被竖版(22)串扰

import unittest

from epd_dashboard.config import NEWS_SUMMARY_LINE_CHARS
from epd_dashboard.fetchers.summarize import _smart_cut, _visual_len


class SmartCutTest(unittest.TestCase):
    def test_mixed_cn_en_line_fits_and_not_cut(self):
        # 旧版按 len=26>24 截成"…署…"；新版宽度 19.5 ≤ 24，整行保留
        line = "DeepSeek论文公开Agent训练，梁文锋署名等人"
        self.assertLessEqual(_visual_len(line), NEWS_SUMMARY_LINE_CHARS)
        self.assertEqual(_smart_cut(line), line)

    def test_qwen_line_fits(self):
        line = "刘大一恒接任阿里Qwen负责人，曾主导Qwen系列研发"
        self.assertEqual(_smart_cut(line), line)

    def test_pure_cjk_over_budget_still_cut_with_ellipsis(self):
        line = "中央气象台发布暴雨黄色预警多地出现强对流天气过程需注意防范" * 1  # 27全角
        out = _smart_cut(line)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(_visual_len(out), NEWS_SUMMARY_LINE_CHARS + 1)  # 悬挂省略号本身占1宽

    def test_english_word_not_split(self):
        from epd_dashboard.fetchers.summarize import _is_wordch
        line = "OpenAI releases GPT-6 with improved reasoning ability today"
        out = _smart_cut(line)
        self.assertTrue(out.endswith("…"))
        # 切点必须在词边界：切点两侧不能同为词元字符（否则是把词切成了两半）
        cut = len(out) - 1  # 省略号位置即切点
        boundary_ok = (not _is_wordch(line[cut - 1])) or (not _is_wordch(line[cut]))
        self.assertTrue(boundary_ok,
                        f"cut mid-word: ...{line[cut-3:cut+3]!r} -> {out!r}")
        self.assertGreater(len(out), 3)

    def test_within_budget_passthrough(self):
        line = "A股收评：沪指跌1.18%"
        self.assertEqual(_smart_cut(line), line)


if __name__ == "__main__":
    unittest.main()
