# -*- coding: utf-8 -*-
"""GLM 请求体的思考参数（2026-11-25 用户选定 glm-5.3-flash + 思考强度 low；离线，不发请求）。"""
import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401


class ReasoningParamsTest(unittest.TestCase):
    def setUp(self):
        _env.force_variant("landscape")
        self.analysis = importlib.import_module("epd_dashboard.fetchers.analysis")
        self.config = importlib.import_module("epd_dashboard.config")

    def test_primary_model_uses_the_configured_effort(self):
        params = self.analysis._reasoning_params(self.config.ANALYSIS_MODEL)
        self.assertEqual(params, {"thinking": {"type": "enabled"},
                                  "reasoning_effort": self.config.ANALYSIS_REASONING_EFFORT})

    def test_configured_effort_is_one_of_the_values_the_api_accepts(self):
        # 取值拼错不会在本地报错，而是每一次模型调用都被接口拒绝
        self.assertIn(self.config.ANALYSIS_REASONING_EFFORT, self.analysis.VALID_REASONING_EFFORTS)

    def test_models_without_reasoning_effort_support_get_no_thinking_fields(self):
        for model in ("glm-4-flash", "glm-4.5", self.config.ANALYSIS_MODEL_FALLBACK):
            with self.subTest(model=model):
                self.assertEqual(self.analysis._reasoning_params(model), {})

    def test_thinking_can_be_switched_off_by_config_for_a_rollback(self):
        # 试用的回退路径：ANALYSIS_THINKING = "disabled" 时只发关闭思考，不带强度
        with mock.patch.object(self.analysis, "ANALYSIS_THINKING", "disabled"):
            self.assertEqual(self.analysis._reasoning_params("glm-5.3"), {"thinking": {"type": "disabled"}})

    def test_config_values_are_consistent(self):
        self.assertIn(self.config.ANALYSIS_THINKING, ("enabled", "disabled"))

    def _capture_body(self, model):
        bodies = []

        def fake_read(url, tries=2, timeout=15, headers=None, data=None, breaker=False):
            bodies.append(json.loads(data.decode("utf-8")))
            reply = {"model": "echo", "choices": [{"message": {"content": "合成回复"}}], "usage": {}}
            return json.dumps(reply).encode("utf-8")

        with mock.patch.object(self.analysis, "http_read", side_effect=fake_read):
            text, _data = self.analysis._request_chat("key", model, {"messages": [], "temperature": 0.2},
                                                      self.config.ANALYSIS_API_URL)
        self.assertEqual(text, "合成回复")
        return bodies[0]

    def test_request_body_for_the_primary_model(self):
        body = self._capture_body(self.config.ANALYSIS_MODEL)
        self.assertEqual(body["model"], "glm-5.3-flash")
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertEqual(body["max_tokens"], 2048)
        self.assertEqual(body["temperature"], 0.2)          # 调用方自己的采样参数原样保留

    def test_request_body_for_the_fallback_has_no_thinking_fields(self):
        body = self._capture_body(self.config.ANALYSIS_MODEL_FALLBACK)
        self.assertNotIn("thinking", body)
        self.assertNotIn("reasoning_effort", body)


if __name__ == "__main__":
    unittest.main()
