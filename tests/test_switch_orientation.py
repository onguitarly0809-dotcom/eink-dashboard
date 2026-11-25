# -*- coding: utf-8 -*-
"""switch_orientation.py 的行为测试（计划任务、进程操作、自启目录全部打桩，不碰真实系统）。

2026-11 审计：切换脚本不处理邮件监控——切到竖版后横版的邮件监控仍在跑，新邮件/锁屏时
往屏上推横版画面；写自启脚本用 ascii + 静默丢字符，路径含中文时会写出坏脚本。
"""
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
DAEMONS = ("epd_refresh_hidden.vbs", "dashboard_web.py", "dashboard_hotkeys.py")


def _load_script():
    spec = importlib.util.spec_from_file_location("switch_orientation_under_test",
                                                  REPO / "switch_orientation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SwitchOrientationTest(unittest.TestCase):
    def setUp(self):
        self.sw = _load_script()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.root = self.home / "repo"
        for variant in ("dashboard_serial_landscape", "dashboard_serial"):
            folder = self.root / variant
            folder.mkdir(parents=True)
            for name in DAEMONS:
                (folder / name).write_text("", encoding="utf-8")
        startup = self.home / "Startup"
        startup.mkdir()
        self.startup_vbs = startup / "EPD_Web_Start.vbs"
        self.monitor_vbs = startup / "EPD_Mail_Monitor_Start.vbs"
        self.monitor_vbs.write_text("", encoding="utf-8")

        self.commands, self.launched = [], []
        self._patch(mock.patch.object(self.sw, "ROOT", self.root))
        self._patch(mock.patch.object(self.sw, "STARTUP_VBS", self.startup_vbs))
        self._patch(mock.patch.object(self.sw, "MAIL_MONITOR_VBS", self.monitor_vbs))
        self._patch(mock.patch.object(self.sw, "find_pythonw", return_value="C:/py/pythonw.exe"))
        self._patch(mock.patch.object(self.sw, "launch_hidden", side_effect=self.launched.append))
        self._patch(mock.patch.object(self.sw.subprocess, "run", side_effect=self._fake_run))
        self.sleep = self._patch(mock.patch.object(self.sw.time, "sleep"))
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def _patch(self, patcher):
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def _fake_run(self, cmd, **_kwargs):
        """wmic 报出三个进程（含切换脚本自己），其余外部命令一律成功。"""
        self.commands.append(list(cmd))
        stdout = ""
        if cmd[0] == "wmic":
            stdout = ("pythonw.exe x dashboard_web.py  4242\r\n"
                      "python.exe x mail_monitor.py  4243\r\n"
                      f"python.exe x switch  {os.getpid()}\r\n\r\n")
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    def _switch(self, target):
        with mock.patch.object(sys, "argv", ["switch_orientation.py", target]):
            self.sw.main()

    def _killed_pids(self):
        return {int(cmd[cmd.index("/PID") + 1]) for cmd in self.commands if cmd[0] == "taskkill"}

    def _startup_text(self):
        return self.startup_vbs.read_bytes().decode("mbcs")

    def test_switching_to_landscape_restarts_every_daemon(self):
        self._switch("landscape")
        self.assertEqual((self.root / "ACTIVE_ORIENTATION.txt").read_text(encoding="ascii"), "landscape")
        schtasks = next(cmd for cmd in self.commands if cmd[0] == "schtasks")
        self.assertTrue(schtasks[schtasks.index("/TR") + 1].endswith(
            'dashboard_serial_landscape\\epd_refresh_hidden.vbs"'))
        query = next(cmd for cmd in self.commands if cmd[0] == "wmic")
        self.assertTrue(any("mail_monitor.py" in part for part in query))
        self.assertEqual(self._killed_pids(), {4242, 4243})            # 自己不在其中
        self.sleep.assert_called_once_with(1.5)                          # 等旧进程退干净再拉新的
        self.assertEqual(self.launched, [self.startup_vbs, self.monitor_vbs])
        text = self._startup_text()
        self.assertIn("dashboard_serial_landscape\\dashboard_web.py", text)
        self.assertIn("dashboard_serial_landscape\\dashboard_hotkeys.py", text)
        self.assertNotIn("dashboard_serial\\", text.replace("dashboard_serial_landscape\\", ""))

    def test_switching_to_portrait_stops_the_monitor_without_restarting_it(self):
        self._switch("portrait")
        self.assertEqual((self.root / "ACTIVE_ORIENTATION.txt").read_text(encoding="ascii"), "portrait")
        self.assertEqual(self._killed_pids(), {4242, 4243})
        self.assertEqual(self.launched, [self.startup_vbs])
        text = self._startup_text()
        self.assertIn("dashboard_serial\\dashboard_web.py", text)
        self.assertIn("dashboard_serial\\dashboard_hotkeys.py", text)
        self.assertNotIn("dashboard_serial_landscape", text)

    def test_startup_script_keeps_non_ascii_paths(self):
        self.sw.write_startup_vbs("C:/py/pythonw.exe", self.home / "中文目录" / "dashboard_web.py",
                                  self.home / "中文目录" / "dashboard_hotkeys.py")
        text = self._startup_text()                   # wscript 按 ANSI 读：系统 ANSI 编码写才对
        self.assertIn("中文目录\\dashboard_web.py", text)
        self.assertIn("中文目录\\dashboard_hotkeys.py", text)

    def test_missing_monitor_launcher_is_not_an_error(self):
        self.monitor_vbs.unlink()
        self._switch("landscape")
        self.assertEqual(self.launched, [self.startup_vbs])


if __name__ == "__main__":
    unittest.main()
