"""页4认知洞察：多领域轮换生成，并持久化历史主题去重。"""
import re
from datetime import datetime

from epd_dashboard.config import (
    ANALYSIS_API_URL,
    ANALYSIS_MODEL,
    ANALYSIS_MODEL_FALLBACK,
    GLM_CHAT_URL,
    INSIGHT_MAX_CHARS,
    INSIGHT_RECENT_TOPICS,
    INSIGHT_RETRY_COUNT,
    INSIGHT_TOPIC_HISTORY,
)
from epd_dashboard.fetchers.analysis import _request_chat
from epd_dashboard.fetchers.glm import _credentials

SYSTEM_PROMPT = (
    "你是一位中文认知科普编辑，熟悉脑科学、心理学、学习科学与行为设计。"
    "擅长把有实证研究基础的知识讲得像日常聊天一样清楚、具体、有画面感。"
    "内容必须准确、克制，不把结论夸大成万能规律，也不使用鸡汤式说教。"
)
REQUIRED_SECTIONS = (
    "【主题名称】",
    "【所属领域】",
    "【核心知识】",
    "【背后的机制】",
    "【生活里的样子】",
    "【怎么用起来】",
)
TOPIC_DOMAINS = (
    "脑科学知识",
    "认知提升",
    "情绪管理",
    "心理学现象",
    "学习方法",
    "行为设计",
    "决策与判断",
    "专注与休息",
)
CLICHE_TOPICS = (
    "巴纳姆效应",
    "光环效应",
    "确认偏误",
    "幸存者偏差",
    "破窗效应",
    "皮格马利翁效应",
    "棉花糖实验",
)


def _topic_key(topic):
    """把主题规范化成去重键：忽略中英文括注、空白和标点。"""
    text = str(topic).strip().lower()
    text = re.sub(r"[（(][^（）()]*[)）]", "", text)
    text = re.sub(r"[\s\W_]+", "", text)
    return text


def _recent_topics(previous):
    if not isinstance(previous, dict):
        return []
    topics = previous.get("recent_topics")
    if not isinstance(topics, list):
        topics = [previous.get("topic")] if previous.get("topic") else []
    return [str(topic).strip() for topic in topics if str(topic).strip()][:INSIGHT_RECENT_TOPICS]


def _topic_history(previous):
    """返回去重后的历史主题，最新在前；兼容旧缓存的 recent_topics。"""
    if not isinstance(previous, dict):
        return []
    raw = []
    if previous.get("topic"):
        raw.append(str(previous["topic"]).strip())
    history = previous.get("topic_history")
    if isinstance(history, list):
        raw.extend(str(topic).strip() for topic in history if str(topic).strip())
    raw.extend(_recent_topics(previous))
    result = []
    seen = set()
    for topic in raw:
        key = _topic_key(topic)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(topic)
    return result[:INSIGHT_TOPIC_HISTORY]


def _next_domain(previous):
    """每次触发都轮换到下一个领域；旧缓存或未知领域从脑科学开始。"""
    current = previous.get("domain") if isinstance(previous, dict) else ""
    try:
        index = TOPIC_DOMAINS.index(str(current))
    except ValueError:
        index = -1
    return TOPIC_DOMAINS[(index + 1) % len(TOPIC_DOMAINS)]


def _build_messages(previous, now, domain, rejected_topics=()):
    history = _topic_history(previous)
    avoid_items = list(dict.fromkeys((*CLICHE_TOPICS, *history, *rejected_topics)))
    avoid = "、".join(avoid_items)
    retry_note = ""
    if rejected_topics:
        retry_note = (
            "\n\n你刚才的输出未通过格式校验或主题重复："
            + "、".join(rejected_topics)
            + "。重新输出时必须从第一个小节标题开始，六个小节各出现一次且顺序正确；"
            + "如果主题重复，必须换一个同领域内完全不同的主题，不能只是换说法、换中英文名或换标点。"
        )
    user = (
        f"今天是{now.strftime('%Y年%m月%d日 %H:%M')}。"
        f"本轮固定领域是“{domain}”。请在该领域内选择一个有意思、非陈词滥调的主题，避开：{avoid}。"
        "历史主题绝对不能再次输出；如果只是同义词、中英文名不同或标点不同，也视为重复。"
        "优先选择有实证研究基础、能解释日常具体行为、略带反直觉的主题；"
        "不要为了新奇选择缺乏共识或争议过大的概念。\n\n"
        "这是给480x800电子墨水屏看的短科普，正文（不含小节标题）严格控制在"
        f"{INSIGHT_MAX_CHARS}字以内，六个小节标题独占一行并用【】包裹，配额如下：\n"
        "-【主题名称】不超过18字：只写中文名，不括注英文名；\n"
        f"-【所属领域】只写“{domain}”原文，不添加说明；\n"
        "-【核心知识】不超过100字：给出这条知识的核心内容；\n"
        "-【背后的机制】不超过180字：把机制讲成自然的因果链，并说明边界条件；\n"
        "-【生活里的样子】不超过130字：一个具体、贴近日常的完整场景；\n"
        "-【怎么用起来】不超过70字：给出可操作的识别或调整方法。\n"
        "要求：\n"
        "1. 每节标题后另起一行写正文，内容连贯，不要markdown符号、表情、网址或参考文献；\n"
        "2. 语气口语化但不说教：像给聪明的朋友解释，不像上课，也不是在写文案；"
        "句子尽量短，前后要有明确衔接，不用“首先/其次/总之”这种机械连接；\n"
        "3. 机制要讲因果，不只用案例重复现象；生活例子要具体到时间、场景和动作；\n"
        "4. 脑科学解释不得把复杂行为简化成单一脑区；不得虚构实验数字、研究者姓名或年代；"
        "不确定时写“通常认为”。"
        + retry_note
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _normalize_text(text):
    lines = []
    started = False
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*#").strip()
        if not line:
            continue
        matched = False
        for section in REQUIRED_SECTIONS:
            if section in line:
                started = True
                _before, after = line.split(section, 1)
                lines.append(section)
                if after.strip():
                    lines.append(after.strip())
                matched = True
                break
        if not started:
            continue
        if not matched:
            lines.append(line)
    return "\n".join(lines)


def _split_sections(text):
    sections = {}
    current = None
    for line in text.splitlines():
        if line in REQUIRED_SECTIONS:
            if line in sections:
                return None, "duplicate section"
            sections[line] = []
            current = line
        elif current is None:
            continue
        else:
            sections[current].append(line)
    return sections, None


def _extract_topic(text):
    sections, _error = _split_sections(text)
    body = (sections or {}).get(REQUIRED_SECTIONS[0], [])
    if not body:
        return ""
    topic = re.sub(r"[（(][^（）()]*[)）]", "", body[0])
    return topic.strip().strip("“”\"'")


def _response_error(text, expected_domain):
    """返回格式错误说明；空字符串表示格式可用。"""
    sections, error = _split_sections(text)
    if error:
        return error
    missing = [section for section in REQUIRED_SECTIONS if section not in sections]
    if missing:
        return "missing sections: " + ", ".join(missing)
    if list(sections) != list(REQUIRED_SECTIONS):
        return "sections out of order"
    topic_body = sections[REQUIRED_SECTIONS[0]]
    domain_body = sections[REQUIRED_SECTIONS[1]]
    if len(topic_body) != 1:
        return "topic must be one line"
    if len(domain_body) != 1:
        return "domain must be one line"
    topic = topic_body[0].strip()
    domain = domain_body[0].strip()
    if not topic:
        return "missing topic"
    if domain != expected_domain:
        return "unexpected domain"
    if len(re.sub(r"\s+", "", topic)) > 18:
        return "topic too long"
    if any(not lines for lines in sections.values()):
        return "empty section"
    body_chars = sum(
        len(re.sub(r"\s+", "", line))
        for lines in sections.values()
        for line in lines
    )
    if body_chars > INSIGHT_MAX_CHARS:
        return "body too long"
    if re.search(r"https?://|\*\*", text):
        return "markdown or url"
    return ""


def fetch_insight(previous=None, now=None):
    """生成一份多领域认知洞察，结构化输出写入缓存 analysis 字段。"""
    now = now or datetime.now()
    key, _org, _proj = _credentials()
    if not key:
        raise RuntimeError("GLM conf missing GLM_KEY")
    domain = _next_domain(previous)
    history = _topic_history(previous)
    history_keys = {_topic_key(topic) for topic in (*CLICHE_TOPICS, *history)}
    rejected_topics = []
    response_errors = []
    text = ""
    data = {}
    topic = ""
    for _ in range(INSIGHT_RETRY_COUNT):
        payload = {
            "messages": _build_messages(previous, now, domain, rejected_topics),
            "stream": False,
        }
        try:
            text, data = _request_chat(key, ANALYSIS_MODEL, payload, ANALYSIS_API_URL)
        except RuntimeError as exc:
            if ANALYSIS_MODEL_FALLBACK and ANALYSIS_MODEL_FALLBACK != ANALYSIS_MODEL and str(exc).startswith("1113"):
                text, data = _request_chat(key, ANALYSIS_MODEL_FALLBACK, payload, GLM_CHAT_URL)
            else:
                raise
        text = _normalize_text(text)
        topic = _extract_topic(text)
        topic_key = _topic_key(topic)
        format_error = _response_error(text, domain)
        if format_error or not topic_key:
            response_errors.append(format_error or "empty topic")
            rejected_topics.append(topic or "格式不完整")
            if topic_key:
                history_keys.add(topic_key)
            continue
        if topic_key not in history_keys:
            break
        history_keys.add(topic_key)
        rejected_topics.append(topic)
        response_errors.append("duplicate topic")
    else:
        details = []
        for topic, error in zip(rejected_topics, response_errors):
            details.append(f"{topic or '未知主题'}（{error}）")
        raise RuntimeError("insight response invalid after retries: " + "；".join(details))

    new_history = [topic] + [item for item in history if _topic_key(item) != _topic_key(topic)]
    new_history = list(dict.fromkeys(new_history))[:INSIGHT_TOPIC_HISTORY]
    usage = data.get("usage") or {}
    return {
        "kind": "insight",
        "domain": domain,
        "topic": topic,
        "text": text,
        "model": data.get("model") or ANALYSIS_MODEL,
        "topic_history": new_history,
        "recent_topics": new_history[:INSIGHT_RECENT_TOPICS],
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "updated": now.strftime("%H:%M"),
        "generated_at": now.isoformat(timespec="seconds"),
        "stale": False,
    }
