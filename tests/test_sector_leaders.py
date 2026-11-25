# -*- coding: utf-8 -*-
"""页3 板块个股行的取舍（横竖两个渲染器；不联网，画布用桩）。

规则（2026-10-09 用户定稿）：热板块展示领涨股，冷板块必须展示实际领跌股；没有领跌数据
就整行不显示，绝不用领涨股冒充。横版早已如此，竖版此前对冷板块读领涨股字段却标"领跌:"。
"""
import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401

GAINER = {"name": "合成领涨股"}
GAINERS = [{"name": "合成上涨股甲"}, {"name": "合成上涨股乙"}]
DECLINERS = [{"name": "合成下跌股甲"}, {"name": "合成下跌股乙"}]


class SectorLeadersTest(unittest.TestCase):
    def _render(self, variant, sector, is_hot):
        """渲染一个板块条目，返回画上去的全部文字（拼成一个字符串）。"""
        _env.force_variant(variant)
        module = importlib.import_module(f"epd_dashboard.renderers.{variant}.page3_markets")
        draw = mock.MagicMock()
        draw.textlength.return_value = 30.0             # 桩画布：所有文字等宽，不做真实排版
        if variant == "landscape":
            module._sector_rows(draw, (0, 0, 480, 480), 0, [(sector, is_hot)], 80)
        else:
            module.render_sector_list(draw, (0, 0, 240, 240), [sector], is_hot=is_hot)
        return " | ".join(str(call.args[1]) for call in draw.text.call_args_list)

    def test_hot_board_shows_its_leading_gainers(self):
        for variant in ("landscape", "portrait"):
            with self.subTest(variant=variant):
                text = self._render(variant, {"name": "合成热板块", "zdf": "2.5", "stocks": GAINERS}, True)
                self.assertIn("领涨", text)
                self.assertIn(GAINERS[0]["name"], text)
                self.assertNotIn("领跌", text)

    def test_cold_board_shows_its_leading_decliners(self):
        for variant in ("landscape", "portrait"):
            with self.subTest(variant=variant):
                text = self._render(variant, {"name": "合成冷板块", "zdf": "-2.5", "stocks": DECLINERS,
                                              "lzg": GAINER}, False)
                self.assertIn("领跌", text)
                self.assertIn(DECLINERS[0]["name"], text)
                self.assertNotIn(GAINER["name"], text)

    def test_tencent_fallback_gainer_is_shown_for_hot_boards_only(self):
        for variant in ("landscape", "portrait"):
            with self.subTest(variant=variant):
                sector = {"name": "合成板块", "zdf": "1.0", "lzg": GAINER}
                self.assertIn(GAINER["name"], self._render(variant, sector, True))
                # 兜底接口不提供领跌股：冷板块的个股行整体不显示，不拿领涨股冒充
                cold = self._render(variant, dict(sector, zdf="-1.0"), False)
                self.assertNotIn(GAINER["name"], cold)
                self.assertNotIn("领跌", cold)

    def test_hot_board_without_any_stock_data_still_shows_the_label(self):
        for variant in ("landscape", "portrait"):
            with self.subTest(variant=variant):
                self.assertIn("领涨", self._render(variant, {"name": "合成板块", "zdf": "1.0"}, True))


if __name__ == "__main__":
    unittest.main()
