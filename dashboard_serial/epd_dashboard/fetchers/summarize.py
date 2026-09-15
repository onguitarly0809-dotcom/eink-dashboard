"""页2新闻 AI 摘要：文章全文 -> GLM 逐篇通读 -> 一行精华（三栏通用）。

正文来源两种载荷：("link", url) 抓文章页（中新网/量子位）；("body", text) 用
RSS 自带正文（雷锋网）。出口边界与 SSRF 整改姿态一致：
- 文章页仅限固定域名白名单：scheme+域名前置校验，解析 IP 必须公网，重定向逐跳同校验；
- 逐篇独立调用 GLM：一篇被内容安全拦截（1301）只损失一篇，回退原标题展示；
- 摘要结果按标题缓存在 news["summaries"]，新标题才调模型；确定性失败负缓存
  （缓存值=原标题）防止 1301 重试风暴；网络类暂时失败不缓存，下轮再试；
- 交互切页走 allow_new=False 纯缓存换装，不联网、不等 GLM。
"""
import ipaddress
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from epd_dashboard.config import (
    ANALYSIS_API_URL,
    ANALYSIS_MODEL,
    NEWS_SUMMARY_BODY_CHARS,
    NEWS_SUMMARY_BUDGET_S,
    NEWS_SUMMARY_LINE_CHARS,
    NEWS_SUMMARY_TIMEOUT_S,
)

# 允许抓文章页的域名（均已登记在 ALLOWED_HTTP_HOSTS；Google 跳转的任意媒体不在此列）
ARTICLE_HOSTS = {"www.chinanews.com.cn", "www.qbitai.com"}

_SYSTEM_PROMPT = (
    "你是电子墨水屏的新闻编辑，任务是把一篇新闻浓缩成一行信息行。规则："
    f"1. 不超过{NEWS_SUMMARY_LINE_CHARS}个字，尽量用满这个长度承载最关键的事实；"
    "2. 人名、机构名、数字必须与原文完全一致，禁止改写或脑补；"
    "3. 不要出现「据报道/据悉/文章称」等元话语，直接陈述事实；"
    "4. 只输出这一行文字：不带引号、编号，结尾不加句号。"
    "给了正文就通读正文后归纳；只给了标题（无正文）就把标题本身压缩去冗余，不得添加标题外的信息。"
)


def _assert_url_allowed(url):
    """出口边界校验：仅 https + 白名单域名，且域名解析到的所有 IP 必须是公网地址。

    （解析与连接之间存在理论上的 DNS rebinding 窗口；白名单为固定公网站点，
    此处以域名白名单+公网 IP 校验作为与项目 ALLOWED_HTTP_HOSTS 同级的防护。）
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ARTICLE_HOSTS:
        raise ValueError(f"article url not allowed: {parsed.scheme}://{parsed.hostname}")
    addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, 443)}
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError(f"article host resolves to non-public ip: {parsed.hostname} -> {address}")


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """重定向逐跳校验：新地址不过 _assert_url_allowed 就拒绝跟随。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_url_allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_ValidatingRedirectHandler)


class _ParagraphCollector(HTMLParser):
    """收集 <p> 段落文本；<script>/<style> 内容跳过。"""

    def __init__(self):
        super().__init__()
        self.paragraphs = []
        self._current = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "p" and not self._skip:
            self._current = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "p" and not self._skip:
            text = re.sub(r"\s+", "", "".join(self._current))
            if len(text) >= 20:  # 导航/版权等碎屑段落很短，按长度过滤
                self.paragraphs.append(text)
            self._current = []

    def handle_data(self, data):
        if not self._skip:
            self._current.append(data)


def _article_body(url):
    """抓文章页并抽正文。出口校验见 _assert_url_allowed；网络错误向上传播。"""
    _assert_url_allowed(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with _OPENER.open(request, timeout=8) as response:
        html = response.read().decode("utf-8", "ignore")
    collector = _ParagraphCollector()
    collector.feed(html)
    body = "".join(collector.paragraphs)
    if len(body) < 200:  # 结构变化导致 <p> 抽取失效时退回全页剥标签
        stripped = re.sub(rb"<(script|style)[^>]*>.*?</\1>", b" ", html.encode(), flags=re.S | re.I)
        body = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", stripped.decode("utf-8", "ignore")))
    return body[:NEWS_SUMMARY_BODY_CHARS]


def _clean_summary_line(text):
    """取首行，剥引号/围栏/空白与项目符号。不在此处截断——长度治理见 _smart_cut。"""
    line = (text or "").strip().splitlines()[0] if text and text.strip() else ""
    return line.strip("` \u201c\u201d\"'\u300c\u300d\u2022- ")


def _smart_cut(line):
    """超长行的本地保形截断：预算内取最后一个自然边界（标点/空格），避免切在词中间。

    模型重压后仍超长才走到这里；找不到边界时退回硬切（保显示不溢出）。
    """
    limit = NEWS_SUMMARY_LINE_CHARS
    if len(line) <= limit:
        return line
    head = line[:limit]
    for i in range(len(head) - 1, NEWS_SUMMARY_LINE_CHARS // 2, -1):
        if head[i] in "，。、；：！？,. ":
            return head[:i].rstrip("，。、；：！？,. ")
    return head


def _summarize_one(title, payload, key):
    """摘要单篇。payload: ("link", url) 抓文章页；("body", text) 用 RSS 自带正文；
    ("title", text) 无正文通道（如新模型置顶行）只压缩标题本身防屏上截断半句。
    返回摘要行；确定性失败（1301/余额/空输出）返回 None 由调用方负缓存；
    网络类异常向上传播，调用方按暂时性失败处理（本轮显示原标题，下轮重试）。"""
    from epd_dashboard.fetchers.analysis import _request_chat  # 函数内导入避免 news->analysis 循环

    if payload[0] == "link":
        body = _article_body(payload[1])
    elif payload[0] == "body":
        body = payload[1][:NEWS_SUMMARY_BODY_CHARS]
    else:
        body = ""
    if body:
        content = f"标题：{title}\n正文：{body}"
    else:
        content = f"标题：{title}\n（无正文，压缩标题本身）"
    payload_request = {
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "temperature": 0.2,
    }
    try:
        text, _resp = _request_chat(key, ANALYSIS_MODEL, payload_request, ANALYSIS_API_URL,
                                    timeout=NEWS_SUMMARY_TIMEOUT_S)
    except RuntimeError as exc:  # GLM 业务错误（1301 内容安全/1113 余额/空回复）
        print(f"WARN summary GLM rejected ({str(exc)[:24]}), fallback title", file=sys.stderr)
        return None
    line = _clean_summary_line(text)
    if len(line) > NEWS_SUMMARY_LINE_CHARS:
        # 模型偶尔无视字数约束：追加一轮对话让它把自己的输出压短，比本地切词保真；
        # 重试失败不致命，走 _smart_cut 兜底
        shorten = {
            "messages": payload_request["messages"] + [
                {"role": "assistant", "content": line},
                {"role": "user", "content": f"这一行有{len(line)}字，超过{NEWS_SUMMARY_LINE_CHARS}字上限。"
                                            f"请压缩到{NEWS_SUMMARY_LINE_CHARS}字以内：只删冗余，"
                                            "保留最核心事实，人名数字不变，只输出这一行。"},
            ],
            "temperature": 0.2,
        }
        try:
            text2, _resp2 = _request_chat(key, ANALYSIS_MODEL, shorten, ANALYSIS_API_URL,
                                          timeout=NEWS_SUMMARY_TIMEOUT_S)
            shorter = _clean_summary_line(text2)
            if shorter:
                line = shorter
        except Exception:
            pass
    return _smart_cut(line)


def apply_summaries(titles, content_map, cache, allow_new=True):
    """给栏目标题换装摘要行（三栏通用）。

    titles: 该栏目本轮要展示的标题；content_map: 标题->内容载荷；cache: 共享的
    {标题: 摘要行} 缓存（负缓存条目的值就是原标题本身）。缓存命中的条目不调模型，
    只有新增标题才走 GLM——去重的第一道闸门。修剪（保留多少出栏条目）由调用方做。
    allow_new=False 时只查缓存换装，不联网不调 GLM（交互切页快速路径）。
    返回 (展示行列表, 缓存, 摘要成功数, 总数, 本轮实际新调用模型次数)。
    """
    from epd_dashboard.fetchers.glm import _credentials  # 同上，规避加载期循环

    if not allow_new:
        lines = [cache.get(title) or title for title in titles]
        done = sum(1 for t in titles if cache.get(t) not in (None, t))
        return lines, cache, done, len(titles), 0

    key, _org, _proj = _credentials()
    deadline = time.monotonic() + NEWS_SUMMARY_BUDGET_S
    fresh = 0
    for title in titles:
        if title in cache:
            continue  # 之前摘过（含负缓存）：直接用缓存，不重复调模型
        payload = content_map.get(title)
        if not (key and payload and payload[1]):
            cache[title] = title  # 无凭据/无正文载荷（源是裸标题源）：显示原标题，不再重试
            continue
        if time.monotonic() > deadline:
            break  # 预算尽：剩余条目本轮展示原标题（未缓存），下轮继续
        try:
            line = _summarize_one(title, payload, key)
            fresh += 1  # 实际发生了一次模型调用（无论成败）
        except Exception as exc:  # 网络类暂时失败：跳过这篇继续（单篇超时不连坐全栏），
            # 不缓存，下轮重试；总时长由预算守卫兜底
            print(f"WARN summary transient ({type(exc).__name__}), keep title", file=sys.stderr)
            continue
        cache[title] = line if line else title  # 确定性失败负缓存为原标题
    lines = [cache.get(title) or title for title in titles]
    summarized = sum(1 for t in titles if cache.get(t) not in (None, t))
    return lines, cache, summarized, len(titles), fresh
