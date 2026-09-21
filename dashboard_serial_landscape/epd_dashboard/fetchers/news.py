"""页2新闻：每个栏目按优先级取 RSS 源，单个源失败自动切换下一个。"""
import json
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from epd_dashboard.config import (
    BASE_DIR,
    NEWS_SUMMARY_ENABLED,
    NEWS_SUMMARY_RETAIN,
)
from epd_dashboard.httpclient import http_read

# RSS 是不可信外部输入：标准库会展开内部 DTD 实体（"十亿笑话"可致资源耗尽），
# 优先用 defusedxml 禁用 DTD；缺失时退回标准库并告警（安全加固静默失效不可接受）
try:
    from defusedxml.ElementTree import fromstring as _safe_fromstring
except ImportError:
    _safe_fromstring = None
    print("WARNING: defusedxml not installed, RSS parsing falls back to stdlib (DTD not forbidden)", file=sys.stderr)

NEWS_PER_BAND = 5
CHINANEWS_ROLL_URL = "https://www.chinanews.com.cn/rss/scroll-news.xml"


def _gnews_search(query):
    # Google News 搜索式 feed。注意：主题式(topic)路径在大陆网络基本不可达，
    # 而搜索式路径与 AI 栏目同款、实测可用，故全部统一为搜索式。
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
    )


# 页2新闻：每个栏目按优先级取源，单个源失败自动切换下一个。
# 源配置 2026-08-27 实测修订：
#   - 人民网时政 RSS 冻结于 2025-06、新浪国内/国际/科技 RSS 冻结于 2018 年，均已删除
#   - 中新网滚动为分钟级更新的活跃综合源，但属国内外混合流，
#     国内/国际栏目共用它时按标题关键词分栏（见 _split_band_titles）
# Google 搜索词一律带 when:1d：搜索式 feed 默认按相关度排序，旧文可常驻数日
# （2026-09-11 实测"国内 时政"前15条仅1条在36h内，136小时前的博彩引流文稳居第3，
# 用户连续看到同一垃圾条目多天）；_fetch_titles 再按 pubDate 本地复核兜底。
NEWS_SOURCES = {
    "domestic": [
        ("Google国内", _gnews_search("国内 时政 when:1d")),
        ("中新网滚动", CHINANEWS_ROLL_URL),
    ],
    "international": [
        # 搜索词用国际实体词 OR 组合（2026-09-01 实测对比：100条中96条命中国际词、
        # 0条SEO垃圾；泛词"国际 新闻"只有73条命中且垃圾文排进前3，如"环球国际
        # 新闻怎么获取？…"）。实体词命中的外交动态（如会见外国元首）属正常国际新闻
        ("Google国际", _gnews_search("美国 OR 俄罗斯 OR 乌克兰 OR 以色列 OR 日本 OR 韩国 OR 欧盟 OR 联合国 when:1d")),
        ("中新网滚动", CHINANEWS_ROLL_URL),
    ],
    "ai": [
        ("GoogleAI", _gnews_search("人工智能 when:1d")),
        ("量子位", "https://www.qbitai.com/feed"),
        ("雷锋网", "https://www.leiphone.com/feed"),
    ],
}
NEWS_TITLES = {"domestic": "国内新闻", "international": "国际新闻", "ai": "AI 新闻"}

# ---------- AI 栏新模型发布优先通道 ----------
# AI 栏每次抓取先定向搜"新模型发布"，命中（发布时间在半天内）则置顶第一行；
# 无命中保持原逻辑。Google News 的 when:12h 实测有效（2026-09-03，51条全在窗口内），
# 本地仍按 pubDate 复核时效，两层防护。
MODEL_RELEASE_URL = _gnews_search("大模型 发布 OR 开源 OR 亮相 OR 上线 when:12h")
MODEL_RELEASE_MAX_AGE_HOURS = 12
_RELEASE_VERB_RE = re.compile(r"发布|开源|上线|推出|亮相|首发|官宣")
_MODEL_NAME_RE = re.compile(
    r"大模型|模型|LLM|GPT|Gemini|Claude|Llama|Qwen|通义|文心|DeepSeek|Kimi"
    r"|豆包|混元|盘古|Grok|GLM|Copilot|OpenAI|Anthropic|智谱|MiniMax"
)
# 大会/榜单类标题常含"发布/亮相"但不是模型发布，排除
_RELEASE_NOISE_RE = re.compile(r"大会|峰会|展会|博览会|榜单|排行|评测|盘点|综述")


def _is_model_release_title(title):
    return bool(
        _RELEASE_VERB_RE.search(title)
        and _MODEL_NAME_RE.search(title)
        and not _RELEASE_NOISE_RE.search(title)
    )


def fetch_model_release(now=None):
    """半天内最新的大模型发布标题（纯标题，渲染层打角标）；无命中返回 None。"""
    now = now or datetime.now().astimezone()
    try:
        root = _parse_xml(http_read(MODEL_RELEASE_URL))
    except Exception as exc:
        print(f"WARN news[model_release] fetch failed: {exc}", file=sys.stderr)
        return None
    hits = []
    for item in root.findall(".//item"):
        title = _clean_title(item)
        if not title or not _is_model_release_title(title):
            continue
        try:
            dt = parsedate_to_datetime(item.findtext("pubDate")).astimezone()
        except (TypeError, ValueError):
            continue  # 无发布时间的无法确认"半天内"，宁缺毋滥
        if dt > now or now - dt > timedelta(hours=MODEL_RELEASE_MAX_AGE_HOURS):
            continue
        hits.append((dt, title))
    if not hits:
        return None
    hits.sort(reverse=True)  # 取最新的
    dt, title = hits[0]
    # 返回纯标题：置顶标记由渲染层以角标形式呈现，不占用标题一行的宝贵宽度
    print(f"news[model_release] pinned ({dt.strftime('%H:%M')}): {title[:50]}", file=sys.stderr)
    return title


# ---------- 临时新闻任务（文件驱动，如"华为发布会某机型售价速报"） ----------
# dashboard_serial/temp_news_task.json 字段：
#   enabled 开关；query 搜索词；match 标题匹配正则（IGNORECASE）；require_price 是否要求
#   标题出现价格（数字+元/售价/价格/起售）；band 置顶栏目；badge 角标字（渲染层替代编号）。
# 命中后把标题写回 last_hit 粘性置顶（新闻轮出后仍显示），取消任务 = 删除文件或 enabled=false。
TEMP_TASK_FILE = BASE_DIR / "temp_news_task.json"
# "准确官方售价"的判定：标题必须出现真实价格数字（数字+元），仅"售价/价格"字眼不算；
# 猜价活动/爆料/传闻（"来猜起售价""曝…"）一律排除——用户要的是官方口径
_TEMP_PRICE_DIGITS_RE = re.compile(r"\d[\d,，.]*\s*元")
_TEMP_GUESS_RE = re.compile(r"猜|预测|爆料|传闻|悬念|有奖|福利|疑似|曝")


def _load_temp_task():
    try:
        task = json.loads(TEMP_TASK_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None  # 无任务文件=常态，静默
    except Exception as exc:
        # 文件存在却解析失败必须留痕：静默 None 会让任务"看起来在跑实际没跑"
        print(f"WARN temp task file invalid, task disabled: {exc}", file=sys.stderr)
        return None
    return task if isinstance(task, dict) and task.get("enabled") and task.get("query") else None


def _save_temp_task(task):
    try:
        TEMP_TASK_FILE.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"WARN temp task save failed: {exc}", file=sys.stderr)


def run_temp_task():
    """执行临时新闻任务，返回给 fetch_news 三种信号之一：
    {"title", "band", "badge"} 命中/粘性置顶；{"clear": band} 任务在跑但尚无命中；
    {"off": True} 任务不存在或已停用（调用方负责清理残留的置顶标志）。"""
    task = _load_temp_task()
    if not task:
        return {"off": True}
    band = task.get("band", "domestic")
    badge = task.get("badge", "价")
    match_re = re.compile(task["match"], re.IGNORECASE)

    def _title_ok(title):
        """官方售价命中判定：匹配型号名 + 真实价格数字，排除猜价/爆料类。"""
        return bool(
            match_re.search(title)
            and not _TEMP_GUESS_RE.search(title)
            and (not task.get("require_price", True) or _TEMP_PRICE_DIGITS_RE.search(title))
        )

    try:
        root = _parse_xml(http_read(_gnews_search(task["query"])))
    except Exception as exc:
        print(f"WARN news[temp_task] fetch failed: {exc}", file=sys.stderr)
        root = None
    hit = None
    for item in (root.findall(".//item") if root is not None else []):
        title = _clean_title(item)
        if title and _title_ok(title):
            hit = title
            break
    if not hit:
        last = task.get("last_hit")
        if last and _title_ok(last):
            hit = last  # 粘性：命中过的标题不随新闻流轮出消失，直到任务取消
        elif last:
            task.pop("last_hit", None)  # 历史命中不再符合规则（如规则刚收紧），清除
            _save_temp_task(task)
    if hit:
        if task.get("last_hit") != hit:
            task["last_hit"] = hit
            _save_temp_task(task)
        print(f"news[temp_task] pinned: {hit[:50]}", file=sys.stderr)
        return {"title": hit, "band": band, "badge": badge}
    return {"clear": band}


# 媒体栏目标签前缀（如 "时政微观察丨" "国际新闻早知道丨" "学习卡丨"）：
# 开头 ≤12 字的品牌词 + 丨/｜/| 分隔符，对墨水屏纯属浪费横向空间，剥掉只留正文。
# 通用识别而非枚举（新栏目名层出不穷）；锚定开头并限长 12 字，正文中间的丨不受影响。
# 品牌栏前缀要求纯汉字：避免误伤 "智谱AI丨xxx" "5G丨xxx" 这类主体在前的标题；
# 另剥开头的 "【栏目】" 前缀。
_COLUMN_PREFIX_RE = re.compile(r"^[\u4e00-\u9fff]{2,12}[丨｜|]\s*")
_BRACKET_PREFIX_RE = re.compile(r"^\s*【[^】]{1,10}】\s*")
# 来源尾巴的粘着变体："标题-国内频道""标题- 时局"（短横无空格或只在后）。
# 限短尾巴（≤12字符）避免误伤 "——习近平治国理政纪实" 这类长副题；不含全角破折号。
_GLUED_SUFFIX_RE = re.compile(r"\s*-\s*[\u4e00-\u9fffA-Za-z0-9.]{1,12}$")


def _strip_column_prefix(title):
    # 连剥两轮以覆盖 "【早知道】时政微观察丨正文" 的叠用；剥空则保留原标题
    for _ in range(2):
        stripped = _COLUMN_PREFIX_RE.sub("", title)
        stripped = _BRACKET_PREFIX_RE.sub("", stripped, count=1)
        if not stripped or stripped == title:
            return stripped or title
        title = stripped
    return title


def _clean_title(item):
    """取条目标题；去 Google 来源后缀与媒体栏目标签前缀，只留正文。"""
    title = (item.findtext("title") or "").replace("\u200b", "").replace("\ufeff", "").strip()
    if " - " in title:
        title = title.split(" - ", 1)[0].strip()
    # 粘着来源尾巴（"-国内频道""- 时局"）：剥短尾巴，剥空则保留原标题
    stripped = _GLUED_SUFFIX_RE.sub("", title).strip()
    return _strip_column_prefix(stripped or title)


def _parse_xml(payload):
    """解析 RSS，禁用 DTD 实体扩展（defusedxml 缺失时退回标准库，启动时已告警）。"""
    if _safe_fromstring is not None:
        return _safe_fromstring(payload)
    return ET.fromstring(payload)


# 栏目新闻时效窗（小时）：查询侧 when:1d 为主防护，本地按 pubDate 复核兜底（两层，
# 同新模型置顶通道）。无 pubDate 的条目无法确认新鲜度，宁缺毋滥一并丢弃。
NEWS_MAX_AGE_HOURS = 36


def _fresh_items(url):
    """产出通过时效过滤的 (item, 标题)：无发布时间或超窗条目丢弃（见 NEWS_MAX_AGE_HOURS）。"""
    now = datetime.now().astimezone()
    root = _parse_xml(http_read(url))
    for item in root.findall(".//item"):
        title = _clean_title(item)
        if not title:
            continue
        try:
            dt = parsedate_to_datetime(item.findtext("pubDate")).astimezone()
        except (TypeError, ValueError):
            continue
        if dt > now or now - dt > timedelta(hours=NEWS_MAX_AGE_HOURS):
            continue
        yield item, title


def _fetch_titles(url):
    """取条目标题，超出时效窗或无发布时间的条目丢弃（防相关度排序下的旧文常驻）。"""
    return [title for _item, title in _fresh_items(url)]


# RSS 自带正文的字段（WordPress 系常见），用于 AI 摘要免抓文章页
_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"


def _feed_body(item):
    """RSS 自带正文（content:encoded 或 description），剥 HTML；不足 150 字视为无正文。"""
    raw = item.findtext(_CONTENT_NS) or item.findtext("description") or ""
    text = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", raw))
    return text if len(text) >= 150 else ""


def _fetch_entries(url, source_name):
    """[(标题, 内容载荷|None)]：AI 摘要的正文来源——中新网/量子位给文章链接
    （"link"，抓页面全文），雷锋网给 feed 自带正文（"body"），Google 等纯标题源为 None。"""
    entries = []
    for item, title in _fresh_items(url):
        if source_name.startswith("中新网") or source_name == "量子位":
            link = (item.findtext("link") or "").strip()
            entries.append((title, ("link", link) if link else None))
        elif source_name == "雷锋网":
            body = _feed_body(item)
            entries.append((title, ("body", body) if body else None))
        else:
            entries.append((title, None))
    return entries


def _fetch_annotated_titles(url):
    """取标题并追加发布时间标注（今天HH:MM/昨天/N天前），供 AI 区分消息新旧。

    Google News 搜索结果默认按相关度排序，会混入数周前的旧文；
    配合查询里的 when:Nd 时间过滤，标注让模型能进一步识别新旧冲突时以新为准。
    """
    root = _parse_xml(http_read(url))
    now = datetime.now().astimezone()
    titles = []
    for item in root.findall(".//item"):
        title = _clean_title(item)
        if not title:
            continue
        try:
            dt = parsedate_to_datetime(item.findtext("pubDate")).astimezone()
            age = (now.date() - dt.date()).days
            label = "今天%H:%M" if age == 0 else "昨天" if age == 1 else f"{age}天前"
            titles.append(f"{title}（{dt.strftime(label)}）")
        except (TypeError, ValueError):
            titles.append(title)
    return titles


# 中新网滚动是国内外混合流，无法按条目顺序区分栏目。按标题关键词过滤分栏：
# 命中国际词的进国际栏；都不命中的默认视为国内（滚动流以国内为主，个别 sports/社会新闻归国内可接受）
_INTERNATIONAL_KEYWORDS = (
    "美国", "俄罗斯", "乌克兰", "以色列", "伊朗", "日本", "韩国", "朝鲜", "印度",
    "英国", "法国", "德国", "欧盟", "联合国", "北约", "越南", "菲律宾", "泰国",
    "新加坡", "马来西亚", "印尼", "澳大利亚", "加拿大", "巴西", "阿根廷", "中东",
    "巴勒斯坦", "叙利亚", "古巴", "委内瑞拉", "墨西哥", "尼泊尔", "缅甸", "柬埔寨",
    "国际", "全球", "外媒", "白宫", "克里姆林宫", "特朗普", "普京", "泽连斯基", "马斯克",
)
# 明显的国内时政词优先级更高：即使含"美国"等词也先按国内算（如中美会谈以中方通稿措辞命名）
_DOMESTIC_PRIORITY_KEYWORDS = ("中央", "全国", "国务院", "国家主席", "总理", "部委", "省", "市委", "国新办")


def _is_international_title(title):
    """国内优先词一票否决，否则要求命中国际词。"""
    if any(k in title for k in _DOMESTIC_PRIORITY_KEYWORDS):
        return False
    return any(k in title for k in _INTERNATIONAL_KEYWORDS)


def _split_band_pairs(pairs):
    """把混合滚动流的 (标题, 链接) 分成 (国内, 国际) 两组，分栏规则同关键词守卫。"""
    domestic, international = [], []
    for pair in pairs:
        (international if _is_international_title(pair[0]) else domestic).append(pair)
    return domestic, international


# SEO 垃圾文特征：How-to 措辞与引流词，常见于宽泛搜索词的结果
# （如 "环球国际新闻怎么获取？最新消息与可靠渠道详解"）；2026-09-11 实测博彩类
# 引流文借时政关键词混入国内栏前排且常驻多日（"58彩官网代理：深度解析…"），
# 增补博彩引流词。任何栏目命中即丢弃
_SEO_JUNK_RE = re.compile(
    r"怎么|如何|怎样|在线观看|完整版|免费领|入口|攻略"
    r"|官网代理|彩官网|博彩|娱乐城|下注|投注|开户送"
)
# 日更 digest 标题（如 "美国之音中文广播 (2026年9月11日)"）：标题本身零信息量且
# 每天换个日期复现，按结尾括号日期识别丢弃
_DIGEST_TITLE_RE = re.compile(r"[（(]\d{4}年\d{1,2}月\d{1,2}日[）)]$")


def _polish_band_titles(key, titles):
    """栏目内容质量统一收口：去 SEO 垃圾文/博彩引流文/日更 digest 标题与重复标题
    （多源同题剥掉来源尾巴后完全相同）；国际栏额外过关键词守卫——定向搜索词仍可能
    混入纯国内文（如 "国新办发布会……"）。"""
    titles = [t for t in titles if not _SEO_JUNK_RE.search(t) and not _DIGEST_TITLE_RE.search(t)]
    if key == "international":
        titles = [t for t in titles if _is_international_title(t)]
    return list(dict.fromkeys(titles))


def _content_capable(source_name):
    """该源能否为 AI 摘要提供正文/链接载荷（中新网文章页、量子位文章页、雷锋网 feed 正文）。"""
    return source_name.startswith(("中新网", "量子位", "雷锋网"))


# 摘要启用时，可提供正文的源即使不足额（≥3 条）也优先于条数更多的裸标题源：
# 展示形态一致性（全栏精华行）比凑满 5 条更重要；不足 3 条才退回裸标题源
_CONTENT_SOURCE_MIN_TITLES = 3


def _ordered_sources(sources):
    """AI 摘要启用时，能提供正文的源排前，Google 裸标题源退居备胎。

    源序不受 summarize 开关影响（交互切页也保持同序），保证各轮标题集合稳定、
    缓存的摘要行能持续命中。
    """
    if not NEWS_SUMMARY_ENABLED:
        return sources
    return ([s for s in sources if _content_capable(s[0])]
            + [s for s in sources if not _content_capable(s[0])])


def fetch_news(previous=None, summarize=False):
    news = dict(previous) if isinstance(previous, dict) else {}
    got_any = False
    # 同一个 URL 只抓一次（国内+国际共用中新网滚动时）
    fetched = {}
    # AI 摘要：GLM 调用只在后台 full 轮播/手动 --force 时做（summarize=True），
    # 交互切页走 allow_new=False 纯缓存换装，不联网、不等模型
    summaries = news.get("summaries") if isinstance(news.get("summaries"), dict) else {}
    raw_titles = {}
    for key, sources in NEWS_SOURCES.items():
        sources = _ordered_sources(sources)
        best_titles, best_content, used = [], {}, ""
        best_rank = (-1, -1)
        # 两轮取源，满额（NEWS_PER_BAND 条）即停；不足额时第二轮只重试因异常
        # 失败的源（成功过的滚动流分钟级不变，重抓无意义）。Google 搜索式 feed
        # 常间歇性 SSL 中断，一次失败落到中新网后混合流按关键词分栏又常分不满
        # 国际栏，补一轮重试可救回多数情况；仍不足则取条数最多的源。
        for attempt in range(2):
            for source_name, url in sources:
                # 同一 URL 只下载一次；缓存过的仍要走本栏的处理（国内+国际共用中新网
                # 滚动，混合流按栏分栏各取所需——跳过处理会让后到的栏永远拿不到它）
                if url not in fetched:
                    try:
                        fetched[url] = _fetch_entries(url, source_name)
                    except Exception as exc:
                        print(f"WARN news[{key}] {source_name} try{attempt + 1} failed: {exc}", file=sys.stderr)
                        continue
                pool = fetched[url]
                # 中新网滚动是混合流，按关键词分栏；Google/量子位/雷锋网等已定向的源直接用
                if source_name.startswith("中新网"):
                    domestic_pairs, international_pairs = _split_band_pairs(pool)
                    band_entries = domestic_pairs if key == "domestic" else international_pairs
                else:
                    band_entries = pool
                titles = [title for title, _payload in band_entries]
                titles = _polish_band_titles(key, titles)
                # 选源：有正文能力且 ≥3 条的源优先（rank 首位 1），其余按条数。
                # 内容源已排在前面，满额即停的早退逻辑不受影响
                capable = (NEWS_SUMMARY_ENABLED and _content_capable(source_name)
                           and len(titles) >= _CONTENT_SOURCE_MIN_TITLES)
                rank = (1 if capable else 0, len(titles))
                if rank > best_rank:
                    best_rank = rank
                    best_titles = titles
                    best_content = {t: p for t, p in band_entries if p and p[1]}
                    used = source_name
                if len(best_titles) >= NEWS_PER_BAND:
                    break
            if len(best_titles) >= NEWS_PER_BAND:
                break
        if key == "ai":
            # 新模型发布优先通道：半天内有发布则置顶第一行（纯标题，渲染层打角标），无命中维持原逻辑。
            # 数据源标签保持原样不加后缀：头部空间有限，置顶身份由"新"角标表达
            pinned = fetch_model_release()
            if pinned:
                best_titles = [pinned] + [t for t in best_titles if t != pinned]
                if NEWS_SUMMARY_ENABLED and pinned not in best_content:
                    # 置顶行来自 Google 通道无正文：做标题压缩，防长标题在屏上截断成半句
                    best_content[pinned] = ("title", pinned)
            # 置顶标志随本次抓取结果刷新：供渲染层把第一行编号换成"新"角标
            news["ai_pinned"] = bool(pinned)
        if best_titles:
            news[key] = best_titles[:NEWS_PER_BAND]
            raw_titles[key] = list(news[key])
            news[f"{key}_source"] = used
            got_any = True
            print(f"news[{key}] <- {used} ({len(news[key])}条)", file=sys.stderr)
            if NEWS_SUMMARY_ENABLED and not _content_capable(used):
                # 胜出源是裸标题源（Google 兜底轮）：标题本身过压缩通道，防长标题截断半句
                best_content = {t: ("title", t) for t in news[key]}
            if NEWS_SUMMARY_ENABLED:
                # 摘要换装：成功条目替换为 ≤22字 精华行（用满屏宽），失败条目回退原标题；
                # 源标签带"AI摘要N/M"便于屏上直观掌握各栏健康度
                from epd_dashboard.fetchers.summarize import apply_summaries  # 函数内导入规避循环
                lines, summaries, done, total, fresh = apply_summaries(
                    news[key], best_content, summaries, allow_new=summarize)
                news[key] = lines
                news[f"{key}_source"] = f"{used}·AI摘要{done}/{total}"
                if summarize:
                    print(f"news[{key}] ai summary {done}/{total}, 新摘{fresh}", file=sys.stderr)
    if NEWS_SUMMARY_ENABLED and got_any:
        # 摘要缓存修剪：在栏条目全保留；出栏条目按"最近插入优先"保留一段（dict 保序，
        # 新标题后插入）——国际栏等会在中新网/Google 间摆动，标题常"出栏又回栏"，
        # 全剪掉会造成同一新闻反复调模型重摘。出栏保留量有上限，防缓存无限增长
        in_band = {t for titles in raw_titles.values() for t in titles}
        kept = {t: v for t, v in summaries.items() if t in in_band}
        overflow = [t for t in summaries if t not in in_band]
        for title in overflow[-NEWS_SUMMARY_RETAIN:]:
            kept[title] = summaries[title]
        news["summaries"] = kept
    # 临时新闻任务：命中（或粘性）置顶目标栏目第一行；off 时清理残留标志，防已取消任务的角标滞留
    pin = run_temp_task()
    if pin and pin.get("title"):
        band = pin["band"]
        titles = list(news.get(band) or [])
        if pin["title"] not in titles:
            titles.insert(0, pin["title"])
        news[band] = titles[:NEWS_PER_BAND]
        news[f"{band}_pinned"] = True
        news[f"{band}_badge"] = pin["badge"]
    elif pin and pin.get("clear"):
        band = pin["clear"]
        news[f"{band}_pinned"] = False
        news[f"{band}_badge"] = ""
    elif pin and pin.get("off"):
        for key in NEWS_SOURCES:
            if key != "ai":  # ai 栏的新模型角标由其自身通道每次刷新时管理
                news[f"{key}_pinned"] = False
                news[f"{key}_badge"] = ""
    if got_any:
        news["updated"] = datetime.now().strftime("%H:%M")
        news["stale"] = False
    else:
        news["stale"] = True
    return news
