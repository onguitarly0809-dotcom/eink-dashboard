#!/usr/bin/env python3
"""兼容入口：实际实现已拆分到 epd_dashboard 包。

保留本文件是因为 dashboard_control.ps1 / 计划任务 / 测试脚本都以
`python render_dashboard.py --mode X --page N` 方式调用，并有人以
`import render_dashboard` 访问模块级常量（如 NEWS_SOURCES）。
"""
from epd_dashboard.cli import main
from epd_dashboard.config import (
    AGENT_PLAN_DATA_FILE,
    DATA_CACHE_FILE,
    EPD_HEIGHT,
    EPD_IMAGE_BYTES,
    EPD_ROW_BYTES,
    EPD_WIDTH,
    HEIGHT,
    MARKET_COMPANY_SYMBOLS,
    MARKET_GROUPS,
    MARKET_SECTOR_URL,
    MARKET_URL_TENCENT,
    PANEL_HEIGHT,
    PANEL_WIDTH,
    PANEL_X,
    PANEL_Y,
    WEATHER_ALERT_URL,
    WEATHER_URL,
    WIDTH,
)
from epd_dashboard.datastore import load_cache, read_plans, save_cache
from epd_dashboard.fetchers.agentplan import fetch_agent_plan
from epd_dashboard.fetchers.glm import fetch_glm_plan
from epd_dashboard.fetchers.markets import AKSHARE_AVAILABLE, fetch_markets
from epd_dashboard.fetchers.news import NEWS_PER_BAND, NEWS_SOURCES, NEWS_TITLES, fetch_news
from epd_dashboard.fetchers.weather import fetch_weather, fetch_weather_alert
from epd_dashboard.output import rotate_for_epd, write_outputs
from epd_dashboard.placeholders import placeholder_glm, placeholder_quotas, placeholder_weather
from epd_dashboard.renderers.page1_today import render_agentplan, render_dashboard, render_plans, render_weather
from epd_dashboard.renderers.page2_news import render_page2
from epd_dashboard.renderers.page3_markets import render_page3
from epd_dashboard.renderers.test_pattern import render_test

if __name__ == "__main__":
    main()
