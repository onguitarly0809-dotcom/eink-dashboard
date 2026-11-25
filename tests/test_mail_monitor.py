# -*- coding: utf-8 -*-
"""邮件守护的推迟/重试逻辑测试（离线：IMAP、control.ps1、锁屏状态全部打桩）。

背景（2026-11 实测）：推送或收起到期时 wait_events 直接短路返回主循环，而被锁屏闸门
拒绝后队列保留、不等待，两者叠加成约每秒一轮的忙循环（4 天 7018 次，每轮拉起
powershell 并对 IMAP 做 SELECT+SEARCH）。修复后：被挡时记一个推迟截止时间，主循环按
它等待；解锁即结束等待；推送/收起阶段的异常不再杀死守护。
"""
import contextlib
import importlib
import io
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401


class _MonitorCase(unittest.TestCase):
    def setUp(self):
        _env.force_variant("landscape")
        self.mm = importlib.import_module("epd_dashboard.mail_monitor")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        # 状态/载荷/日志/底图全部指向临时目录，绝不碰运营目录里的真实文件
        for name, value in (("MAIL_STATE_FILE", root / "mail_state.json"),
                            ("MAIL_INBOX_FILE", root / "mail_inbox.json"),
                            ("MAIL_LOG_FILE", root / "mail_monitor.log"),
                            ("MAIL_BASE_PNG", root / "mail_base.png"),
                            ("PAGE_STATE_FILE", root / "page_state.json")):
            patcher = mock.patch.object(self.mm, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.logs = io.StringIO()
        redirect = contextlib.redirect_stderr(self.logs)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        cfg = dict(self.mm.DEFAULT_CONFIG, account="audit@example.invalid", auth_code="x",
                   batch_window_seconds=0, min_push_gap_seconds=0)
        self.monitor = self.mm.MailMonitor(cfg)

    def _pending_mail(self):
        self.monitor.pending = [{"uid": 1, "from": "合成发件人", "subject": "合成主题", "time": "12:00"}]
        self.monitor.last_arrival = time.time() - 60
        self.monitor.first_pending = self.monitor.last_arrival

    def _assert_waits_about(self, wakes, expected):
        """等待时长允许亚秒级误差：推迟的截止时刻固定，逐轮取到的是剩余时间。"""
        self.assertEqual(len(wakes), len(expected), str(wakes))
        for wake, want in zip(wakes, expected):
            self.assertAlmostEqual(wake, want, delta=0.5, msg=str(wakes))

    def _expired_overlay(self):
        self.monitor.overlay_until = time.time() - 1
        self.monitor.overlay_page = 1
        self.mm.MAIL_BASE_PNG.write_bytes(b"png")
        self.mm.PAGE_STATE_FILE.write_text('{"page": 1}', encoding="utf-8")

    def _run(self, lock_states, control_result, loops):
        """跑 run() 若干轮：wait_events 调满 loops 次后用 KeyboardInterrupt 结束主循环。
        锁屏监视线程替换成空函数——绝不让测试去调真实的 control.ps1。
        返回 (各轮等待秒数, _run_control 的 mock)。"""
        waits = []

        def fake_wait(max_wait):
            if len(waits) >= loops:
                raise KeyboardInterrupt
            waits.append(max_wait)
            return True

        with mock.patch.object(self.mm.MailMonitor, "_watch_lock", lambda self: None), \
                mock.patch.object(self.monitor, "connect"), mock.patch.object(self.monitor, "catchup"), \
                mock.patch.object(self.monitor, "_session_locked", side_effect=lambda: next(lock_states)), \
                mock.patch.object(self.monitor, "_run_control", return_value=control_result) as control, \
                mock.patch.object(self.monitor, "wait_events", side_effect=fake_wait):
            self.monitor.run()
        return waits, control


class DeferWhileLockedTest(_MonitorCase):
    def test_locked_push_waits_between_checks_instead_of_spinning(self):
        self._pending_mail()
        waits, control = self._run(iter(lambda: True, None), "locked", loops=6)
        control.assert_not_called()                        # 本地先判锁屏，不白起 powershell
        self.assertTrue(self.monitor.pending)              # 队列保留，解锁后补推
        self._assert_waits_about(waits, [0] + [self.mm.LOCKED_DEFER_WAKE_S] * (len(waits) - 1))   # 到期那一轮之后按 20 秒等，不是 0
        self.assertGreaterEqual(len(waits), 5)
        self.assertEqual(self.logs.getvalue().count("弹窗推迟"), 1)   # 一次锁屏只记一条日志

    def test_gate_rejecting_after_the_local_check_also_defers(self):
        # 竞态：本地判定时还没锁，调用 control.ps1 时已被闸门拒绝
        self._pending_mail()
        waits, control = self._run(iter([False] + [True] * 50), "locked", loops=5)
        control.assert_called_once_with("mail")            # 只被调用这一次，不再每轮重来
        self._assert_waits_about(waits[1:], [self.mm.LOCKED_DEFER_WAKE_S] * (len(waits) - 1))
        self.assertEqual(self.logs.getvalue().count("弹窗推迟"), 1)
        self.assertTrue(self.monitor.pending)

    def test_unlocking_pushes_on_the_next_loop(self):
        self._pending_mail()
        waits, control = self._run(iter([True, True, True, False, False, False]), True, loops=3)
        control.assert_called_once_with("mail")
        self.assertEqual(self.monitor.pending, [])
        self.assertGreater(self.monitor.overlay_until, time.time())
        self.assertIn('"overlay_seconds": 600',
                      self.mm.MAIL_INBOX_FILE.read_text(encoding="utf-8"))   # 页脚时长随载荷下发
        self._assert_waits_about(waits[:2], [0, self.mm.LOCKED_DEFER_WAKE_S])   # 锁屏期间按 20 秒等；解锁后的那一轮就补推

    def test_locked_dismiss_defers_without_calling_control(self):
        monitor = self.monitor
        self._expired_overlay()
        with mock.patch.object(monitor, "_session_locked", return_value=True), \
                mock.patch.object(monitor, "_run_control") as control:
            for _ in range(5):
                monitor.maybe_dismiss()
            control.assert_not_called()
            self.assertGreater(monitor.deferred_in(), 0)
            self.assertEqual(self.logs.getvalue().count("收起推迟"), 1)
        with mock.patch.object(monitor, "_session_locked", return_value=False), \
                mock.patch.object(monitor, "_run_control", return_value=True) as control:
            monitor.maybe_dismiss()
        control.assert_called_once_with("mailoff")
        self.assertEqual((monitor.overlay_until, monitor.overlay_page), (0.0, None))


class DeferOnFailureTest(_MonitorCase):
    def test_device_absent_and_real_failures_retry_after_a_delay(self):
        self._expired_overlay()
        for outcome in ("device", False):
            self.monitor.defer_until = 0.0
            with mock.patch.object(self.monitor, "_session_locked", return_value=False), \
                    mock.patch.object(self.monitor, "_run_control", return_value=outcome) as control:
                for _ in range(4):
                    self.monitor.maybe_dismiss()
                control.assert_called_once()               # 连调 4 次只真正尝试 1 次
            self.assertGreaterEqual(self.monitor.deferred_in(), self.mm.CONTROL_RETRY_S - 1)
        self.assertEqual(self.monitor.overlay_page, 1)     # 没做成之前不清状态

    def test_device_absent_push_keeps_queue_and_throttles(self):
        self._pending_mail()
        monitor = self.monitor
        monitor.cfg["min_push_gap_seconds"] = 180
        with mock.patch.object(monitor, "_session_locked", return_value=False), \
                mock.patch.object(monitor, "_run_control", return_value="device") as control:
            monitor.maybe_push()
            self.assertTrue(monitor.pending)               # 队列保留
            self.assertGreater(monitor._push_due_in(), 170)   # 按最小推送间隔节流，不立刻重来
            for _ in range(3):
                monitor.maybe_push()
        self.assertEqual(control.call_count, 1)

    def test_control_exit_code_4_means_device_absent_not_an_error(self):
        result = mock.Mock(returncode=4, stdout="", stderr="")
        with mock.patch.object(self.mm.subprocess, "run", return_value=result):
            self.assertEqual(self.monitor._run_control("mail"), "device")
        self.assertNotIn("ERROR", self.logs.getvalue())


class RobustnessTest(_MonitorCase):
    def test_step_exception_does_not_kill_the_loop(self):
        with mock.patch.object(self.monitor, "maybe_push", side_effect=OSError("file busy")):
            self._run(iter(lambda: False, None), True, loops=3)
        self.assertIn("maybe_push 异常", self.logs.getvalue())

    def test_filter_rules_tolerate_bad_entries(self):
        monitor = self.monitor
        monitor.cfg["filters"] = {"block_senders": ["@spam.example", 123, None],
                                  "block_subject_keywords": "not-a-list", "block_from_keywords": [7, "广告"]}
        self.assertTrue(monitor._is_blocked({"from": "x", "addr": "a@b.spam.example", "subject": "s"}))
        self.assertTrue(monitor._is_blocked({"from": "某广告", "addr": "a@c.example", "subject": "s"}))
        self.assertFalse(monitor._is_blocked({"from": "同事", "addr": "a@c.example", "subject": "报销"}))
        monitor.cfg["filters"] = "garbage"
        self.assertFalse(monitor._is_blocked({"from": "x", "addr": "a@b.c", "subject": "s"}))

    def test_uidvalidity_change_rebaselines_the_watermark(self):
        monitor = self.monitor
        monitor.watermark, monitor.baselined = 100, True
        imap = mock.Mock()
        imap.response.return_value = ("UIDVALIDITY", [b"7"])
        with mock.patch.object(monitor, "imap", imap):
            monitor._check_uidvalidity()                   # 旧状态文件没有该字段：只记录
            self.assertEqual((monitor.uidvalidity, monitor.baselined, monitor.watermark), (7, True, 100))
            imap.response.return_value = ("UIDVALIDITY", [b"8"])
            monitor._check_uidvalidity()                   # 服务器重新编号：重新基线
            self.assertEqual((monitor.baselined, monitor.watermark), (False, 0))
            imap.response.return_value = ("UIDVALIDITY", [None])
            monitor._check_uidvalidity()                   # 解析不了：保持原样
            self.assertEqual(monitor.uidvalidity, 8)

    def test_pid_lock_takes_over_when_pid_was_reused_by_another_program(self):
        mm = self.mm
        self.assertTrue(mm._process_image(os.getpid()).lower().startswith("python"))
        self.assertFalse(mm._pid_is_other_program(os.getpid()))
        self.assertFalse(mm._pid_is_other_program(99999999))   # 不存在：拿不准，认为锁有效
        others = [pid for pid, name in mm._iter_processes() if name.lower() == "explorer.exe"]
        if not others:
            self.skipTest("explorer.exe not running in this session")
        self.assertTrue(mm._pid_is_other_program(others[0]))
        lock = self.mm.MAIL_STATE_FILE.with_name("monitor.lock")
        lock.write_text(str(others[0]))
        with mm._PidLock(lock):                             # pid 已被别的程序复用：接管
            self.assertEqual(lock.read_text(), str(os.getpid()))
        lock.write_text(str(os.getpid()))
        with self.assertRaises(SystemExit):                 # 真有 python 实例占着：退出
            with mm._PidLock(lock):
                pass


class OrientationGuardTest(_MonitorCase):
    """登录自启脚本不分方向都会拉起监控：竖版运营时它必须直接退出（弹窗/锁屏层只有横版）。"""

    def _start_with_marker(self, text):
        """带方向标记跑一遍 main()；返回 (是否走到正常启动流程, 写日志的桩)。"""
        mm = self.mm
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        (home / "dashboard_serial_landscape").mkdir()              # 运营目录：正常启动要在里面写锁文件
        reached = RuntimeError("sentinel: normal startup path reached")
        with mock.patch.object(mm, "BASE_DIR", home / "dashboard_serial_landscape"), \
                mock.patch.object(mm, "MailMonitor", side_effect=reached), \
                mock.patch.object(mm, "load_config", return_value={}), \
                mock.patch.object(mm, "_log_write") as log, \
                contextlib.redirect_stderr(io.StringIO()):
            if text is not None:
                (home / "ACTIVE_ORIENTATION.txt").write_text(text, encoding="ascii")
            try:
                mm.main()
            except RuntimeError as exc:
                self.assertIs(exc, reached)                 # 只接受哨兵异常：别的异常照常失败
                return True, log
        return False, log

    def test_portrait_operation_does_not_start_the_monitor(self):
        started, log = self._start_with_marker("portrait\n")
        self.assertFalse(started)
        log.assert_called_once()
        self.assertIn("竖版运营", log.call_args.args[0])

    def test_landscape_or_missing_marker_starts_normally(self):
        for text in ("landscape", None, "", "garbage"):
            with self.subTest(marker=text):
                started, log = self._start_with_marker(text)
                self.assertTrue(started)
                log.assert_not_called()


class MailOverlayTextTest(unittest.TestCase):
    def setUp(self):
        _env.force_variant("landscape")
        from PIL import Image, ImageDraw
        from epd_dashboard.fonts import noto
        from epd_dashboard.renderers.landscape import page_mail
        from epd_dashboard.renderers.landscape.page4_analysis import BODY_TEXT_WEIGHT
        self.page_mail = page_mail
        self.base = Image.new("L", (800, 480), 255)
        self.draw = ImageDraw.Draw(self.base)
        self.font = noto(18, BODY_TEXT_WEIGHT)

    def test_two_line_cap_marks_truncation_with_an_ellipsis(self):
        fit = self.page_mail._fit_two_lines
        short = "合成测试主题"
        self.assertEqual(fit(self.draw, short, self.font, 596), [short])
        lines = fit(self.draw, "合成" * 60, self.font, 596)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].endswith("…"))
        self.assertLessEqual(self.draw.textlength(lines[1], font=self.font), 596)

    def test_footer_follows_overlay_seconds(self):
        render = self.page_mail.render_mail_overlay
        now = datetime(2026, 11, 25, 12, 0)
        payload = {"account": "a@example.invalid", "total_new": 1,
                   "mails": [{"from": "合成发件人", "subject": "合成主题", "time": "12:00"}]}
        default = render(self.base, payload, now).tobytes()
        self.assertEqual(default, render(self.base, dict(payload, overlay_seconds=600), now).tobytes())
        self.assertNotEqual(default, render(self.base, dict(payload, overlay_seconds=1800), now).tobytes())
        self.assertEqual(default, render(self.base, dict(payload, overlay_seconds="坏数据"), now).tobytes())


if __name__ == "__main__":
    unittest.main()
