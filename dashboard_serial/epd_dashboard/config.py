"""集中配置：屏幕尺寸、面板布局、数据源 URL、路径锚点。

改动屏幕型号/版式/数据源时只动这里；EPD_IMAGE_BYTES 需与
send_dashboard.ps1 的 48000 和固件 EPDSerial.h 的 EPD_IMAGE_BYTES 保持一致。
"""
import os
import urllib.parse
from pathlib import Path

# 所有运行期文件都以本包的上一级（dashboard_serial/）为锚点，与旧版单文件行为一致
BASE_DIR = Path(__file__).resolve().parent.parent

# ---------- 屏幕 / 版式（竖屏 480x800，三个等高面板） ----------
WIDTH = 480
HEIGHT = 800
PANEL_WIDTH = 456
PANEL_HEIGHT = 252
PANEL_X = 12
PANEL_Y = (12, 274, 536)

# ---------- EPD 固件参数（7.5in V2, 800x480 横屏） ----------
EPD_WIDTH = 800
EPD_HEIGHT = 480
EPD_ROW_BYTES = EPD_WIDTH // 8
EPD_IMAGE_BYTES = EPD_ROW_BYTES * EPD_HEIGHT
# PC→固件串口端口；波特率/ACK 块大小由 push.py 自动协商（新固件 921600/512B，
# 旧固件 115200/128B），与固件 dashboard_serial.ino 的 Serial.begin / kChunkSize 对应
EPD_SERIAL_PORT = os.getenv("EPD_SERIAL_PORT", "")

# ---------- 出口主机白名单：epd_dashboard/httpclient.py 只允许访问这些主机 ----------
# SSRF 边界校验（安全扫描 HIGH 项的整改）：所有数据源主机在此显式登记，
# 新增数据源/新闻源时同步维护；test_news_sources.py 探测用的候选源也一并列入
ALLOWED_HTTP_HOSTS = {
    # 行情：腾讯实时/板块榜/分时分钟线
    "qt.gtimg.cn",
    "proxy.finance.qq.com",
    "web.ifzq.gtimg.cn",
    # 天气：open-meteo 实况 + 中央气象台预警
    "api.open-meteo.com",
    "www.nmc.cn",
    # 新闻：Google News RSS + 中新网滚动 + AI 栏目备选源（量子位/雷锋网）
    "news.google.com",
    "www.chinanews.com.cn",
    "www.qbitai.com",
    "www.leiphone.com",
    # 候选新闻源（仅 test_news_sources.py 探测用，尚未启用）
    "www.tmtpost.com",
    "www.ifanr.com",
    "sspai.com",
    "www.people.com.cn",
    # 智谱 GLM：额度查询 + 对话补全（页1 额度/页4/页5 分析）
    "open.bigmodel.cn",
}

# ---------- 数据源 URL ----------
WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast?"
    + urllib.parse.urlencode(
        {
            "latitude": os.getenv("EPD_WEATHER_LATITUDE", "39.9042"),
            "longitude": os.getenv("EPD_WEATHER_LONGITUDE", "116.4074"),
            "current": "temperature_2m,relative_humidity_2m,precipitation_probability,weather_code,wind_speed_10m,uv_index",
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "Asia/Shanghai",
            "forecast_days": 1,
        }
    )
)
WEATHER_ALERT_URL = (
    "http://www.nmc.cn/rest/findAlarm?pageNo=1&pageSize=2000"
)

# ---------- 行情：腾讯 A股/港股/美股（新浪源已停用，代码保留在 git 历史） ----------
MARKET_URL_TENCENT = "https://qt.gtimg.cn/q="
MARKET_SECTOR_URL = (
    "https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank"
    "?board_type=hy&sort_type=price&direct=down&offset=0&count=200"
)
# 腾讯分时（分钟级）数据：返回当日 09:30 起每分钟 "hhmm 价格 累计量 累计额"，含午休跳档
MARKET_MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code="
MARKET_GROUPS = {
    "my_watchlist": {"title": "示例自选",
                     "symbols": [("hk02513", "智谱AI"), ("sh000001", "上证指数"), ("sz399001", "深证成指"),
                               ("sz399006", "创业板指"), ("hkHSTECH", "恒生科技"), ("usIXIC", "纳斯达克")]},
    "market_ref": {"title": "市场参考",
                   "symbols": [("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指"),
                             ("hkHSTECH", "恒生科技"), ("usIXIC", "纳斯达克"), ("sz399415", "人工智能")]},
}
MARKET_COMPANY_SYMBOLS = (("hk02513", "智谱AI"),)

# ---------- 跨模块共享的文件路径 ----------
GLM_USAGE_CONF = Path(os.getenv("GLM_USAGE_CONF", BASE_DIR / "glm_usage.conf"))
GLM_QUOTA_URL = "https://open.bigmodel.cn/api/monitor/usage/quota/limit?type=2"

# ---------- 页4认知洞察 / 页5智谱AI分析（智谱 GLM，凭据复用 GLM_KEY） ----------
# 2026-08 实测：标准接口 paas/v4 只认余额/资源包——仅 glm-4-flash 免费可调，glm-4.5/5.x 全报 1113；
# Coding Plan 套餐额度走专用接口 coding/paas/v4（同一个 Key），glm-5.3 实测可用
# （thinking 推理模型，代码中对 glm-5* 关闭思考换取生成速度）。
# 主通道 = ANALYSIS_API_URL + ANALYSIS_MODEL；报 1113 时自动回退：标准接口 + glm-4-flash（免费兜底）
GLM_CHAT_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_CODING_CHAT_URL = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
ANALYSIS_API_URL = GLM_CODING_CHAT_URL
ANALYSIS_MODEL = "glm-5.3"
ANALYSIS_MODEL_FALLBACK = "glm-4-flash"
ANALYSIS_TTL_MINUTES = 90      # 分析缓存时效：超过才允许自动重新生成
# 页5报告字数上限 = 排版预算：取消风险提示后，450字在18/16/15/14/12px
# 自适应排版下可优先选择更大字号；各节配额写在 zhipu_analysis.py 提示词里。
ANALYSIS_MAX_CHARS = 450
ANALYSIS_WEB_SEARCH = False    # True 时请求附带 web_search 联网工具（仅标准接口支持，且需账户余额）
ANALYSIS_NEWS_PER_SECTOR = 6   # 每个板块喂给模型的新闻标题条数（Google News 搜索）
ANALYSIS_NEWS_MAX_AGE_DAYS = 2 # 新闻时间窗（天）：查询加 when:Nd 过滤，归因"今日涨跌"只需最近1-2天消息
ANALYSIS_NEWS_BUDGET = 30.0    # 板块新闻标题抓取整体时间预算（秒），超预算的板块跳过

# ---------- 页4认知洞察解读 ----------
# 生成端保留六段结构；渲染端剥离主题/领域两个元信息小节，
# 正文按22/20/18/16/14/12px自适应，优先把释放出的空间用于放大内容。
INSIGHT_MAX_CHARS = 600
INSIGHT_RECENT_TOPICS = 8      # Web 控制台展示的最近主题数
INSIGHT_TOPIC_HISTORY = 120   # 持久去重历史，避免重复讲解同一主题
INSIGHT_RETRY_COUNT = 3       # 主题重复或格式异常时的重试次数
# Obsidian 归档目录：每次生成新洞察（轮播到页4 / 手动 analysis）同步写一份
# Markdown 笔记；只在新生成时落盘，导出失败仅记 WARN 不影响刷新主链路
INSIGHT_ARCHIVE_DIR = Path(os.getenv(
    "INSIGHT_ARCHIVE_DIR", str(Path.home() / "Documents" / "Obsidian Vault" / "04-认知")))

# ---------- 页2新闻 AI 摘要（2026-09-11 国内栏试点通过，同日铺开三栏） ----------
# "模型通读全文 -> 一行精华"替代原始标题。正文来源限定在出口白名单内的站点：
# 中新网（文章页）/量子位（文章页）/雷锋网（RSS 自带全文）；Google 裸标题源退居备胎。
NEWS_SUMMARY_ENABLED = True      # 总开关（False 时三栏回到纯标题流、源序复原）
NEWS_SUMMARY_BODY_CHARS = 2000  # 送模型的正文截断长度（新闻前载，导语+首段已含核心事实）
NEWS_SUMMARY_LINE_CHARS = 22    # 摘要行长度上限（屏宽约23全角字，按22用满可视面积、留1字余量）；
                                # 模型超过才触发重压/保形截断，20字上下的行不再二次调用
NEWS_SUMMARY_TIMEOUT_S = 15     # 单篇 GLM 调用超时（秒）
NEWS_SUMMARY_BUDGET_S = 70      # 单栏摘要整体时间预算（秒），超时剩余条目下轮再做
NEWS_SUMMARY_RETAIN = 40       # 出栏条目的摘要保留条数：标题暂时滑出 5 条序列又回来时
                               # 直接复用缓存不重调模型（源在中新网/Google间摆动时常见）
DATA_CACHE_FILE = BASE_DIR / "dashboard_data.json"
PLANS_FILE = BASE_DIR / "plans.txt"
DEFAULT_OUTPUT_DIR = BASE_DIR

# ---------- 切页缓存时效（TTL）：按键切页时缓存未过期就跳过联网，先出图 ----------
# 只门控切页用的 mode（today/news/markets）；full（定时轮播，数据补给线）与手动单模块
# 命令不受 TTL 限制，仍全量抓取。markets 分交易时段：盘中行情变化快用短 TTL，收盘后用长 TTL。
TTL_MINUTES = {
    "weather": 30,
    "glm": 30,
    "news": 10,
}
MARKETS_TTL_TRADING_MINUTES = 3
MARKETS_TTL_CLOSED_MINUTES = 60
