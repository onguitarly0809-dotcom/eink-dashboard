"""竖版页面渲染器（480x800，页1-6）。统一再导出页面函数，cli/工具按包级 API 调用。"""
from epd_dashboard.renderers.portrait.page1_today import render_dashboard
from epd_dashboard.renderers.portrait.page2_news import render_page2
from epd_dashboard.renderers.portrait.page3_markets import render_page3
from epd_dashboard.renderers.portrait.page4_analysis import render_page4
from epd_dashboard.renderers.portrait.page5_zhipu import render_page5
from epd_dashboard.renderers.portrait.page6_weather import render_page6
from epd_dashboard.renderers.portrait.test_pattern import render_test

__all__ = ["render_dashboard", "render_page2", "render_page3", "render_page4",
           "render_page5", "render_page6", "render_test"]
