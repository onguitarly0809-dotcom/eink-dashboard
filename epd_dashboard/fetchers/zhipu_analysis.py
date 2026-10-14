"""页5 智谱AI 走势归因：个股行情缓存 + 公司/AI板块新闻标题 -> 智谱 GLM 归因报告。

与页4（fetchers/analysis.py）共用聊天通道（_request_chat：glm-5.3 主通道 +
1113 自动回退）、时效判断（should_refresh/TTL）与新闻抓取组件；差异仅在
上下文构造（个股行情而非板块冷热）与提示词。生成窗口对齐港股时段（至16:05）。
"""
import json
import re
import sys
import time
from datetime import datetime, time as dtime

from epd_dashboard.config import (
    ANALYSIS_API_URL,
    ANALYSIS_MAX_CHARS,
    ANALYSIS_MODEL,
    ANALYSIS_MODEL_FALLBACK,
    ANALYSIS_NEWS_BUDGET,
    ANALYSIS_NEWS_MAX_AGE_DAYS,
    ANALYSIS_NEWS_PER_SECTOR,
    ANALYSIS_WEB_SEARCH,
    GLM_CHAT_URL,
    STOCK_RETRY_COUNT,
    STOCK_SECTION_QUOTAS,
)
from epd_dashboard.fetchers.analysis import _request_chat, in_generation_window, should_refresh
from epd_dashboard.fetchers.glm import _credentials
from epd_dashboard.fetchers.news import _fetch_annotated_titles, _gnews_search

ZHIPU_CODE = "hk02513"
ZHIPU_NAME = "智谱AI"
AI_INDEX_CODE = "sz399415"     # 人工智能(A)指数：页5 右侧对照分时图
HK_SESSION_END = dtime(16, 5)   # 港股连续交易 09:30-12:00 / 13:00-16:00，留 5 分钟余量

# 各节字数配额随版式（横版17px/竖版自适应字号），由 config 导入：
# 见 layouts/{landscape,portrait}.py 的 STOCK_SECTION_QUOTAS 注释——提示词配额与
# _response_error 逐节硬校验共用此表，超配额整篇作废重写。
# 教训：只有提示词没有硬校验时模型会写到 75 字（配额30），指令形同虚设。


def _split_sections(text):
    """【】标题分节 → {节名: [正文行]}；标题行外的所有行归入当前节。"""
    sections = {}
    current = None
    for line in str(text).splitlines():
        m = re.match(r"^【([^】]+)】\s*$", line.strip())
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return sections


def _response_error(text, quotas=STOCK_SECTION_QUOTAS):
    """逐节硬校验：缺节、任一节超配额、总量超帽、markdown/URL 都判失败。"""
    sections = _split_sections(text)
    for name, _q, _d in quotas:
        if name not in sections:
            return f"missing section: {name}"
    for name, quota, _d in quotas:
        n = sum(len(re.sub(r"\s+", "", line)) for line in sections[name])
        if n > quota:
            return f"section over limit: {name} {n}>{quota}"
    body = "".join("".join(lines) for lines in sections.values())
    if len(re.sub(r"\s+", "", body)) > ANALYSIS_MAX_CHARS:
        return "body too long"
    if re.search(r"https?://|\*\*", text):
        return "markdown or url"
    return ""

SYSTEM_PROMPT = (
    "你是一位面向个人投资者的资深财经编辑，熟悉A股与港股市场，文风客观严谨。"
    "只依据给出的行情数据、新闻标题与你的财经知识做归因分析，绝不虚构具体政策文件、数字或日期。"
)


def _fmt_pct(pct):
    try:
        return f"{float(pct):+.2f}%"
    except (TypeError, ValueError):
        return "--"


def _find_quote(markets, code):
    """从行情缓存找指定标的：先 my_watchlist（含 code），再 companies（按名称兜底）。"""
    for item in (markets.get("quotes") or {}).get("my_watchlist") or []:
        if isinstance(item, dict) and item.get("code") == code:
            return item
    for item in markets.get("companies") or []:
        if isinstance(item, dict) and item.get("name") == ZHIPU_NAME:
            return item
    return None


def _index_pct(markets, code):
    for item in (markets.get("quotes") or {}).get("market_ref") or []:
        if isinstance(item, dict) and item.get("code") == code:
            return item.get("pct")
    return None


def _headlines():
    """公司动态与 AI 板块两路新闻标题，整体受 ANALYSIS_NEWS_BUDGET 时间预算约束。

    查询带 when:Nd 限定时间窗（默认按相关度排序会混入数周前旧文），
    标题附发布时间标注供模型区分新旧。
    """
    queries = (
        ("智谱AI公司动态", f"{ZHIPU_NAME} 利好 OR 利空 OR 分析 when:{ANALYSIS_NEWS_MAX_AGE_DAYS}d"),
        ("AI板块与算力", f"人工智能 板块 利好 OR 利空 when:{ANALYSIS_NEWS_MAX_AGE_DAYS}d"),
    )
    result = {}
    start = time.monotonic()
    for label, query in queries:
        if result and time.monotonic() - start > ANALYSIS_NEWS_BUDGET:
            print(f"zhipu analysis: headlines budget exceeded, skip {label}", file=sys.stderr)
            break
        try:
            result[label] = _fetch_annotated_titles(_gnews_search(query))[:ANALYSIS_NEWS_PER_SECTOR]
        except Exception as exc:
            print(f"WARN zhipu analysis[{label}] headlines failed: {exc}", file=sys.stderr)
            result[label] = []
    return result


def _build_messages(markets, headlines, now, response_errors=()):
    user_lines = [f"今天是{now.strftime('%Y年%m月%d日 %H:%M')}。"]
    quote = _find_quote(markets, ZHIPU_CODE)
    if quote and quote.get("price", 0) > 0:
        user_lines.append(
            f"{ZHIPU_NAME}（港股 {ZHIPU_CODE}）最新价 {quote['price']:.2f} 港元，"
            f"今日涨跌 {quote.get('chg', 0):+.2f}、涨跌幅 {_fmt_pct(quote.get('pct'))}。"
        )
    else:
        user_lines.append(f"{ZHIPU_NAME}（{ZHIPU_CODE}）暂无最新行情数据。")
    ai_pct = _index_pct(markets, "sz399415")
    sh_pct = _index_pct(markets, "sh000001")
    if ai_pct is not None:
        user_lines.append(f"人工智能指数(399415)今日 {_fmt_pct(ai_pct)}。")
    if sh_pct is not None:
        user_lines.append(f"上证指数今日 {_fmt_pct(sh_pct)}。")
    user = "\n".join(user_lines)

    news_blocks = [
        f"【{label}】相关新闻标题：\n" + "\n".join(f"- {title}" for title in titles)
        for label, titles in headlines.items() if titles
    ]
    if news_blocks:
        user += "\n\n另附刚从新闻聚合搜索到的相关标题：\n\n" + "\n\n".join(news_blocks)
    source = "综合以上数据与你的联网检索结果" if ANALYSIS_WEB_SEARCH else "综合以上数据与你的财经知识"
    # 字数预算与页4同一排版容量（见 config.ANALYSIS_MAX_CHARS 注释），各节配额加总不得超过
    user += (
        f"\n\n请{source}，写一份智谱AI今日走势归因分析。这是给电子墨水屏看的短报告，"
        f"正文（不含小节标题）严格控制在{ANALYSIS_MAX_CHARS}字以内，四个小节标题独占一行并用【】包裹，字数配额如下：\n"
        + "".join(f"-【{name}】不超过{q}字：{desc}；\n"
                  for name, q, desc in STOCK_SECTION_QUOTAS)
        + "各节正文长度写到目标区间内，不要贴着上限写："
        + "、".join(f"{name}{int(q * 0.7)}~{int(q * 0.92)}字"
                    for name, q, _d in STOCK_SECTION_QUOTAS)
        + "。任何一节超过配额一字，整篇作废重写。\n"
        "要求：\n"
        "1. 每节直接写成连贯语句，不要分条编号、不要markdown符号、表情或网址；\n"
        "2. 标题末尾括号内是发布时间：优先采信最新消息，新旧信息冲突时以新为准，"
        "不要把多天前的旧闻当作今日走势的驱动；\n"
        "3. 智谱AI是港股，注意其交易时段与流动性特点，不与A股涨跌幅直接类比；\n"
        "4. 归因必须与公司或AI行业直接相关且逻辑成立，缺乏明确消息时如实说明，不要编造政策、会议或数字。"
    )
    if response_errors:
        user += ("\n\n你刚才的输出未通过校验，逐次失败原因："
                 + "；".join(response_errors)
                 + "。重新输出时严格执行各节字数配额，超配额的小节明显写短——"
                   "宁可精炼也不要贴着上限写。")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def fetch_zhipu_analysis(markets, previous=None, now=None):
    """生成一份智谱AI走势归因分析（逐节配额硬校验，超限带原因重试）。
    结构化输出写入缓存 stock_analysis 字段；重试耗尽仍超配额则抛错，
    调用方（cli stock 路径）保留旧值并 WARN，不推坏版面。"""
    now = now or datetime.now()
    key, _org, _proj = _credentials()
    if not key:
        raise RuntimeError("GLM conf missing GLM_KEY")

    headlines = _headlines()
    response_errors = []
    for _attempt in range(STOCK_RETRY_COUNT):
        payload_base = {
            "messages": _build_messages(markets, headlines, now, response_errors),
            "stream": False,
    }
        if ANALYSIS_WEB_SEARCH:
            payload_base["tools"] = [{
                "type": "web_search",
                "web_search": {"enable": True, "search_engine": "search_std", "count": 5},
            }]
        try:
            text, data = _request_chat(key, ANALYSIS_MODEL, payload_base, ANALYSIS_API_URL)
        except RuntimeError as exc:
            # 1113 = 余额不足/无资源包（主通道模型不可用）：回退标准接口 + glm-4-flash 免费兜底
            fallback = ANALYSIS_MODEL_FALLBACK
            if fallback and fallback != ANALYSIS_MODEL and str(exc).startswith("1113"):
                print(f"WARN {ANALYSIS_MODEL} unavailable ({exc}), falling back to "
                      f"{fallback} via standard API", file=sys.stderr)
                text, data = _request_chat(key, fallback, payload_base, GLM_CHAT_URL)
            else:
                raise
        error = _response_error(text)
        if not error:
            usage = data.get("usage") or {}
            quote = _find_quote(markets, ZHIPU_CODE)
            return {
                "text": text,
                "model": data.get("model") or ANALYSIS_MODEL,
                "web_search": bool(ANALYSIS_WEB_SEARCH),
                "price": quote.get("price") if quote else None,
                "pct": quote.get("pct") if quote else None,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "updated": now.strftime("%H:%M"),
                "generated_at": now.isoformat(timespec="seconds"),
                "stale": False,
            }
        response_errors.append(error)
        print(f"WARN stock analysis quota violation ({error}), retry "
              f"{_attempt + 1}/{STOCK_RETRY_COUNT}", file=sys.stderr)
    raise RuntimeError(f"stock analysis failed quota validation after "
                       f"{STOCK_RETRY_COUNT} attempts: {response_errors}")
