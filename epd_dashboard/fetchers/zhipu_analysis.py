"""页5 智谱AI 走势归因：个股行情缓存 + 公司/AI板块新闻标题 -> 智谱 GLM 归因报告。

与页4（fetchers/analysis.py）共用聊天通道（_request_chat：ANALYSIS_MODEL 主通道，现为
glm-5.3-flash + 思考强度 low；1113 自动回退）、时效判断（should_refresh/TTL）与新闻抓取组件；差异仅在
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
from epd_dashboard.calendar_cn import is_trading_day
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


def quote_phase(now):
    """生成时刻行情快照所处的阶段，提示词据此称呼这份价格与涨跌（2026-11-25 方案 A）。

    "trading"       港股交易时段内：报价是实时价，涨跌幅是今日的（午间休市仍是今日数据）；
    "prev_session"  开盘前或休市日：行情接口返回的还是上一交易日的收盘价与当日涨跌幅。
                    此前提示词一律写成"最新价/今日涨跌"，模型照此把上一交易日的走势写成
                    "今日早盘"（2026-11-25 08:48 盘前按键强制生成的实例）；
    "closed_today"  今日交易时段已结束：报价是今日收盘价。
    时段判定沿用 in_generation_window 的口径（A股交易日历 + 09:31~16:05）。
    """
    if not is_trading_day(now.date()):
        return "prev_session"
    if now.time() < dtime(9, 31):
        return "prev_session"
    if now.time() > HK_SESSION_END:
        return "closed_today"
    return "trading"


def _build_messages(markets, headlines, now, response_errors=()):
    phase = quote_phase(now)
    # 行情未开盘或休市时，接口给的涨跌属于上一交易日：措辞必须跟着改，否则模型把昨天写成今天
    day_word = "上一交易日" if phase == "prev_session" else "今日"
    user_lines = [f"今天是{now.strftime('%Y年%m月%d日 %H:%M')}。"]
    phase_notes = {
        "prev_session": "注意：港股当前未开盘（开盘前或休市），下面的价格与涨跌幅是上一交易日的收盘数据，不是今日行情。",
        "closed_today": "注意：港股今日已收盘，下面的价格与涨跌幅是今日收盘数据。",
    }
    if phase in phase_notes:
        user_lines.append(phase_notes[phase])
    elif dtime(12, 0) < now.time() < dtime(13, 0):
        user_lines.append("注意：港股当前午间休市，下面的价格与涨跌幅是上午收市数据。")
    quote = _find_quote(markets, ZHIPU_CODE)
    if quote and quote.get("price", 0) > 0:
        price_word = {"trading": "最新价", "prev_session": "上一交易日收盘价",
                      "closed_today": "今日收盘价"}[phase]
        user_lines.append(
            f"{ZHIPU_NAME}（港股 {ZHIPU_CODE}）{price_word} {quote['price']:.2f} 港元，"
            f"{day_word}涨跌 {quote.get('chg', 0):+.2f}、涨跌幅 {_fmt_pct(quote.get('pct'))}。"
        )
    else:
        user_lines.append(f"{ZHIPU_NAME}（{ZHIPU_CODE}）暂无最新行情数据。")
    ai_pct = _index_pct(markets, "sz399415")
    sh_pct = _index_pct(markets, "sh000001")
    if ai_pct is not None:
        user_lines.append(f"人工智能指数(399415){day_word} {_fmt_pct(ai_pct)}。")
    if sh_pct is not None:
        user_lines.append(f"上证指数{day_word} {_fmt_pct(sh_pct)}。")
    user = "\n".join(user_lines)

    news_blocks = [
        f"【{label}】相关新闻标题：\n" + "\n".join(f"- {title}" for title in titles)
        for label, titles in headlines.items() if titles
    ]
    if news_blocks:
        user += "\n\n另附刚从新闻聚合搜索到的相关标题：\n\n" + "\n\n".join(news_blocks)
    source = "综合以上数据与你的联网检索结果" if ANALYSIS_WEB_SEARCH else "综合以上数据与你的财经知识"
    subject = "上一交易日走势归因回顾" if phase == "prev_session" else "今日走势归因分析"
    # 字数预算与页4同一排版容量（见 config.ANALYSIS_MAX_CHARS 注释），各节配额加总不得超过
    user += (
        f"\n\n请{source}，写一份智谱AI{subject}。这是给电子墨水屏看的短报告，"
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
        + ("不要把多天前的旧闻当作当日走势的驱动；\n" if phase == "prev_session"
           else "不要把多天前的旧闻当作今日走势的驱动；\n")
        + "3. 智谱AI是港股，注意其交易时段与流动性特点，不与A股涨跌幅直接类比；\n"
        "4. 归因必须与公司或AI行业直接相关且逻辑成立，缺乏明确消息时如实说明，不要编造政策、会议或数字。"
    )
    if phase == "prev_session":
        user += "\n5. 这是上一交易日的走势回顾：正文要写明是上一交易日，不要写成今日或早盘行情。"
    if response_errors:
        user += ("\n\n你刚才的输出未通过校验，逐次失败原因："
                 + "；".join(response_errors)
                 + "。重新输出时严格执行各节字数配额，超配额的小节明显写短——"
                   "宁可精炼也不要贴着上限写。")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


_SENTENCE_END = "。；！？;"
_CLAUSE_END = "，、：:,"


def _visible_length(text):
    """按校验口径计字数：去掉全部空白字符后的长度。"""
    return len(re.sub(r"\s+", "", text))


def _over_limit_sections(text, quotas=STOCK_SECTION_QUOTAS):
    """超配额的小节 → {节名: 超出的字数}；都没超返回空字典。"""
    sections = _split_sections(text)
    result = {}
    for name, quota, _desc in quotas:
        if name in sections:
            excess = _visible_length("".join(sections[name])) - quota
            if excess > 0:
                result[name] = excess
    return result


def _shorten(text, quota):
    """把一段正文截到不超过 quota 个非空白字符。优先断在句末标点，其次断在分句标点并补句号，
    都找不到才硬截加省略号；断点不早于配额的一半，免得为了几个字丢掉大半节。"""
    if _visible_length(text) <= quota:
        return text
    used, cut = 0, len(text)
    for index, char in enumerate(text):
        if not char.isspace():
            used += 1
            if used > quota:
                cut = index
                break
    head = text[:cut]
    floor = int(quota * 0.5)
    sentence = max(head.rfind(mark) for mark in _SENTENCE_END)
    if sentence >= floor:
        return head[:sentence + 1].rstrip()
    clause = max(head.rfind(mark) for mark in _CLAUSE_END)
    if clause >= floor:
        return head[:clause].rstrip() + "。"
    return head.rstrip()[:-1] + "…"


def _shorten_sections(text, over_limit):
    """把 over_limit 列出的各节正文截短成一行（渲染器自己折行）；标题行、空行、其余小节原样保留。
    over_limit: {节名: 配额}。"""
    title = re.compile(r"^【([^】]+)】\s*$")
    lines = text.splitlines()
    out, index = [], 0
    while index < len(lines):
        match = title.match(lines[index].strip())
        if not match:
            out.append(lines[index])
            index += 1
            continue
        out.append(lines[index])
        index += 1
        body = []
        while index < len(lines) and not title.match(lines[index].strip()):
            body.append(lines[index])
            index += 1
        if match.group(1) in over_limit:
            content = "".join(line.strip() for line in body if line.strip())
            out.append(_shorten(content, over_limit[match.group(1)]))
            out.extend(line for line in body if not line.strip())
        else:
            out.extend(body)               # 不截短的小节：正文原样带回（漏掉这一步等于把整节清空，
                                          # 而校验对空节不报错——2026-11-25 测试当场抓到）
    return "\n".join(out)


def _best_salvage(attempts):
    """重试耗尽后的兜底（2026-11-25）：各次回复都只是"小节超字数"时，挑超出最少的一份，
    把超限的小节截短来用，返回 (截短后的文本, 该次响应, 原失败原因)；救不了返回 None。

    缺小节、带 markdown/网址的回复不救——那种文本截短也救不回来。
    背景：此前任何一节超一个字就整篇作废，三次都超就沿用旧报告。实测 glm-5.3 写
    "今日走势"常在 44~55 字（配额 40），2026-11-25 当天两次重写因此全部失败，
    屏上一直是盘前那份过期报告。"""
    quotas = {name: quota for name, quota, _desc in STOCK_SECTION_QUOTAS}
    best = None
    for text, data in attempts:
        error = _response_error(text)
        if not error or not error.startswith("section over limit"):
            continue
        before = _split_sections(text)
        over = _over_limit_sections(text)
        fitted = _shorten_sections(text, {name: quotas[name] for name in over})
        after = _split_sections(fitted)
        # 截短只该动名单里的小节。其余小节若有任何变化——比如被整节清空，而校验对空节
        # 不报错——就宁可不救（2026-11-25 首版 _shorten_sections 正是这样漏掉了正文）
        untouched = all(after.get(name) == lines
                        for name, lines in before.items() if name not in over)
        if not untouched or _response_error(fitted):
            continue
        score = sum(over.values())
        if best is None or score < best[0]:
            best = (score, fitted, data, error)
    return best[1:] if best else None


def _build_result(text, data, markets, now, shortened=False):
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
        "shortened": bool(shortened),      # True = 重试耗尽后截短小节得来的报告（排查用）
    }


def fetch_zhipu_analysis(markets, previous=None, now=None):
    """生成一份智谱AI走势归因分析（逐节配额硬校验，超限带原因重试）。
    结构化输出写入缓存 stock_analysis 字段；重试耗尽仍超配额时，把超限的小节截短来用
    （见 _best_salvage）而不是整篇丢弃；缺小节等救不了的情况仍抛错，
    调用方（cli stock 路径）保留旧值并 WARN，不推坏版面。"""
    now = now or datetime.now()
    key, _org, _proj = _credentials()
    if not key:
        raise RuntimeError("GLM conf missing GLM_KEY")

    headlines = _headlines()
    response_errors = []
    attempts = []                       # 超配额的各次回复：重试耗尽后从中挑一份截短来用
    attempt = 0
    while attempt < STOCK_RETRY_COUNT:
        attempt += 1
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
            code = str(exc)
            if code.startswith("1301") and headlines:
                # 1301 = 内容安全拦截：多半是某条新闻标题触发。去掉新闻标题、只留行情
                # 数据重试一次（不占配额重试次数）；仍失败由调用方沿用旧缓存并 WARN
                print("WARN stock analysis rejected (1301), retry without news headlines",
                      file=sys.stderr)
                headlines = {}
                attempt -= 1
                continue
            # 1113 = 余额不足/无资源包（主通道模型不可用）：回退标准接口 + glm-4-flash 免费兜底
            fallback = ANALYSIS_MODEL_FALLBACK
            if fallback and fallback != ANALYSIS_MODEL and code.startswith("1113"):
                print(f"WARN {ANALYSIS_MODEL} unavailable ({exc}), falling back to "
                      f"{fallback} via standard API", file=sys.stderr)
                text, data = _request_chat(key, fallback, payload_base, GLM_CHAT_URL)
            else:
                raise
        error = _response_error(text)
        if not error:
            return _build_result(text, data, markets, now)
        attempts.append((text, data))
        response_errors.append(error)
        print(f"WARN stock analysis quota violation ({error}), retry "
              f"{attempt}/{STOCK_RETRY_COUNT}", file=sys.stderr)
    salvage = _best_salvage(attempts)
    if salvage:
        fitted, data, error = salvage
        print(f"WARN stock analysis: still over quota after {STOCK_RETRY_COUNT} attempts "
              f"({error}); using the least over-limit report with that section trimmed",
              file=sys.stderr)
        return _build_result(fitted, data, markets, now, shortened=True)
    raise RuntimeError(f"stock analysis failed quota validation after "
                       f"{STOCK_RETRY_COUNT} attempts: {response_errors}")
