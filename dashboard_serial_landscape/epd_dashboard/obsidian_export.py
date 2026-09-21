"""页4认知洞察 → Obsidian 归档：每次生成新主题时同步落一份 Markdown 笔记。

目标文件夹在 Obsidian Vault 的 04-认知（config.INSIGHT_ARCHIVE_DIR），
文件名 "YYYY-MM-DD 主题.md"，同日同主题重生成时追加 HHMM 后缀避免覆盖。
只在 fetch_insight 成功后调用（重渲染不重复归档）；
导出失败仅记 WARN，绝不影响渲染/推送主链路。
"""
import re
import sys
from datetime import datetime
from pathlib import Path

from epd_dashboard.config import INSIGHT_ARCHIVE_DIR

# 正文小节顺序固定；主题/领域两个元信息小节进 frontmatter，不重复出现在正文
SECTION_TITLES = ("核心知识", "背后的机制", "生活里的样子", "怎么用起来")
_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _split_sections(text):
    """把六段【】文本拆成 {小节名: [正文行]}，兼容"【标题】正文"同行写法。"""
    sections = {}
    current = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.match(r"^【([^】]+)】", line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            remainder = line[match.end():].strip()
            if remainder:
                sections[current].append(remainder)
        elif current:
            sections[current].append(line)
    return sections


def _safe_filename(topic):
    """替换 Windows 文件名非法字符；结尾的空格/点也会被资源管理器吞掉，一并剥掉。"""
    name = _INVALID_FS_CHARS.sub(" ", str(topic)).strip().rstrip(".")
    return name or "未命名主题"


def build_insight_markdown(analysis, now=None):
    """把 insight 缓存对象转成 Obsidian 笔记（YAML frontmatter + 一级标题 + 四小节）。"""
    a = analysis or {}
    sections = _split_sections(a.get("text", ""))
    topic = a.get("topic") or (sections.get("主题名称") or ["未命名主题"])[0]
    domain = a.get("domain") or (sections.get("所属领域") or [""])[0]
    created = a.get("generated_at") or (now or datetime.now()).isoformat(timespec="seconds")

    lines = [
        "---",
        f"created: {created}",
        "tags:",
        "  - 认知洞察",
    ]
    if domain:
        lines.append(f"  - {domain}")
    lines += [
        f"source: 墨水屏页4认知洞察（{a.get('model') or 'GLM'}）",
        "---",
        "",
        f"# {topic}",
        "",
    ]
    for title in SECTION_TITLES:
        content = sections.get(title) or []
        if not content:
            continue
        lines.append(f"## {title}")
        lines.append("")
        lines.extend(content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def archive_insight(analysis, archive_dir=INSIGHT_ARCHIVE_DIR, now=None):
    """写盘归档并返回笔记路径；非 insight 内容或写盘失败返回 None（只记 WARN）。"""
    try:
        a = analysis or {}
        if a.get("kind") != "insight" or not a.get("text"):
            return None
        try:
            stamp = datetime.fromisoformat(a.get("generated_at"))
        except (TypeError, ValueError):
            stamp = now or datetime.now()
        topic = _safe_filename(a.get("topic") or "未命名主题")
        Path(archive_dir).mkdir(parents=True, exist_ok=True)
        path = Path(archive_dir) / f"{stamp:%Y-%m-%d} {topic}.md"
        if path.exists():
            path = Path(archive_dir) / f"{stamp:%Y-%m-%d} {topic} {stamp:%H%M}.md"
        path.write_text(build_insight_markdown(a, now=now), encoding="utf-8")
        return path
    except Exception as exc:
        print(f"WARN insight archive failed: {exc}", file=sys.stderr)
        return None
