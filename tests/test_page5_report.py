# -*- coding: utf-8 -*-
"""页5 报告的生成时机、提示词与截短兜底（2026-11-25 用户选定方案 A + E；全部离线，不调 GLM）。

- 方案 E：港股时段内每次渲染页5 都重新生成，不再按 90 分钟 TTL；重写失败而沿用旧报告时
  一律标"历史"；
- 方案 A：开盘前/休市日行情接口给的是上一交易日收盘数据，提示词必须如实称呼，否则模型
  把上一交易日的走势写成"今日早盘"；
- 截短兜底：三次重试仍有小节超字数时，把超限的那一节截短来用，而不是整篇丢弃
  （当天两次重写都因"今日走势 44>40"整篇作废，屏上一直留着过期报告）。
"""
import contextlib
import importlib
import io
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401

OUTPUTS = (Path("a.png"), Path("b.png"), Path("c.bin"), 48000)
MARKETS = {
    "quotes": {
        "my_watchlist": [{"code": "hk02513", "name": "智谱", "price": 319.0, "chg": -21.14, "pct": -6.23}],
        "market_ref": [{"code": "sz399415", "pct": 1.2}, {"code": "sh000001", "pct": -0.3}],
    }
}


def _report(first_section):
    """合成一份四节报告：首节正文由 first_section 给定，其余三节都在配额内。"""
    return "\n".join([
        "【今日走势】", first_section, "",
        "【消息面归因】", "合成" * 40, "",
        "【AI板块联动】", "合成" * 30, "",
        "【政策与国际环境】", "合成" * 30,
    ])


class PromptPhaseTest(unittest.TestCase):
    """方案 A：提示词按行情所处阶段称呼价格与涨跌。"""

    def setUp(self):
        _env.force_variant("landscape")
        self.za = importlib.import_module("epd_dashboard.fetchers.zhipu_analysis")

    def _prompt(self, now):
        return self.za._build_messages(MARKETS, {}, now)[1]["content"]

    def test_during_the_session_quotes_are_todays(self):
        prompt = self._prompt(datetime(2026, 11, 25, 10, 30))
        self.assertIn("最新价 319.00 港元，今日涨跌 -21.14、涨跌幅 -6.23%。", prompt)
        self.assertIn("人工智能指数(399415)今日 +1.20%。", prompt)
        self.assertIn("上证指数今日 -0.30%。", prompt)
        self.assertIn("写一份智谱AI今日走势归因分析", prompt)
        self.assertNotIn("上一交易日", prompt)
        self.assertNotIn("注意：", prompt)

    def test_before_the_open_quotes_belong_to_the_previous_session(self):
        # 2026-11-25 08:48 的实例：盘前按键强制生成，报价 319.0/-6.23% 其实是昨日收盘
        prompt = self._prompt(datetime(2026, 11, 25, 8, 48))
        self.assertIn("港股当前未开盘", prompt)
        self.assertIn("上一交易日收盘价 319.00 港元，上一交易日涨跌 -21.14、涨跌幅 -6.23%。", prompt)
        self.assertIn("人工智能指数(399415)上一交易日 +1.20%。", prompt)
        self.assertIn("写一份智谱AI上一交易日走势归因回顾", prompt)
        self.assertIn("不要写成今日或早盘行情", prompt)
        self.assertNotIn("今日走势归因分析", prompt)
        self.assertNotIn("最新价", prompt)

    def test_after_the_close_quotes_are_todays_close(self):
        prompt = self._prompt(datetime(2026, 11, 25, 17, 0))
        self.assertIn("港股今日已收盘", prompt)
        self.assertIn("今日收盘价 319.00 港元", prompt)
        self.assertIn("写一份智谱AI今日走势归因分析", prompt)

    def test_lunch_break_is_still_todays_data(self):
        prompt = self._prompt(datetime(2026, 11, 25, 12, 30))
        self.assertIn("午间休市", prompt)
        self.assertIn("上午收市数据", prompt)
        self.assertIn("最新价 319.00 港元", prompt)

    def test_non_trading_days_are_treated_as_previous_session(self):
        for now in (datetime(2026, 11, 28, 10, 30), datetime(2026, 10, 1, 10, 30)):   # 周六 / 国庆
            with self.subTest(now=now):
                self.assertEqual(self.za.quote_phase(now), "prev_session")

    def test_phase_boundaries(self):
        phase = self.za.quote_phase

        def wednesday(hour, minute):
            return datetime(2026, 11, 25, hour, minute)

        self.assertEqual(phase(wednesday(9, 30)), "prev_session")
        self.assertEqual(phase(wednesday(9, 31)), "trading")
        self.assertEqual(phase(wednesday(16, 5)), "trading")
        self.assertEqual(phase(wednesday(16, 6)), "closed_today")


class ShortenTest(unittest.TestCase):
    def setUp(self):
        _env.force_variant("landscape")
        self.za = importlib.import_module("epd_dashboard.fetchers.zhipu_analysis")

    def test_cuts_at_a_sentence_end_when_possible(self):
        shorten = self.za._shorten
        self.assertEqual(shorten("合成句子一。合成句子二。合成句子三。", 10), "合成句子一。")
        self.assertEqual(shorten("合成句子一。", 10), "合成句子一。")              # 不超限原样返回

    def test_cuts_at_a_clause_and_closes_the_sentence(self):
        self.assertEqual(self.za._shorten("甲" * 6 + "，" + "乙" * 8, 10), "甲" * 6 + "。")

    def test_hard_cut_marks_the_omission_and_respects_the_quota(self):
        fitted = self.za._shorten("合" * 44, 40)
        self.assertEqual(fitted, "合" * 39 + "…")
        self.assertEqual(self.za._visible_length(fitted), 40)

    def test_every_branch_stays_within_the_quota(self):
        samples = ["，".join("句" * n for n in (3, 5, 8, 13)), "。".join("段" * n for n in (7, 9, 4)),
                   "、" * 30 + "字", "短句。" * 12, "无标点" * 20]
        for sample in samples:
            for quota in (10, 40, 70):
                with self.subTest(sample=sample[:8], quota=quota):
                    self.assertLessEqual(self.za._visible_length(self.za._shorten(sample, quota)), quota)

    def test_only_the_listed_section_is_rewritten(self):
        text = _report("合" * 44)
        fitted = self.za._shorten_sections(text, {"今日走势": 40})
        before, after = text.splitlines(), fitted.splitlines()
        self.assertEqual(after[0], before[0])                    # 标题行
        self.assertEqual(after[1], "合" * 39 + "…")
        self.assertEqual(after[2:], before[2:])                  # 空行与其余三节逐行不变

    def test_salvage_picks_the_least_over_limit_attempt(self):
        best = self.za._best_salvage([(_report("合" * 55), {"n": 55}), (_report("合" * 44), {"n": 44})])
        fitted, data, error = best
        self.assertEqual(data, {"n": 44})
        self.assertEqual(self.za._response_error(fitted), "")
        self.assertTrue(fitted.splitlines()[1].endswith("…"))

    def test_salvage_refuses_reports_it_cannot_repair(self):
        missing = _report("合" * 44).replace("【AI板块联动】", "【别的标题】")
        markdown = _report("合" * 44) + "\n**加粗**"
        for attempts in ([], [(missing, {})], [(markdown, {})], [(_report("合" * 30), {})]):
            with self.subTest(attempts=len(attempts)):
                self.assertIsNone(self.za._best_salvage(attempts))

    def test_generation_returns_the_shortened_report_instead_of_failing(self):
        za = self.za
        replies = [(_report("合" * n), {"model": "glm-x", "usage": {}}) for n in (44, 55, 45)]
        with mock.patch.object(za, "_credentials", return_value=("key", "org", "proj")), \
                mock.patch.object(za, "_headlines", return_value={}), \
                mock.patch.object(za, "_request_chat", side_effect=replies), \
                mock.patch.object(za, "_find_quote", return_value=None), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            result = za.fetch_zhipu_analysis({}, now=datetime(2026, 11, 25, 13, 43))
        self.assertEqual(za._response_error(result["text"]), "")
        self.assertEqual(result["text"].splitlines()[1], "合" * 39 + "…")   # 取超出最少的 44 字那份
        # 截短只动超限的那一节：其余三节必须原样在（首版实现把它们整节清空过）。
        # 分节时节后的空行归在上一节，比较时只看非空行
        sections = za._split_sections(result["text"])
        bodies = {name: [line for line in lines if line.strip()] for name, lines in sections.items()}
        self.assertEqual(bodies["消息面归因"], ["合成" * 40])
        self.assertEqual(bodies["AI板块联动"], ["合成" * 30])
        self.assertEqual(bodies["政策与国际环境"], ["合成" * 30])
        self.assertTrue(result["shortened"])
        self.assertFalse(result["stale"])
        self.assertIn("still over quota after 3 attempts", err.getvalue())

    def test_generation_still_fails_when_a_section_is_missing(self):
        za = self.za
        broken = _report("合" * 44).replace("【政策与国际环境】", "【其它】")
        replies = [(broken, {"model": "glm-x", "usage": {}})] * za.STOCK_RETRY_COUNT
        with mock.patch.object(za, "_credentials", return_value=("key", "org", "proj")), \
                mock.patch.object(za, "_headlines", return_value={}), \
                mock.patch.object(za, "_request_chat", side_effect=replies), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(RuntimeError):
                za.fetch_zhipu_analysis({}, now=datetime(2026, 11, 25, 13, 43))


class RegenerationTimingTest(unittest.TestCase):
    """方案 E：什么时候重新生成页5 报告。"""

    def setUp(self):
        _env.force_variant("landscape")
        self.cli = importlib.import_module("epd_dashboard.cli")

    def _report(self, age_minutes):
        generated = datetime.now() - timedelta(minutes=age_minutes)
        return {"text": "合成旧报告", "generated_at": generated.isoformat(timespec="seconds"), "stale": False}

    def _run(self, argv, cached, in_session, generate):
        """跑一遍 cli.main()（markets 模式：不触发页4 的生成与归档），返回最终的缓存对象。
        抓取/生成/渲染/落盘全部打桩；generate 作为 fetch_zhipu_analysis 的返回来源。"""
        cli = self.cli
        cache = {"stock_analysis": cached}
        with mock.patch.object(cli, "load_cache", return_value=cache), \
                mock.patch.object(cli, "fetch_markets", side_effect=lambda previous: previous or {}), \
                mock.patch.object(cli, "fetch_intraday", return_value={}), \
                mock.patch.object(cli, "in_generation_window", return_value=in_session), \
                mock.patch.object(cli, "fetch_zhipu_analysis", side_effect=generate), \
                mock.patch.object(cli, "read_plans", return_value=[]), \
                mock.patch.object(cli, "save_cache"), \
                mock.patch.object(cli, "write_outputs", return_value=OUTPUTS), \
                mock.patch.object(cli.R, "render_page5", return_value=object()), \
                mock.patch.object(cli.R, "render_page3", return_value=object()), \
                mock.patch.object(sys, "argv", ["render_dashboard.py", *argv]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main()
        return cache

    NEW = {"text": "合成新报告", "generated_at": datetime.now().isoformat(timespec="seconds"), "stale": False}

    def test_in_session_every_visit_regenerates_even_a_one_minute_old_report(self):
        generate = mock.Mock(return_value=dict(self.NEW))
        cache = self._run(["--mode", "markets", "--page", "5"], self._report(1), True, generate)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(cache["stock_analysis"]["text"], "合成新报告")

    def test_out_of_session_the_report_is_kept(self):
        for age, stale in ((30, False), (150, True)):
            with self.subTest(age=age):
                generate = mock.Mock()
                cache = self._run(["--mode", "markets", "--page", "5"], self._report(age), False, generate)
                generate.assert_not_called()
                self.assertEqual(cache["stock_analysis"]["text"], "合成旧报告")
                self.assertIs(cache["stock_analysis"]["stale"], stale)      # 超过 90 分钟才标"历史"

    def test_failed_regeneration_marks_the_kept_report_stale(self):
        # 时段内重写失败：旧报告再新也要标"历史"——旁边是刚刷新的分时图
        generate = mock.Mock(side_effect=RuntimeError("1301: 合成拦截"))
        cache = self._run(["--mode", "markets", "--page", "5"], self._report(5), True, generate)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(cache["stock_analysis"], dict(self._report(5), stale=True))

    def test_forced_refresh_regenerates_outside_the_session(self):
        generate = mock.Mock(return_value=dict(self.NEW))
        cache = self._run(["--mode", "markets", "--page", "5", "--force"], self._report(1), False, generate)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(cache["stock_analysis"]["text"], "合成新报告")

    def test_other_pages_never_touch_the_report(self):
        generate = mock.Mock()
        self._run(["--mode", "markets", "--page", "3"], self._report(1), True, generate)
        generate.assert_not_called()


class HelpTextTest(unittest.TestCase):
    def test_placeholder_note_describes_the_new_rule(self):
        for variant in ("landscape", "portrait"):
            with self.subTest(variant=variant):
                _env.force_variant(variant)
                module = importlib.import_module(f"epd_dashboard.renderers.{variant}.page5_zhipu")
                with mock.patch.object(module, "render_report_page", return_value=object()) as page:
                    module.render_page5({}, None, None, None)
                passed = list(page.call_args.args) + list(page.call_args.kwargs.values())
                notes = next(arg for arg in passed
                             if isinstance(arg, tuple) and any("自动生成" in str(item) for item in arg))
                self.assertIn("每次显示本页都重新生成", " ".join(notes))
                self.assertNotIn("90分钟", " ".join(notes))


if __name__ == "__main__":
    unittest.main()
