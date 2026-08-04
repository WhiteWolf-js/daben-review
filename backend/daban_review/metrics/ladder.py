"""连板梯队与个股画像原料(封单强度/首封时间/炸板/行业),供前端天梯图与 agent 属性归因。"""

from __future__ import annotations

import pandas as pd


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def stock_profiles(limitup: pd.DataFrame) -> list[dict]:
    """把涨停池每只票整理成画像 dict,含封单强度(封板资金/流通市值)。"""
    out: list[dict] = []
    for _, r in limitup.iterrows():
        float_mv = _num(r.get("float_mv"))
        seal_amount = _num(r.get("seal_amount"))
        seal_strength = round(seal_amount / float_mv, 4) if float_mv else 0.0
        out.append({
            "code": str(r.get("code")),
            "name": str(r.get("name")),
            "boards": int(_num(r.get("boards"))),
            "pct": round(_num(r.get("pct")), 2),
            "price": round(_num(r.get("price")), 2),  # 当日收盘=涨停价,供次日触发价推算

            "seal_amount": seal_amount,
            "seal_strength": seal_strength,  # 封单/流通市值,越大封得越结实
            "first_seal": str(r.get("first_seal")),
            "last_seal": str(r.get("last_seal")),
            "break_times": int(_num(r.get("break_times"))),
            "turnover": round(_num(r.get("turnover")), 2),
            "zt_stat": str(r.get("zt_stat")),
            "industry": str(r.get("industry")),
        })
    return out


def build_ladder(limitup: pd.DataFrame) -> dict[int, list[dict]]:
    """按连板数分组的天梯:{板级: [个股画像...]},板级从高到低。"""
    profiles = stock_profiles(limitup)
    ladder: dict[int, list[dict]] = {}
    for p in profiles:
        ladder.setdefault(p["boards"], []).append(p)
    # 每档内按封单强度降序
    for b in ladder:
        ladder[b].sort(key=lambda x: x["seal_strength"], reverse=True)
    return dict(sorted(ladder.items(), key=lambda kv: kv[0], reverse=True))


# ---- 天梯图(含炸板票 + 行业分布),供 LadderPoster 出图 ----

def _seal_minutes(first_seal) -> int | None:
    """首封时间 '092500' / '09:25:00' → 当日分钟数;解析不了返回 None。"""
    digits = "".join(ch for ch in str(first_seal) if ch.isdigit())
    if len(digits) < 4:
        return None
    hh, mm = int(digits[:2]), int(digits[2:4])
    return hh * 60 + mm if 0 <= hh <= 23 and 0 <= mm <= 59 else None


# 集合竞价即涨停(≤9:25)= 一字板
_YIZI_MIN = 9 * 60 + 25
INDUSTRY_MIN_COUNT = 3  # 行业分布里低于此数的并进「其他」


# 只画「昨日≥2板今日断板」的票:昨日首板今日断板每天几十只、无信息量,画上去会淹掉 2 板档
BROKEN_MIN_PREV_BOARDS = 2

# 判「涨幅是否已到涨停」时留的舍入余量:涨停价按分四舍五入,同日实测出现过
# 9.98 / 9.99 / 10.01 / 10.08 都是涨停价
LIMIT_EPS = 0.15


def _limit_pct(code: str) -> float:
    """该票当日涨跌幅限制(%)。**必须按板块取**,一刀切 9.9 会把 20cm 判错。

    ST 不再单列:沪深主板风险警示股涨跌幅 **2026-07-06 起由 5% 调为 10%**,与主板普通股一致
    (2026-04-24 三大交易所发布修订规则);创业板/科创板 ST 本来就是 20%、北交所 30%。
    所以限制纯粹由板块决定,和是否戴帽无关。

    已知边界:库内 20260703 这一天还属旧规(主板 ST 5%),仅此一天,不做特殊处理。
    """
    c = str(code)
    if c.startswith(("30", "688")):
        return 20.0  # 创业板 / 科创板
    if c.startswith(("8", "4")):
        return 30.0  # 北交所
    return 10.0      # 沪深主板(含 ST)


def ladder_board(pools: dict, industry_min: int = INDUSTRY_MIN_COUNT) -> dict:
    """天梯图数据:每档 = 今日封住的票 + **昨日连板今日断板的票**,外加行业分布。

    断板票来源是 `previous`(昨日涨停今日表现)而非炸板池 —— 断板不一定摸过板
    (实测长缆科技 6 板位置 −4.83%,全天没碰涨停,压根不在炸板池里),
    用炸板池会漏掉最关键的「高度被打掉」信息。档位 = 昨日板数 + 1。

    **断板要用涨幅兜底一次**:涨停池会漏收「反复炸板尾盘回封」的票(它们被归进炸板池),
    只按「不在涨停池」判断会把这种票误划成断板。收盘涨幅到涨停幅度的,改判 `reseal`。

    只收昨日 ≥2 板的断板票(见 BROKEN_MIN_PREV_BOARDS);昨日首板今日断板几十只,
    画上去会把 2 板档淹掉,且没有信息量。
    """
    lim = pools.get("limitup", pd.DataFrame())
    prev = pools.get("previous", pd.DataFrame())

    sealed_codes: set[str] = set()
    by_board: dict[int, list[dict]] = {}

    if lim is not None and not lim.empty:
        for p in stock_profiles(lim):
            sealed_codes.add(p["code"])
            first_min = _seal_minutes(p["first_seal"])
            # 展示用「最终封板时间」= 几点才真正稳住;缺失时退回首封
            mins = _seal_minutes(p["last_seal"])
            if mins is None:
                mins = first_min
            by_board.setdefault(p["boards"], []).append({
                "code": p["code"], "name": p["name"], "industry": p["industry"],
                "first_seal": p["first_seal"], "last_seal": p["last_seal"],
                "seal_minutes": mins,  # 排序与展示都用最终封板
                # 真一字要求全天没开板:一字后炸了又回封的,该显示回封时间而不是标一字
                "is_yizi": first_min is not None and first_min <= _YIZI_MIN and p["break_times"] == 0,
                "break_times": p["break_times"],  # >0 = 炸过又回封,质量打折
                "seal_strength": p["seal_strength"], "pct": p["pct"],
                "broken": False,
            })

    if prev is not None and not prev.empty:
        # 炸板池:给「其实封住了但涨停池没收录」的票补炸板次数(见下面的兜底判据)
        zb = pools.get("zbgc")
        zb_breaks: dict[str, int] = {}
        if zb is not None and not zb.empty and "code" in zb.columns:
            for _, z in zb.iterrows():
                zb_breaks[str(z.get("code"))] = int(_num(z.get("break_times")))

        for _, r in prev.iterrows():
            code = str(r.get("code"))
            pb = int(_num(r.get("prev_boards")))
            if code in sealed_codes or pb < BROKEN_MIN_PREV_BOARDS:
                continue  # 今天封住了 → 已在上面;昨日首板断板 → 不画
            name = str(r.get("name"))
            pct = round(_num(r.get("pct")), 2)
            base = {
                "code": code, "name": name, "industry": str(r.get("industry")),
                "first_seal": "", "last_seal": "", "seal_minutes": None, "is_yizi": False,
                "seal_strength": 0.0, "pct": pct,
            }
            if pct >= _limit_pct(code) - LIMIT_EPS:
                # 收盘涨幅已经到涨停 → 它其实封住了,只是 akshare 涨停池漏收 ——
                # 反复炸板、尾盘才回封的票会被归进炸板池。实测 002827 高争民爆:
                # 09:25 一字开盘、炸板 26 次、收盘 41.87 = 涨停价 38.06×1.1,
                # 却只出现在炸板池里,于是被当成断板划了线。
                # **故意不填封板时间**:最终回封时刻拿不到,拿首封顶替会把烂板显示成
                # 「超早封」(评分体系里最强的信号),宁可留空,靠炸板次数说明质量。
                by_board.setdefault(pb + 1, []).append({
                    **base, "break_times": zb_breaks.get(code, 0),
                    "broken": False, "reseal": True,
                })
                sealed_codes.add(code)
                continue
            by_board.setdefault(pb + 1, []).append({**base, "broken": True})

    # 档内排序:先封住的(按首封时间早→晚),炸板的排最后
    for b in by_board:
        by_board[b].sort(key=lambda s: (s["broken"], s["seal_minutes"] if s["seal_minutes"] is not None else 9999))

    rows = [{"boards": b, "stocks": by_board[b]} for b in sorted(by_board, reverse=True)]

    # 行业分布(封住+炸板全算,与图上各档票数总和一致);少于 industry_min 的并进「其他」
    counts: dict[str, int] = {}
    for row in rows:
        for s in row["stocks"]:
            counts[s["industry"] or "其他"] = counts.get(s["industry"] or "其他", 0) + 1
    main = [(k, v) for k, v in counts.items() if v >= industry_min and k != "其他"]
    main.sort(key=lambda kv: (-kv[1], kv[0]))
    others = sum(v for k, v in counts.items() if (v < industry_min or k == "其他"))
    industries = [{"name": k, "count": v} for k, v in main]
    if others:
        industries.append({"name": "其他", "count": others})

    total = sum(len(r["stocks"]) for r in rows)
    return {
        "rows": rows,
        "industries": industries,
        "total": total,
        "sealed": sum(1 for r in rows for s in r["stocks"] if not s["broken"]),
        "broken": sum(1 for r in rows for s in r["stocks"] if s["broken"]),
        "max_board": rows[0]["boards"] if rows else 0,
    }
