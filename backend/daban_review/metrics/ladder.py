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


def ladder_board(pools: dict, industry_min: int = INDUSTRY_MIN_COUNT) -> dict:
    """天梯图数据:每档 = 今日封住的票 + **昨日连板今日断板的票**,外加行业分布。

    断板票来源是 `previous`(昨日涨停今日表现)而非炸板池 —— 断板不一定摸过板
    (实测长缆科技 6 板位置 −4.83%,全天没碰涨停,压根不在炸板池里),
    用炸板池会漏掉最关键的「高度被打掉」信息。档位 = 昨日板数 + 1。

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
        for _, r in prev.iterrows():
            code = str(r.get("code"))
            pb = int(_num(r.get("prev_boards")))
            if code in sealed_codes or pb < BROKEN_MIN_PREV_BOARDS:
                continue  # 今天封住了 → 已在上面;昨日首板断板 → 不画
            by_board.setdefault(pb + 1, []).append({
                "code": code, "name": str(r.get("name")), "industry": str(r.get("industry")),
                "first_seal": "", "seal_minutes": None, "is_yizi": False,
                "seal_strength": 0.0, "pct": round(_num(r.get("pct")), 2),
                "broken": True,
            })

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
