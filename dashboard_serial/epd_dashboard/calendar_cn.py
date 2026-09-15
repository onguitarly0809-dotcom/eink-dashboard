"""农历/法定节假日/节日倒计时/分市场交易状态。

依赖 lunar_python（缺省时农历相关功能自动退化为空）。
"""
from datetime import date, datetime, timedelta

try:
    from lunar_python import Solar as _LunarSolar
    from lunar_python import Lunar as _Lunar
except Exception:
    _LunarSolar = None
    _Lunar = None


def is_statutory_holiday(day):
    """day 是否为 A股休市的法定节假日当天（元旦/劳动节/国庆/春节/端午/中秋/清明）。"""
    fixed = {(1, 1), (5, 1), (10, 1)}
    if (day.month, day.day) in fixed:
        return True
    if _LunarSolar is None or _Lunar is None:
        return False
    try:
        lunar = _LunarSolar.fromYmd(day.year, day.month, day.day).getLunar()
        ly = lunar.getYear()
        qm = lunar.getJieQiTable().get("清明")
        if qm is not None and (qm.getMonth(), qm.getDay()) == (day.month, day.day):
            return True
        for lm, ld in ((1, 1), (5, 5), (8, 15)):
            lun = _Lunar.fromYmd(ly, lm, ld)
            s = lun.getSolar()
            if s is not None and (s.getMonth(), s.getDay()) == (day.month, day.day):
                return True
    except Exception:
        pass
    return False


def market_status(now):
    """A股交易状态：未开盘 / 交易中 / 午休 / 已收盘 / 休市。休市仅指周末与法定节假日。"""
    if now.weekday() >= 5 or is_statutory_holiday(now.date()):
        return "休市"
    hm = now.strftime("%H:%M")
    if hm < "09:30":
        return "未开盘"
    if hm <= "11:30" or "13:00" <= hm <= "15:00":
        return "交易中"
    if hm < "13:00":
        return "午休"
    return "已收盘"


def market_of(code):
    """按代码前缀判断市场：A股 / 港股(HK) / 美股(US)。"""
    c = str(code).lower()
    if c.startswith("us"):
        return "US"
    if c.startswith("hk"):
        return "HK"
    return "A"


def market_status_for(market, now):
    """按市场各自时段返回交易状态：未开盘 / 交易中 / 午休 / 已收盘 / 休市。"""
    if market == "HK":
        if now.weekday() >= 5:
            return "休市"
        hm = now.strftime("%H:%M")
        if hm < "09:30":
            return "未开盘"
        if hm <= "12:00" or "13:00" <= hm <= "16:00":
            return "交易中"
        if hm < "13:00":
            return "午休"
        return "已收盘"
    if market == "US":
        # 美股 9:30-16:00 美东，无午休。北京≈美东+12h(夏令时)/+13h(冬令时)，近似切换。
        et = now - timedelta(hours=13)
        if 3 <= now.month <= 10:  # 粗略夏令时窗口
            et = now - timedelta(hours=12)
        if et.weekday() >= 5:
            return "休市"
        ehm = et.strftime("%H:%M")
        if ehm < "09:30":
            return "未开盘"
        return "交易中" if ehm <= "16:00" else "已收盘"
    return market_status(now)


def next_legal_holiday(now):
    # 返回 (最近法定节假日名, 距今天数)；依赖 lunar_python，失败返回 ("", 0)
    today = now.date()
    candidates = []
    def _add(name, d):
        if d >= today:
            candidates.append((name, (d - today).days))
    y = today.year
    # 固定公历法定节假日
    for m, d, name in ((1, 1, "元旦"), (5, 1, "劳动节"), (10, 1, "国庆节")):
        base = date(y, m, d)
        if base < today:
            base = date(y + 1, m, d)
        _add(name, base)
    # 农历法定节假日 + 清明节气
    if _LunarSolar is not None:
        lunar = _LunarSolar.fromYmd(y, today.month, today.day).getLunar()
        ly = lunar.getYear()
        qm = lunar.getJieQiTable().get("清明")
        if qm is not None:
            qmd = date(qm.getYear(), qm.getMonth(), qm.getDay())
            if qmd < today:
                qm = _LunarSolar.fromYmd(y + 1, 4, 5).getLunar().getJieQiTable().get("清明")
                qmd = date(qm.getYear(), qm.getMonth(), qm.getDay())
            _add("清明节", qmd)
        for lm, ld, name in ((1, 1, "春节"), (5, 5, "端午节"), (8, 15, "中秋节")):
            lun = _Lunar.fromYmd(ly, lm, ld)
            d = lun.getSolar()
            dd = date(d.getYear(), d.getMonth(), d.getDay())
            if dd < today:
                lun = _Lunar.fromYmd(ly + 1, lm, ld)
                d = lun.getSolar()
                dd = date(d.getYear(), d.getMonth(), d.getDay())
            _add(name, dd)
    if not candidates:
        return "", 0
    return min(candidates, key=lambda item: item[1])


def next_festival(now):
    # 返回 (最近节日名, 距今天数)，含不放假的节日；依赖 lunar_python，失败返回 ("", 0)
    today = now.date()
    candidates = []
    def _add(name, d):
        if d >= today:
            candidates.append((name, (d - today).days))
    def _nth_weekday(y, m, weekday, n):
        first = date(y, m, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + (n - 1) * 7)
    y = today.year
    # 固定公历节日（含不放假节日）
    for m, d, name in (
        (1, 1, "元旦"), (2, 14, "情人节"), (3, 8, "妇女节"), (3, 12, "植树节"),
        (5, 1, "劳动节"), (6, 1, "儿童节"), (10, 1, "国庆节"), (12, 25, "圣诞节"),
    ):
        base = date(y, m, d)
        if base < today:
            base = date(y + 1, m, d)
        _add(name, base)
    # 非固定公历节日：母亲节(5月第2个周日)、父亲节(6月第3个周日)
    for m, n, name in ((5, 2, "母亲节"), (6, 3, "父亲节")):
        base = _nth_weekday(y, m, 6, n)
        if base < today:
            base = _nth_weekday(y + 1, m, 6, n)
        _add(name, base)
    # 农历节日 + 清明节气
    if _LunarSolar is not None:
        lunar = _LunarSolar.fromYmd(y, today.month, today.day).getLunar()
        ly = lunar.getYear()
        qm = lunar.getJieQiTable().get("清明")
        if qm is not None:
            qmd = date(qm.getYear(), qm.getMonth(), qm.getDay())
            if qmd < today:
                qm = _LunarSolar.fromYmd(y + 1, 4, 5).getLunar().getJieQiTable().get("清明")
                qmd = date(qm.getYear(), qm.getMonth(), qm.getDay())
            _add("清明节", qmd)
        for lm, ld, name in (
            (1, 1, "春节"), (1, 15, "元宵节"), (5, 5, "端午节"),
            (7, 7, "七夕"), (8, 15, "中秋节"), (9, 9, "重阳节"),
        ):
            lun = _Lunar.fromYmd(ly, lm, ld)
            d = lun.getSolar()
            dd = date(d.getYear(), d.getMonth(), d.getDay())
            if dd < today:
                lun = _Lunar.fromYmd(ly + 1, lm, ld)
                d = lun.getSolar()
                dd = date(d.getYear(), d.getMonth(), d.getDay())
            _add(name, dd)
    if not candidates:
        return "", 0
    return min(candidates, key=lambda item: item[1])


def lunar_extra(now):
    # 返回 (农历月日, 节假日倒计时)；第一部分=距放假天数(法定节假日)，第二部分=下一完整节日(含不放假)
    if _LunarSolar is None:
        return "", ""
    try:
        lunar = _LunarSolar.fromYmd(now.year, now.month, now.day).getLunar()
        lunar_str = lunar.getMonthInChinese() + "月" + lunar.getDayInChinese()
        legal_name, legal_days = next_legal_holiday(now)
        part1 = f"今日{legal_name}" if legal_days <= 0 else f"距{legal_name}{legal_days}天" if legal_name else ""
        fest_name, fest_days = next_festival(now)
        part2 = f"今日{fest_name}" if fest_days <= 0 else f"距{fest_name}{fest_days}天" if fest_name else ""
        if part1 and part2:
            # 同一节日时去重（如中秋当天）
            if fest_name == legal_name:
                extra = part1
            else:
                extra = f"{part1} · {part2}"
        else:
            extra = part1 or part2
        return lunar_str, extra
    except Exception:
        return "", ""
