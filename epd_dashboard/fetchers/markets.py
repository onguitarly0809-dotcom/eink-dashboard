"""页3行情：腾讯实时行情 + akshare 概念板块（腾讯接口兜底）。"""
import json
import re
import sys
import time
from datetime import datetime

from epd_dashboard.calendar_cn import market_of
from epd_dashboard.config import (
    MARKET_COMPANY_SYMBOLS,
    MARKET_GROUPS,
    MARKET_MINUTE_URL,
    MARKET_SECTOR_URL,
    MARKET_URL_TENCENT,
)
from epd_dashboard.httpclient import http_read
from epd_dashboard.util import to_float

# 尝试导入akshare，如果不可用会在运行时处理
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("WARNING: akshare not available, will use fallback data source", file=sys.stderr)


# 东财概念板块列表里混有"统计类板块"——按条件筛出的股票集合而非真实主题，
# 如 历史新高/昨日涨停/昨日连板/昨日打二板以上表现/连续上涨/百元股/ST股/预盈预增 等。
# 它们的涨跌幅天然脱离主题逻辑（创新高的股票当天必然大涨），当"最热板块"展示
# 和做AI归因都会误导（同义反复），抓取时统一过滤。
_STATISTICAL_BOARD_RE = re.compile(
    r"^昨日|^ST|^连续|^退市|^打板|新高$|新低$|^百元|^低价|^高价|^次新|^破净|^微盘"
    r"|^预盈|^预亏|^融资融券|^转债标的|^证金|^汇金|^机构重仓|^基金重仓|^社保重仓"
    r"|^QFII|^MSCI|^标普|^富时|^沪股通|^深股通|^机构调研|^央视50|^茅指数|^宁组合|^AH股|^B股"
)


def _is_statistical_board(name):
    """判断是否为统计类板块（非真实主题）。"""
    return bool(_STATISTICAL_BOARD_RE.search(name or ""))


def fetch_markets(previous=None):
    """抓取行情：腾讯（指数/公司/板块），失败保留旧值。"""
    markets = dict(previous) if isinstance(previous, dict) else {}
    tencent_symbols = [code for group in MARKET_GROUPS.values() for code, _ in group["symbols"]]
    tencent_symbols += [code for code, _ in MARKET_COMPANY_SYMBOLS]
    tencent_data = {}
    if tencent_symbols:
        try:
            raw = http_read(MARKET_URL_TENCENT + ",".join(tencent_symbols), timeout=12)
            for line in raw.decode("gbk", errors="replace").split(";"):
                parts = line.split("~")
                if len(parts) <= 33:
                    continue
                tencent_data[line.split("=", 1)[0].replace("v_", "").strip()] = {
                    "name": parts[1].strip(),
                    "price": to_float(parts[3]),
                    "chg": to_float(parts[31]),
                    "pct": to_float(parts[32]),
                }
        except Exception as exc:
            print(f"WARN markets[tencent] fetch failed: {exc}", file=sys.stderr)
    # 板块数据：优先使用akshare获取多股数据，失败时回退到腾讯财经API
    try:
        # 尝试使用akshare获取板块和多股数据
        sectors_with_stocks = fetch_sector_with_akshare()
        if sectors_with_stocks and len(sectors_with_stocks) > 0:
            markets["raw_sectors"] = sectors_with_stocks
            print("Successfully loaded sector data from akshare with multiple stocks")
        else:
            raise Exception("akshare returned empty data")
    except Exception as ak_exc:
        print(f"WARN akshare fetch failed: {ak_exc}, falling back to Tencent API", file=sys.stderr)
        # 回退到腾讯财经API（原有逻辑）
        try:
            payload = json.loads(http_read(
                MARKET_SECTOR_URL,
                timeout=12,
                headers={"Referer": "https://gu.qq.com/"},
            ).decode("utf-8"))
            sector_rows = payload.get("data", {}).get("rank_list", [])
            # 腾讯兜底路径同样防御性过滤统计类板块
            sector_rows = [row for row in sector_rows if not _is_statistical_board(row.get("name", ""))]

            # 保存原始板块数据供AI重点跟踪面板使用
            markets["raw_sectors"] = sector_rows
        except Exception as tencent_exc:
            print(f"WARN Tencent fallback also failed: {tencent_exc}", file=sys.stderr)
    previous_quotes = markets.get("quotes") or {}
    quotes = {}
    got_fresh = False
    for key, group in MARKET_GROUPS.items():
        prev_group = previous_quotes.get(key) or []
        # 旧值优先按 code 对齐（调整标的列表后不会张冠李戴）；无 code 的旧缓存退回索引对齐
        prev_by_code = {item.get("code"): item for item in prev_group if isinstance(item, dict) and item.get("code")}
        quotes[key] = []
        for idx, (code, fallback_name) in enumerate(group["symbols"]):
            quote = tencent_data.get(code)
            if quote:
                got_fresh = True
                # 修复指数名称显示问题：如果返回的名称是代码（如"I100"），使用fallback_name
                quote_name = quote["name"]
                if quote_name and (quote_name == "I100" or quote_name == code):
                    display_name = fallback_name
                else:
                    display_name = quote_name or fallback_name

                quotes[key].append({"name": display_name, "price": quote["price"],
                                    "chg": quote["chg"], "pct": quote["pct"], "market": market_of(code),
                                    "code": code})
            else:
                prev = prev_by_code.get(code)
                if prev is None and idx < len(prev_group) and prev_group[idx].get("code") is None:
                    prev = prev_group[idx]
                if prev and prev.get("price", 0) > 0:
                    # 本次未取到该标的（网络失败/接口波动），保留上一轮可用数据，避免页面显示 "--"
                    quotes[key].append(dict(prev))
                else:
                    quotes[key].append({"name": fallback_name, "price": 0, "chg": 0, "pct": 0,
                                        "market": market_of(code), "code": code})
    previous_companies = {
        item.get("name"): item for item in markets.get("companies", []) if isinstance(item, dict)
    }
    markets["companies"] = []
    for code, display_name in MARKET_COMPANY_SYMBOLS:
        quote = tencent_data.get(code)
        fallback = previous_companies.get(display_name, {})
        markets["companies"].append({
            "name": display_name,
            "price": quote["price"] if quote else fallback.get("price", 0),
            "chg": quote["chg"] if quote else fallback.get("chg", 0),
            "pct": quote["pct"] if quote else fallback.get("pct", 0),
            "market": market_of(code),
        })
    if any(quotes.values()):
        markets["quotes"] = quotes
        markets["stale"] = not got_fresh
        if got_fresh:
            markets["updated"] = datetime.now().strftime("%H:%M")
    return markets


def fetch_sector_with_akshare():
    """使用akshare获取概念板块和多股数据。

    akshare 单次请求无法传超时，这里用整体时间预算兜底：超预算后剩余板块
    不再逐个取成分股（保留已取到的部分），避免网络差时把整个刷新流程挂死。
    """
    if not AKSHARE_AVAILABLE:
        raise Exception("akshare not available")

    budget_seconds = 45.0
    start = time.monotonic()

    try:
        print("Fetching concept boards from akshare...")
        # 获取概念板块列表
        concept_boards = ak.stock_board_concept_name_em()

        if concept_boards is None or len(concept_boards) == 0:
            raise Exception("No concept boards returned from akshare")

        # 按涨跌幅排序
        concept_boards = concept_boards.sort_values('涨跌幅', ascending=False)
        # 过滤统计类板块（历史新高/昨日涨停等条件筛选集合），只留真实主题板块
        concept_boards = concept_boards[
            [not _is_statistical_board(name) for name in concept_boards['板块名称']]
        ]

        # 获取最热和最冷的板块
        hot_boards = concept_boards.head(3)
        cold_boards = concept_boards.tail(3)

        sectors_with_stocks = []

        # 处理最热板块
        for idx, (_, board) in enumerate(hot_boards.iterrows()):
            board_name = board['板块名称']
            print(f"Fetching stocks for hot board {idx+1}/3: {board_name}")
            over_budget = time.monotonic() - start > budget_seconds
            sectors_with_stocks.append(_board_payload(board, board_name, descending=True, skip_stocks=over_budget))

        # 处理最冷板块
        for idx, (_, board) in enumerate(cold_boards.iterrows()):
            board_name = board['板块名称']
            print(f"Fetching stocks for cold board {idx+1}/3: {board_name}")
            over_budget = time.monotonic() - start > budget_seconds
            sectors_with_stocks.append(_board_payload(board, board_name, descending=False, skip_stocks=over_budget))

        print(f"Successfully fetched {len(sectors_with_stocks)} sectors with stocks")
        return sectors_with_stocks

    except Exception as e:
        print(f"WARN akshare fetch failed: {e}", file=sys.stderr)
        raise Exception(f"akshare error: {e}")


def _board_payload(board, board_name, descending, skip_stocks=False):
    """单个板块的载荷：名称、涨跌幅、领涨/领跌前2个股（个股获取失败则留空）。"""
    if skip_stocks:
        print("  Budget exceeded, skipping stock fetch")
        return {'name': board_name, 'pct': board['涨跌幅'], 'stocks': []}
    try:
        stocks = ak.stock_board_concept_cons_em(symbol=board_name)
        if stocks is not None and len(stocks) > 0:
            top_stocks = stocks.sort_values('涨跌幅', ascending=not descending).head(2)
            payload = {
                'name': board_name,
                'pct': board['涨跌幅'],
                'stocks': [
                    {'name': row['名称'], 'pct': row['涨跌幅']}
                    for _, row in top_stocks.iterrows()
                ],
            }
            print(f"  Found {len(top_stocks)} stocks")
            return payload
        print("  No stocks found for this board")
    except Exception as e:
        print(f"  WARN failed to fetch stocks for {board_name}: {e}")
    return {'name': board_name, 'pct': board['涨跌幅'], 'stocks': []}


def fetch_intraday(symbol):
    """腾讯分时（分钟级）：当日价格序列 + 昨收/最高/最低，供页5折线图。

    返回 {"symbol", "date", "points": [(hhmm, price)...], "prev_close", "high", "low", "updated"}；
    points 午休时段在数据里天然跳档（1200 → 1300），渲染按序号定位即可。
    """
    raw = http_read(MARKET_MINUTE_URL + symbol, timeout=10)
    node = json.loads(raw.decode("utf-8", errors="replace"))["data"][symbol]
    points = []
    for row in node["data"]["data"]:
        parts = row.split()
        if len(parts) >= 2:
            points.append((int(parts[0]), to_float(parts[1])))
    if not points:
        raise ValueError(f"intraday: no minute points for {symbol}")
    # qt 为腾讯既有格式的位置数组（dict 形态）：3=现价 4=昨收 5=今开 11=最高 12=最低
    qt = node.get("qt", {}).get(symbol) or {}
    vals = list(qt.values()) if isinstance(qt, dict) else list(qt)

    def _at(index):
        return to_float(vals[index]) if len(vals) > index else 0.0

    date = str(node["data"].get("date", ""))
    if len(date) == 8:
        date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return {
        "symbol": symbol,
        "date": date,
        "points": points,
        "prev_close": _at(4),
        "high": _at(11),
        "low": _at(12),
        "updated": datetime.now().strftime("%H:%M"),
    }
