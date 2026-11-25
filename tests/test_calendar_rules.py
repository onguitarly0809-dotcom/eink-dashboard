# -*- coding: utf-8 -*-
"""日历规则测试（不联网）：节假日表只对它覆盖的年份有效、美股夏令时的切换时刻。"""
import contextlib
import importlib
import io
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401


class _CalendarCase(unittest.TestCase):
    def setUp(self):
        _env.force_variant("landscape")
        self.cal = importlib.import_module("epd_dashboard.calendar_cn")
        self.year = self.cal.HOLIDAY_PLAN_YEAR

    def holiday(self, year, month, day):
        """查某天的休/班标记，收集 stderr（跨年提醒只应出现一次）。"""
        self.cal._plan_year_warned = False
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            mark = self.cal.holiday_mark(date(year, month, day))
        return mark, err.getvalue()


class HolidayPlanYearTest(_CalendarCase):
    def test_covered_year_still_uses_the_table(self):
        plan = self.cal.HOLIDAY_PLAN
        self.assertGreaterEqual(len(plan), 20)                      # 2026 年安排：30 余项
        closed = next(key for key, value in plan.items() if value == "休")
        workday = next(key for key, value in plan.items() if value == "班")
        self.assertEqual(self.holiday(self.year, *closed)[0], "休")
        self.assertEqual(self.holiday(self.year, *workday)[0], "班")
        self.assertEqual(self.holiday(self.year, 11, 25)[0], None)  # 普通工作日不在表里
        self.assertFalse(self.cal.is_trading_day(date(self.year, *closed)))
        self.assertTrue(self.cal.is_trading_day(date(self.year, *workday)))   # 调休上班日照常开市

    def test_other_years_do_not_inherit_last_years_schedule(self):
        next_year = self.year + 1
        # 旧表把 2026-02-16（春节）记作"休"；2027 年的同一天只是个普通工作日（元旦这类
        # 每年固定的节日不算），必须按常规规则判为交易日
        self.assertEqual(self.holiday(self.year, 2, 16)[0], "休")
        mark, err = self.holiday(next_year, 2, 16)
        self.assertIsNone(mark)
        self.assertIn(f"WARN HOLIDAY_PLAN 只覆盖 {self.year} 年", err)      # 提醒换表
        self.assertTrue(self.cal.is_trading_day(date(next_year, 2, 16)))
        # 提醒只打一次，不会每个日期刷一行
        self.cal._plan_year_warned = False
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for day in range(1, 28):
                self.cal.holiday_mark(date(next_year, 2, day))
        self.assertEqual(err.getvalue().count("WARN HOLIDAY_PLAN"), 1)

    def test_reminder_names_the_plan_year_from_config(self):
        from epd_dashboard import config
        self.assertEqual(self.cal.HOLIDAY_PLAN_YEAR, config.HOLIDAY_PLAN_YEAR)
        with mock.patch.object(self.cal, "HOLIDAY_PLAN_YEAR", date.today().year + 5):
            self.assertIsNone(self.cal.holiday_mark(date.today()))


class UsMarketClockTest(_CalendarCase):
    """美股 9:30-16:00 美东：北京 = 美东 + 12h（夏令时）/ +13h（冬令时）。"""

    def test_dst_boundaries_follow_second_sunday_of_march_and_first_sunday_of_november(self):
        active = self.cal.us_dst_active
        for year in (2026, 2027, 2030):
            with self.subTest(year=year):
                march = [date(year, 3, d) for d in range(1, 15) if date(year, 3, d).weekday() == 6][1]
                november = [date(year, 11, d) for d in range(1, 8) if date(year, 11, d).weekday() == 6][0]
                start = datetime.combine(march, datetime.min.time()).replace(hour=15)
                end = datetime.combine(november, datetime.min.time()).replace(hour=14)
                self.assertFalse(active(start.replace(hour=14, minute=59)))
                self.assertTrue(active(start))
                self.assertTrue(active(end.replace(hour=13, minute=59)))
                self.assertFalse(active(end))

    def test_market_hours_shift_by_one_hour_with_dst(self):
        def status(hour, minute, when):
            return self.cal.market_status_for("US", when.replace(hour=hour, minute=minute))

        winter_friday = datetime(2026, 3, 6)      # 切换前的周五：22:30 开盘
        summer_wednesday = datetime(2026, 7, 1)   # 夏令时内：21:30 开盘，次日 04:00 收盘
        next_day = summer_wednesday + timedelta(days=1)
        self.assertEqual(status(22, 29, winter_friday), "未开盘")
        self.assertEqual(status(22, 30, winter_friday), "交易中")
        self.assertEqual(status(21, 29, summer_wednesday), "未开盘")
        self.assertEqual(status(21, 30, summer_wednesday), "交易中")
        self.assertEqual(status(4, 0, next_day), "交易中")
        self.assertEqual(status(4, 1, next_day), "已收盘")
        self.assertEqual(status(12, 0, datetime(2026, 7, 4)), "休市")          # 周六
        self.assertEqual(status(12, 0, datetime(2026, 11, 2)), "休市")          # 北京周一中午 = 纽约周日晚
        self.assertEqual(status(22, 29, datetime(2026, 11, 2)), "未开盘")       # 冬令时：22:30 才开盘
        self.assertEqual(status(22, 30, datetime(2026, 11, 2)), "交易中")

    def test_hk_and_a_share_clocks_are_untouched(self):
        self.assertEqual(self.cal.market_status_for("HK", datetime(2026, 11, 25, 10, 0)), "交易中")
        self.assertEqual(self.cal.market_status_for("HK", datetime(2026, 11, 25, 12, 30)), "午休")
        self.assertEqual(self.cal.market_status_for("A", datetime(2026, 11, 25, 14, 59)), "交易中")
        self.assertEqual(self.cal.market_status_for("A", datetime(2026, 11, 28, 14, 59)), "休市")   # 周六


if __name__ == "__main__":
    unittest.main()
