"""页5（智谱AI）：智谱AI 个股走势归因分析，整页排版（复用页4的报告页组件）。

页首为一行两列分时面板：左=智谱AI(HK) 个股，右=人工智能(A)指数（sz399415），
直观对比个股与 A 股 AI 板块的走势差异；昨收以图内虚线+图头小字保留，
大盘对照（AI指数/上证涨跌幅）不再展示。报告正文与页4排版完全一致。
"""
from epd_dashboard.fetchers.zhipu_analysis import ZHIPU_CODE, ZHIPU_NAME, _find_quote
from epd_dashboard.renderers.landscape.page4_analysis import (
    _meta_text,
    _pct_text,
    STOCK_BODY_SIZES,
    render_report_page,
)


def _series(data):
    """分时缓存 → (points, prev_close, high, low)；坏数据静默退化为空。"""
    data = data if isinstance(data, dict) else {}
    try:
        points = [(int(t), float(p)) for t, p in (data.get("points") or [])]
    except (TypeError, ValueError):
        points = []
    return points, float(data.get("prev_close") or 0), data.get("high"), data.get("low")


def _sub_line(name, prev_close, high, low):
    parts = [name]
    if prev_close > 0:
        parts.append(f"昨收 {prev_close:.2f}")
    if high:
        parts.append(f"高 {high:.2f}")
    if low:
        parts.append(f"低 {low:.2f}")
    return " · ".join(parts)


def _build_stock_chart(intraday, quote):
    """左图：智谱AI(HK) 分时。无有效分时点时返回 None（面板显示占位文案）。"""
    points, prev_close, high, low = _series(intraday)
    if len(points) < 2:
        return None
    if quote and quote.get("price", 0) > 0:
        price, pct = quote["price"], quote.get("pct")
    else:
        price = points[-1][1]
        pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else None
    return {
        "price_text": f"{price:.2f} {_pct_text(pct)}",  # 港元字样省略（2026-09-23 真机定稿）
        "name": f"{ZHIPU_NAME}(HK)",
        "sub_text": _sub_line(f"{ZHIPU_NAME}(HK)", prev_close, high, low),
        "points": points,
        "prev_close": prev_close,
    }


def _build_index_chart(intraday_ai):
    """右图：人工智能(A)指数（sz399415）分时，与个股共用同一绘制面板。"""
    points, prev_close, high, low = _series(intraday_ai)
    if len(points) < 2:
        return None
    price = points[-1][1]
    pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else None
    return {
        "price_text": f"{price:.2f} {_pct_text(pct)}",
        "name": "人工智能(A)",
        "sub_text": _sub_line("人工智能(A)", prev_close, high, low),
        "points": points,
        "prev_close": prev_close,
    }


def _strip_risk_section(text):
    """页5不再显示风险提示；旧缓存渲染时自动剥离该小节。"""
    risk_start = (text or "").find("【风险提示】")
    return text[:risk_start].rstrip() if risk_start >= 0 else text


def render_page5(markets, analysis, intraday=None, intraday_ai=None):
    """页5：智谱AI 走势归因（横版）。个股与 AI 指数分时一行两列对比。"""
    a = analysis or {}
    quote = _find_quote(markets, ZHIPU_CODE)
    charts = [c for c in (_build_stock_chart(intraday, quote),
                          _build_index_chart(intraday_ai)) if c]
    notes = (
        "暂无分析报告。",
        "自动生成：交易日（港股时段至16:05）轮播到本页且报告超过90分钟时自动重新生成。",
        "手动生成：运行 dashboard_control.ps1 stock。",
    )
    return render_report_page(
        f"{ZHIPU_NAME} · 今日走势分析",
        _meta_text(a),
        _strip_risk_section(a.get("text", "")),
        notes,
        charts=charts,
        body_sizes=STOCK_BODY_SIZES,
    )
