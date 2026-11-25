# -*- coding: utf-8 -*-
"""调度链兜底行为测试（离线：抓取/设备/串口/落盘/渲染全部打桩）。

覆盖 2026-11 审计出的几类"轮播卡死 / 白跑一轮"：
- 设备拔出时 --push 在抓数据前就以退出码 4 结束，不白跑、不耗 GLM 额度、不写 Obsidian；
- 页4 洞察生成失败时沿用上一篇并标"历史"，不再抛错把轮播冻在页4；
- 页5 分析被 1301（内容安全）拦截时去掉新闻标题重试一次；
- 串口推送失败后的重试次数与间隔（间隔保持 2 秒）。
"""
import argparse
import contextlib
import importlib
import io
import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401

OUTPUTS = (Path("a.png"), Path("b.png"), Path("c.bin"), 48000)


class _CliCase(unittest.TestCase):
    def setUp(self):
        # 合跑时别的用例会在运行期切换变体，这里每个用例都重新按横版取当前模块对象
        _env.force_variant("landscape")
        self.cli = importlib.import_module("epd_dashboard.cli")


class DevicePreFlightTest(_CliCase):
    """--push 前的设备在线预检。"""

    def test_forced_offline_exits_with_code_4_before_fetching_anything(self):
        cli = self.cli
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"EPD_FORCE_OFFLINE": "1"}), \
                mock.patch.object(cli, "load_cache") as load, \
                mock.patch.object(cli, "fetch_weather") as weather, \
                mock.patch.object(cli, "fetch_insight") as insight, \
                mock.patch.object(cli, "save_cache") as save, \
                mock.patch.object(sys, "argv", ["render_dashboard.py", "--mode", "full",
                                                "--page", "4", "--push"]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as stop:
                cli.main()
        self.assertEqual(stop.exception.code, cli.DEVICE_OFFLINE_EXIT)
        self.assertEqual(stop.exception.code, 4)                # 与 ops/control.ps1 的约定
        self.assertEqual(json.loads(out.getvalue()),
                         {"mode": "full", "page": "4", "skipped": "device-offline"})
        for stub in (load, weather, insight, save):
            stub.assert_not_called()

    def test_device_is_detected_by_port_enumeration_only(self):
        push = importlib.import_module("epd_dashboard.push")
        args = argparse.Namespace(push=True, port=None)
        with mock.patch.object(push, "_resolve_port", return_value="COM5") as resolve, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(self.cli._device_online(args))
        resolve.assert_called_once()                            # 只枚举串口：不开端口、不发 PING
        with mock.patch.object(push, "_resolve_port",
                               side_effect=push.DeviceUnavailable("设备未连接")), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertFalse(self.cli._device_online(args))
        self.assertIn("设备未连接", err.getvalue())

    def test_without_push_the_device_is_never_consulted(self):
        cli = self.cli
        cache = {"weather": {"temperature": 1.0}}
        with mock.patch.object(cli, "_device_online",
                               side_effect=AssertionError("不推送时不该查设备")), \
                mock.patch.object(cli, "load_cache", return_value=cache), \
                mock.patch.object(cli, "fetch_weather", return_value={"temperature": 2.0}), \
                mock.patch.object(cli, "fetch_glm_plan", return_value={}), \
                mock.patch.object(cli, "fetch_news", return_value={}), \
                mock.patch.object(cli, "fetch_markets", side_effect=lambda previous: previous or {}), \
                mock.patch.object(cli, "read_plans", return_value=[]), \
                mock.patch.object(cli, "save_cache"), \
                mock.patch.object(cli, "write_outputs", return_value=OUTPUTS), \
                mock.patch.object(cli.R, "render_dashboard", return_value=object()), \
                mock.patch.object(sys, "argv", ["render_dashboard.py", "--mode", "weather", "--page", "1"]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main()                                          # 仅预览：设备拔着也照常出图


class InsightFallbackTest(_CliCase):
    """页4 洞察生成失败：沿用上一篇并标"历史"，页面照常出图、页状态照常提交。"""

    PREVIOUS = {"text": "上一篇洞察正文", "topic": "合成主题", "domain": "科技",
                "model": "glm-x", "updated": "10:50", "stale": False}

    def _run(self, cached, generate):
        cli = self.cli
        cache = {"analysis": cached}
        saved, rendered, err = {}, {}, io.StringIO()

        def render(analysis):
            rendered["analysis"] = analysis
            return object()

        with mock.patch.object(cli, "load_cache", return_value=cache), \
                mock.patch.object(cli, "fetch_insight", side_effect=generate), \
                mock.patch.object(cli, "archive_insight") as archive, \
                mock.patch.object(cli, "save_cache", side_effect=saved.update), \
                mock.patch.object(cli, "write_outputs", return_value=OUTPUTS), \
                mock.patch.object(cli.R, "render_page4", side_effect=render), \
                mock.patch.object(sys, "argv", ["render_dashboard.py", "--mode", "insight", "--page", "4"]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            cli.main()
        return saved, rendered["analysis"], archive, err.getvalue()

    def test_generation_failure_keeps_the_previous_insight_marked_stale(self):
        previous = dict(self.PREVIOUS)
        saved, rendered, archive, err = self._run(previous, RuntimeError("GLM 502"))
        self.assertEqual(saved["analysis"], dict(previous, stale=True))
        self.assertIs(rendered, saved["analysis"])
        self.assertFalse(previous["stale"])                     # 缓存里的旧对象不被原地改写
        archive.assert_not_called()                              # 旧洞察不重复归档进 Obsidian
        self.assertIn("WARN insight generation failed", err)
        self.assertNotIn("ERROR insight generation failed", err)  # 降级为 WARN，不再是致命错误

    def test_failure_without_any_cached_insight_renders_the_placeholder(self):
        saved, rendered, archive, _ = self._run(None, RuntimeError("GLM 502"))
        self.assertIsNone(saved["analysis"])
        self.assertIsNone(rendered)
        archive.assert_not_called()

    def test_successful_generation_still_replaces_and_archives(self):
        fresh = dict(self.PREVIOUS, text="新洞察", stale=False)
        saved, rendered, archive, _ = self._run(dict(self.PREVIOUS, stale=True),
                                                mock.Mock(return_value=fresh))
        self.assertIs(saved["analysis"], fresh)
        self.assertFalse(saved["analysis"]["stale"])             # 上一次失败留下的"历史"标记被清掉
        self.assertIs(rendered, fresh)
        archive.assert_called_once()


class StockAnalysisContentFilterTest(unittest.TestCase):
    """页5 分析被 1301 拦截：去掉新闻标题、只留行情数据重试一次。"""

    HEADLINES = {"AI板块": ["合成标题甲"]}
    NOW = datetime(2026, 11, 25, 11, 0)

    def setUp(self):
        _env.force_variant("landscape")
        self.za = importlib.import_module("epd_dashboard.fetchers.zhipu_analysis")
        self.err = io.StringIO()

    @staticmethod
    def _ask(responses):
        """_request_chat 的桩：字符串 = 成功回复正文，其余 = 抛出的异常。"""
        replies = [(text, {"model": "glm-x", "usage": {}}) if isinstance(text, str) else text
                   for text in responses]
        return mock.Mock(side_effect=replies)

    def _patched(self, ask, headlines=HEADLINES):
        """打桩凭据/新闻标题/请求/校验；ask 是 _request_chat 的桩。返回可 with 的栈。"""
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(
            self.za, "_credentials", return_value=("key", "org", "proj")))
        stack.enter_context(mock.patch.object(self.za, "_headlines", return_value=headlines))
        stack.enter_context(mock.patch.object(self.za, "_request_chat", ask))
        stack.enter_context(mock.patch.object(self.za, "_response_error", return_value=None))
        stack.enter_context(mock.patch.object(self.za, "_find_quote", return_value=None))
        stack.enter_context(contextlib.redirect_stderr(self.err))
        return stack

    def _headline_in(self, call):
        return "合成标题甲" in json.dumps(call.args[2]["messages"], ensure_ascii=False)

    def test_content_rejection_retries_without_news_headlines(self):
        ask = self._ask([RuntimeError("1301: 内容安全"), "正文"])
        with self._patched(ask):
            result = self.za.fetch_zhipu_analysis({}, now=self.NOW)
        self.assertEqual(result["text"], "正文")
        self.assertEqual(ask.call_count, 2)
        self.assertTrue(self._headline_in(ask.call_args_list[0]))
        self.assertFalse(self._headline_in(ask.call_args_list[1]))
        self.assertIn("1301", self.err.getvalue())

    def test_second_rejection_propagates_so_the_caller_keeps_the_old_report(self):
        ask = self._ask([RuntimeError("1301: 内容安全"), RuntimeError("1301: 仍然拦截")])
        with self._patched(ask), self.assertRaises(RuntimeError):
            self.za.fetch_zhipu_analysis({}, now=self.NOW)
        self.assertEqual(ask.call_count, 2)                     # 只去掉一次标题，不会无限重试

    def test_rejection_without_headlines_is_not_retried(self):
        ask = self._ask([RuntimeError("1301: 内容安全"), "不该被用到"])
        with self._patched(ask, headlines={}), self.assertRaises(RuntimeError):
            self.za.fetch_zhipu_analysis({}, now=self.NOW)
        ask.assert_called_once()

    def test_other_errors_are_not_mistaken_for_content_rejection(self):
        ask = self._ask([RuntimeError("500: 服务端错误"), "不该被用到"])
        with self._patched(ask), self.assertRaises(RuntimeError):
            self.za.fetch_zhipu_analysis({}, now=self.NOW)
        ask.assert_called_once()

    def test_quota_retries_are_not_consumed_by_the_headline_retry(self):
        # 1301 一次，之后配额连续超限 (STOCK_RETRY_COUNT - 1) 次再成功：配额重试额度一次没少
        quota_rounds = self.za.STOCK_RETRY_COUNT
        errors = ["超限"] * (quota_rounds - 1) + [None]
        ask = self._ask([RuntimeError("1301: 内容安全")] + ["正文"] * quota_rounds)
        with self._patched(ask), \
                mock.patch.object(self.za, "_response_error", side_effect=errors):
            result = self.za.fetch_zhipu_analysis({}, now=self.NOW)
        self.assertEqual(result["text"], "正文")
        self.assertEqual(ask.call_count, quota_rounds + 1)


class SerialRetryTest(unittest.TestCase):
    """串口推送失败后的重试（间隔保持 2 秒：打开串口会让 ESP8266 复位，不必等过固件接收超时）。"""

    def setUp(self):
        _env.force_variant("landscape")
        self.push = importlib.import_module("epd_dashboard.push")

    def test_transient_failure_is_retried_after_the_delay(self):
        push = self.push
        with mock.patch.object(push, "push", side_effect=[push.PushError("ACK timeout"), None]) as attempt, \
                mock.patch.object(push.time, "sleep") as sleep, \
                contextlib.redirect_stdout(io.StringIO()):
            push.push_with_retry(binary_path="x.bin")
        self.assertEqual(attempt.call_count, 2)
        sleep.assert_called_once_with(2.0)

    def test_retries_are_exhausted_then_the_last_error_is_raised(self):
        push = self.push
        with mock.patch.object(push, "push", side_effect=push.PushError("No PONG")) as attempt, \
                mock.patch.object(push.time, "sleep") as sleep, \
                mock.patch.object(push, "EPD_SERIAL_PORT", "COM5"), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(push.PushError, "after 3 attempts"):
                push.push_with_retry(binary_path="x.bin")
        self.assertEqual(attempt.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_unplugged_device_is_not_retried(self):
        push = self.push
        with mock.patch.object(push, "push",
                               side_effect=push.DeviceUnavailable("设备未连接")) as attempt, \
                mock.patch.object(push.time, "sleep") as sleep, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(push.DeviceUnavailable):
                push.push_with_retry(binary_path="x.bin")
        attempt.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
