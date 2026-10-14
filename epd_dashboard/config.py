"""集中配置（横竖共用的共享核心）：变体解析 + 数据源 URL / 路径 / TTL。

结构：
- 横竖有差异的版面常量与字数配额在 epd_dashboard/layouts/{landscape,portrait}.py，
  本模块按当前变体把它们平铺导出——调用方始终 `from epd_dashboard.config import X`；
- 其余常量（EPD 固件参数、数据源、凭据路径、缓存 TTL、节假日表）横竖一致，定义在本文件。

变体解析：各运营目录的入口脚本（render_dashboard.py / dashboard_web.py /
dashboard_hotkeys.py）先设置 EPD_VARIANT + EPD_BASE_DIR 再导入本包；
未设置时默认横版（当前运营方向），BASE_DIR 按变体目录名从仓库根推导。

改动屏幕型号/数据源时只动这里；EPD_IMAGE_BYTES 需与 send_dashboard.ps1 的
48000 和固件 EPDSerial.h 的 EPD_IMAGE_BYTES 保持一致。
"""
import os
import urllib.parse
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

VARIANT = os.environ.get("EPD_VARIANT") or "landscape"
_VARIANT_DIRS = {"landscape": "dashboard_serial_landscape", "portrait": "dashboard_serial"}
if VARIANT not in _VARIANT_DIRS:
    raise RuntimeError(f"unknown EPD_VARIANT: {VARIANT!r} (expected landscape|portrait)")

# 运行期文件（缓存/计划/bin/预览/日志）都锚定运营变体目录，横竖两套互不干扰
BASE_DIR = Path(os.environ.get("EPD_BASE_DIR") or _REPO_ROOT / _VARIANT_DIRS[VARIANT])

# ---------- 版式与版面配额（横竖差异全部在 layouts/，按变体平铺导出） ----------
from epd_dashboard.layouts import get_layout  # noqa: E402

LAYOUT = get_layout(VARIANT)
globals().update(
    {name: value for name, value in vars(LAYOUT).items()
     if name.isupper() and not name.startswith("_")}
)

# ---------- EPD 固件参数（7.5in V2 面板 800x480 栅格，横竖共用） ----------
EPD_WIDTH = 800
EPD_HEIGHT = 480
EPD_ROW_BYTES = EPD_WIDTH // 8
EPD_IMAGE_BYTES = EPD_ROW_BYTES * EPD_HEIGHT
# 四灰模式（2026-09 方案四）：2bpp 图拆成 0x10/0x13 两张 1bpp 位平面串流发送，
# 固件按 BEGIN 尺寸分流（48000=1bit 快刷不变 / 96000=4灰），编码规则与微雪
# EPD_7IN5_V2_Display_4Gray 一致（详见 output.pack_4gray 注释）
EPD_IMAGE_BYTES_4G = EPD_IMAGE_BYTES * 2
# PC→固件串口端口；波特率/ACK 块大小由 push.py 自动协商（新固件 921600/512B，
# 旧固件 115200/128B），与固件 dashboard_serial.ino 的 Serial.begin / kChunkSize 对应
EPD_SERIAL_PORT = os.getenv("EPD_SERIAL_PORT", "")

# ---------- 出口主机白名单：httpclient.py 只允许访问这些主机 ----------
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
# 天气字段按全量抓取（体感/气压/风向/逐时/多日预报）；页1只用其中实况子集
WEATHER_CITY = "北京"
WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast?"
    + urllib.parse.urlencode(
        {
            "latitude": os.getenv("EPD_WEATHER_LATITUDE", "39.9042"),
            "longitude": os.getenv("EPD_WEATHER_LONGITUDE", "116.4074"),
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
                       "precipitation_probability,weather_code,surface_pressure,wind_speed_10m,wind_direction_10m,uv_index",
            "hourly": "temperature_2m,precipitation_probability",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,sunrise,sunset",
            "timezone": "Asia/Shanghai",
            "forecast_days": 6,
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
MARKET_COMPANY_SYMBOLS = (
    ("hk02513", "智谱AI"),
)

# ---------- 跨模块共享的文件路径 ----------
# GLM Coding Plan 团队版：凭据放 zcode workspace 的 conf（含敏感 key，不入仓库），接口只返回 5小时/每周两个窗口
GLM_USAGE_CONF = Path(os.getenv("GLM_USAGE_CONF", str(BASE_DIR / "glm_usage.conf")))
GLM_QUOTA_URL = "https://open.bigmodel.cn/api/monitor/usage/quota/limit?type=2"
PLANS_FILE = BASE_DIR / "plans.txt"

# ---------- 邮件提醒（IMAP 监控插播页） ----------
# mail_config.json 含 QQ 邮箱授权码（敏感凭据），根 .gitignore 已排除，严禁入库；
# 其余为监控进程运行期文件，同样不入库
MAIL_CONFIG_FILE = BASE_DIR / "mail_config.json"
MAIL_INBOX_FILE = BASE_DIR / "mail_inbox.json"    # 监控 → 渲染器的数据交接文件
MAIL_STATE_FILE = BASE_DIR / "mail_state.json"    # UID 水位 + 弹窗还原状态（重启续期）
MAIL_LOG_FILE = BASE_DIR / "mail_monitor.log"
MAIL_BASE_PNG = BASE_DIR / "mail_base.png"        # 弹窗底图（被覆盖页的还原基准）
PAGE_STATE_FILE = BASE_DIR / "page_state.json"    # 与 ops/control.ps1 共用的页状态

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
ANALYSIS_WEB_SEARCH = False    # True 时请求附带 web_search 联网工具（仅标准接口支持，且需账户余额）
ANALYSIS_NEWS_PER_SECTOR = 6   # 每个板块喂给模型的新闻标题条数（Google News 搜索）
ANALYSIS_NEWS_MAX_AGE_DAYS = 2 # 新闻时间窗（天）：查询加 when:Nd 过滤，归因"今日涨跌"只需最近1-2天消息
ANALYSIS_NEWS_BUDGET = 30.0    # 板块新闻标题抓取整体时间预算（秒），超预算的板块跳过

INSIGHT_RECENT_TOPICS = 8      # Web 控制台展示的最近主题数
INSIGHT_TOPIC_HISTORY = 120   # 持久去重历史，避免重复讲解同一主题
# Obsidian 归档目录：每次生成新洞察（轮播到页4 / 手动 analysis）同步写一份
# Markdown 笔记；只在新生成时落盘，重渲染不重复归档，导出失败不影响主链路
INSIGHT_ARCHIVE_DIR = Path(os.getenv(
    "INSIGHT_ARCHIVE_DIR", str(Path.home() / "Documents" / "Obsidian Vault" / "04-认知")))

# ---------- 页2新闻 AI 摘要（2026-09-11 国内栏试点通过，同日铺开三栏） ----------
# "模型通读全文 -> 一行精华"替代原始标题。正文来源限定在出口白名单内的站点：
# 中新网（文章页）/量子位（文章页）/雷锋网（RSS 自带全文）；Google 裸标题源退居备胎。
NEWS_SUMMARY_ENABLED = True      # 总开关（False 时三栏回到纯标题流、源序复原）
NEWS_SUMMARY_BODY_CHARS = 2000  # 送模型的正文截断长度（新闻前载，导语+首段已含核心事实）
NEWS_SUMMARY_TIMEOUT_S = 15     # 单篇 GLM 调用超时（秒）
NEWS_SUMMARY_BUDGET_S = 70      # 单栏摘要整体时间预算（秒），超时剩余条目下轮再做
NEWS_SUMMARY_RETAIN = 40       # 出栏条目的摘要保留条数：标题暂时滑出 5 条序列又回来时
                               # 直接复用缓存不重调模型（源在中新网/Google间摆动时常见）
DATA_CACHE_FILE = BASE_DIR / "dashboard_data.json"
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

# ---------- 页1 月历：法定节假日/调休安排表 ----------
# 按《国务院办公厅关于2026年部分节假日安排的通知》整理；官方口径如有出入，改这张表即可。
# (月, 日) -> "休"=法定放假（含调休形成的连休日） | "班"=调休上班日
HOLIDAY_PLAN = {
    (1, 1): "休", (1, 2): "休", (1, 3): "休",                        # 元旦
    (1, 4): "班",                                                     # 元旦调休上班
    (2, 14): "班",                                                    # 春节调休上班
    (2, 15): "休", (2, 16): "休", (2, 17): "休", (2, 18): "休",
    (2, 19): "休", (2, 20): "休", (2, 21): "休", (2, 22): "休",
    (2, 23): "休",                                                    # 春节（15-23 共9天）
    (2, 28): "班",                                                    # 春节调休上班
    (4, 4): "休", (4, 5): "休", (4, 6): "休",                         # 清明（不调休）
    (5, 1): "休", (5, 2): "休", (5, 3): "休", (5, 4): "休", (5, 5): "休",  # 劳动节
    (5, 9): "班",                                                     # 劳动节调休上班
    (6, 19): "休", (6, 20): "休", (6, 21): "休",                      # 端午（不调休）
    (9, 20): "班",                                                    # 国庆调休上班
    (9, 25): "休", (9, 26): "休", (9, 27): "休",                      # 中秋（不调休）
    (10, 1): "休", (10, 2): "休", (10, 3): "休", (10, 4): "休",
    (10, 5): "休", (10, 6): "休", (10, 7): "休",                      # 国庆
    (10, 10): "班",                                                   # 国庆调休上班
}
