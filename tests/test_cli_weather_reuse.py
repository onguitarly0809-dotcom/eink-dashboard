# -*- coding: utf-8 -*-
"""full 模式天气缓存复用规则的行为测试（离线：抓取/落盘/渲染全部打桩）。

规则（2026-11-25）：full 渲染的不是页1 且天气缓存仍在 TTL 内时不重抓天气——天气只有
页1 用，轮播 20 分钟一轮而 TTL 30 分钟。页1 自身上屏、手动 weather、--force、
缓存已过期这四种情况照常联网。
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


class FullModeWeatherReuseTest(unittest.TestCase):
    def setUp(self):
        # 合跑时别的用例会在运行期切换变体，这里每个用例都重新按横版取当前模块对象
        _env.force_variant("landscape")
        self.cli = importlib.import_module("epd_dashboard.cli")

    def _weather_fetch_count(self, argv, fetched_at):
        """跑一遍 cli.main()，返回 fetch_weather 被调用的次数（其余外部依赖全部打桩）。"""
        cli = self.cli
        cache = {"weather": {"temperature": 1.0}, "_meta": {"weather": {"fetched_at": fetched_at}}}
        weather = mock.Mock(return_value={"temperature": 2.0})
        with mock.patch.object(cli, "load_cache", return_value=cache), \
                mock.patch.object(cli, "fetch_weather", weather), \
                mock.patch.object(cli, "fetch_glm_plan", return_value={}), \
                mock.patch.object(cli, "fetch_news", return_value={}), \
                mock.patch.object(cli, "fetch_markets", side_effect=lambda previous: previous or {}), \
                mock.patch.object(cli, "read_plans", return_value=[]), \
                mock.patch.object(cli, "save_cache"), \
                mock.patch.object(cli, "write_outputs",
                                  return_value=(Path("a.png"), Path("b.png"), Path("c.bin"), 48000)), \
                mock.patch.object(cli.R, "render_page3", return_value=object()), \
                mock.patch.object(cli.R, "render_dashboard", return_value=object()), \
                mock.patch.object(sys, "argv", ["render_dashboard.py", *argv]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main()
        return weather.call_count

    def test_fresh_cache_is_reused_when_rendering_other_pages(self):
        fresh = datetime.now().isoformat(timespec="seconds")
        self.assertEqual(self._weather_fetch_count(["--mode", "full", "--page", "3"], fresh), 0)

    def test_page1_always_fetches_when_rendered_by_full(self):
        fresh = datetime.now().isoformat(timespec="seconds")
        self.assertEqual(self._weather_fetch_count(["--mode", "full", "--page", "1"], fresh), 1)

    def test_stale_cache_is_refetched_on_any_page(self):
        stale = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        self.assertEqual(self._weather_fetch_count(["--mode", "full", "--page", "3"], stale), 1)

    def test_force_bypasses_reuse(self):
        fresh = datetime.now().isoformat(timespec="seconds")
        self.assertEqual(self._weather_fetch_count(["--mode", "full", "--page", "3", "--force"], fresh), 1)

    def test_manual_weather_command_always_fetches(self):
        fresh = datetime.now().isoformat(timespec="seconds")
        self.assertEqual(self._weather_fetch_count(["--mode", "weather", "--page", "1"], fresh), 1)

    def test_today_mode_keeps_ttl_gating(self):
        fresh = datetime.now().isoformat(timespec="seconds")
        stale = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        self.assertEqual(self._weather_fetch_count(["--mode", "today", "--page", "1"], fresh), 0)
        self.assertEqual(self._weather_fetch_count(["--mode", "today", "--page", "1"], stale), 1)


if __name__ == "__main__":
    unittest.main()
