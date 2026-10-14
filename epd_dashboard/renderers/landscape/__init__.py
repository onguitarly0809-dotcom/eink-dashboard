"""横版页面渲染器（800x480）。统一再导出页面函数，cli/工具按包级 API 调用。"""
from epd_dashboard.renderers.landscape.page1_today import render_dashboard
from epd_dashboard.renderers.landscape.page2_news import render_page2
from epd_dashboard.renderers.landscape.page3_markets import render_page3
from epd_dashboard.renderers.landscape.page4_analysis import render_page4
from epd_dashboard.renderers.landscape.page5_zhipu import render_page5
from epd_dashboard.renderers.landscape.page_mail import render_mail_overlay
from epd_dashboard.renderers.landscape.test_pattern import render_test

__all__ = ["render_dashboard", "render_page2", "render_page3", "render_page4",
           "render_page5", "render_mail_overlay", "render_test"]
