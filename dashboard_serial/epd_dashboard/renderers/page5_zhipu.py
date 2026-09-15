"""页5（智谱AI）：智谱AI 个股走势归因分析，整页排版（复用页4的报告页组件）。

页首为分时折线面板（价格叠加在面板左上），AI指数/上证对照压缩为一行，
为折线图腾出空间；【今日走势】以下的报告内容与页4排版完全一致。
"""
from epd_dashboard.fetchers.zhipu_analysis import ZHIPU_CODE, ZHIPU_NAME, _find_quote, _index_pct
from epd_dashboard.renderers.page4_analysis import (
    _meta_text,
    _pct_text,
    STOCK_BODY_SIZES,
    render_report_page,
)


def _build_chart(intraday, quote):
    """把分时缓存整理成渲染面板数据；无有效分时点时返回 None（面板显示占位文案）。"""
    data = intraday if isinstance(intraday, dict) else {}
    try:
        points = [(int(t), float(p)) for t, p in (data.get("points") or [])]
    except (TypeError, ValueError):
        points = []
    if len(points) < 2:
        return None
    prev_close = float(data.get("prev_close") or 0)
    if quote and quote.get("price", 0) > 0:
        price, pct = quote["price"], quote.get("pct")
    else:
        # 行情缺失时用分时最后一点兜底
        price = points[-1][1]
        pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else None
    sub_parts = []
    if prev_close > 0:
        sub_parts.append(f"昨收 {prev_close:.2f}")
    if data.get("high"):
        sub_parts.append(f"高 {data['high']:.2f}")
    if data.get("low"):
        sub_parts.append(f"低 {data['low']:.2f}")
    return {
        "price_text": f"{price:.2f} 港元 {_pct_text(pct)}",
        "sub_text": " · ".join(sub_parts),
        "points": points,
        "prev_close": prev_close,
    }


def _strip_risk_section(text):
    """页5不再显示风险提示；旧缓存渲染时自动剥离该小节。"""
    risk_start = (text or "").find("【风险提示】")
    return text[:risk_start].rstrip() if risk_start >= 0 else text


def render_page5(markets, analysis, intraday=None):
    """页5：智谱AI 走势归因。页首分时折线（价格叠加），对照行 = AI板块指数/大盘。"""
    a = analysis or {}
    quote = _find_quote(markets, ZHIPU_CODE)
    chart = _build_chart(intraday, quote)
    ai_pct = _index_pct(markets, "sz399415")
    sh_pct = _index_pct(markets, "sh000001")
    if ai_pct is None and sh_pct is None:
        pair_text = "暂无行情"
    else:
        pair_text = (f"AI指数 {_pct_text(ai_pct)} · 上证指数 {_pct_text(sh_pct)}")
    pairs = [("大盘对照", pair_text)]
    notes = (
        "暂无分析报告。",
        "自动生成：交易日（港股时段至16:05）轮播到本页且报告超过90分钟时自动重新生成。",
        "手动生成：运行 dashboard_control.ps1 stock。",
    )
    return render_report_page(
        f"{ZHIPU_NAME} · 今日走势分析",
        _meta_text(a),
        pairs,
        _strip_risk_section(a.get("text", "")),
        notes,
        page_tag="5/5",
        chart=chart,
        body_sizes=STOCK_BODY_SIZES,
    )
