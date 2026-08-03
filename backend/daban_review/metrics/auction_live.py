"""盘前竞价遴选:候选池 → 个股竞价行 → 题材聚合 → 叠加竞价维度的分级。纯函数,不碰网络/IO。

交易口径(决定判据):
- 9:15–9:20 可撤单,虚单多 → 数据不采信(phase=pre_cancel,面板标灰)
- 9:20–9:25 不可撤,真金白银 → 采信,并算与首轮(≈9:20)的变化方向
- 9:25 撮合定格 → 用 open;9:30 后同样用 open(当日开盘结果,复盘回看)

三个防骗维度:定格高开% / 9:20→9:25 变化方向 / 竞价成交额。
同样 +5%,从 +2% 抬上来是抢筹在加,从 +8% 掉下来是有人砸(高开低走风险);
高开 7% 只成交 800 万是假强,高开 5% 成交 1.2 亿才是真抢。
"""

from __future__ import annotations

SHOUBAN_TOP = 15        # 首板按封流比取前 N(连板全取)
GAP_BEST = (3.0, 5.0)   # 最佳接力高开区间(%)
GAP_TOO_HIGH = 7.0      # 溢价过高:一步到位,接力赔率差
GAP_TOO_LOW = 2.0       # 高开不足:情绪偏弱
AMT_OK_YI = 0.5         # 竞价成交额达标线(亿):低于此的高开是"没人接的假强"
TREND_EPS = 0.3         # 变化方向阈值(百分点),小于此视为持平

_GRADE_UP = {"D": "C", "C": "B", "B": "A", "A": "A+", "A+": "A+"}
_GRADE_DOWN = {"A+": "A", "A": "B", "B": "C", "C": "D", "D": "D"}


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def pick_pool(prev_profiles: list[dict], shouban_top: int = SHOUBAN_TOP) -> list[dict]:
    """候选池:上一交易日连板(≥2)全取 + 首板按封流比 top N(接力视角)。"""
    lianban = [p for p in prev_profiles if int(_f(p.get("boards"))) >= 2]
    shouban = sorted(
        [p for p in prev_profiles if int(_f(p.get("boards"))) == 1],
        key=lambda x: _f(x.get("seal_strength")),
        reverse=True,
    )[:shouban_top]
    return lianban + shouban


def _trend(code: str, gap_pct: float, series: dict[str, list[dict]], last_close: float) -> str:
    """与首轮(≈9:20)比的变化方向:up=抢筹在加 / down=有人砸 / flat / none=无历史。"""
    hist = (series or {}).get(code) or []
    if not hist or last_close <= 0:
        return "none"
    first_price = _f(hist[0].get("price"))
    if first_price <= 0:
        return "none"
    first_gap = (first_price / last_close - 1) * 100
    delta = gap_pct - first_gap
    if delta > TREND_EPS:
        return "up"
    if delta < -TREND_EPS:
        return "down"
    return "flat"


def live_rows(
    pool: list[dict],
    quotes: dict[str, dict],
    phase: str,
    series: dict[str, list[dict]] | None = None,
    themes: dict[str, list[str]] | None = None,
    candidate_codes: set[str] | None = None,
) -> list[dict]:
    """组装个股竞价行,按高开降序。

    phase: pre_cancel(9:15–9:20) / bidding(9:20–9:25) 用 price;opened/closed 用 open。
    """
    use_price = phase in ("pre_cancel", "bidding")
    themes = themes or {}
    cands = candidate_codes or set()
    out: list[dict] = []
    for p in pool:
        code = str(p.get("code", "")).strip()
        q = quotes.get(code)
        if not q:
            continue
        last_close = _f(q.get("last_close"))
        ref = _f(q.get("price")) if use_price else _f(q.get("open"))
        if last_close <= 0 or ref <= 0:
            continue  # 竞价未撮合出价 / 数据缺失
        gap_pct = round((ref / last_close - 1) * 100, 2)
        amount_yi = round(_f(q.get("amount")) / 1e8, 3)
        bid_vol, ask_vol = _f(q.get("bid_vol1")), _f(q.get("ask_vol1"))
        out.append({
            "code": code,
            "name": str(p.get("name", "")),
            "prev_boards": int(_f(p.get("boards"))),
            "seal_strength": round(_f(p.get("seal_strength")), 4),
            "ref_price": round(ref, 2),
            "last_close": round(last_close, 2),
            "gap_pct": gap_pct,
            "gap_trend": _trend(code, gap_pct, series or {}, last_close),
            "amount_yi": amount_yi,
            "bid_vol": bid_vol,
            "ask_vol": ask_vol,
            "bid_ask_ratio": round(bid_vol / ask_vol, 2) if ask_vol > 0 else None,
            "theme": themes.get(code, []),
            "in_candidates": code in cands,
        })
    out.sort(key=lambda r: r["gap_pct"], reverse=True)
    return out


def theme_agg(rows: list[dict], top: int = 10, min_members: int = 2) -> list[dict]:
    """按题材聚合竞价强弱:成员数 / 均高开 / 最高板 / 题材总竞价额。

    排序用 均高开 × 成员数 —— 单票高开是个股行为,一群票齐高开才是方向(板块效应)。
    """
    buckets: dict[str, dict] = {}
    for r in rows:
        for t in r.get("theme") or []:
            b = buckets.setdefault(t, {
                "theme": t, "members": 0, "gap_sum": 0.0, "max_board": 0,
                "amount_yi": 0.0, "stocks": [],
            })
            b["members"] += 1
            b["gap_sum"] += r["gap_pct"]
            b["max_board"] = max(b["max_board"], r["prev_boards"])
            b["amount_yi"] += r["amount_yi"]
            b["stocks"].append({
                "code": r["code"], "name": r["name"], "prev_boards": r["prev_boards"],
                "gap_pct": r["gap_pct"], "gap_trend": r["gap_trend"],
                "amount_yi": r["amount_yi"], "grade": r.get("grade", ""),
                "in_candidates": r["in_candidates"],
            })
    res = []
    for b in buckets.values():
        if b["members"] < min_members:
            continue  # 单票题材是个股标签,不构成方向
        b["avg_gap"] = round(b["gap_sum"] / b["members"], 2)
        b["amount_yi"] = round(b["amount_yi"], 2)
        b["strength"] = round(b["avg_gap"] * b["members"], 2)
        b["stocks"].sort(key=lambda s: s["gap_pct"], reverse=True)
        b.pop("gap_sum")
        res.append(b)
    res.sort(key=lambda x: x["strength"], reverse=True)
    return res[:top]


def auction_grade(row: dict, base_grade: str) -> dict:
    """在昨日画像分级(score.grade_candidate)上叠加竞价维度,返回 {grade, notes}。

    竞价维度:高开区间(最佳/过高/不足)、量能是否达标、变化方向(抢筹在加 or 有人砸)。
    """
    gap, amt, trend = row.get("gap_pct", 0.0), row.get("amount_yi", 0.0), row.get("gap_trend", "none")
    delta, notes = 0, []

    if GAP_BEST[0] <= gap <= GAP_BEST[1]:
        delta += 1
        notes.append(f"高开{gap:.1f}%(最佳接力区)")
    elif gap > GAP_TOO_HIGH:
        delta -= 1
        notes.append(f"高开{gap:.1f}%(溢价过高,一步到位)")
    elif gap < GAP_TOO_LOW:
        delta -= 1
        notes.append(f"高开仅{gap:.1f}%(情绪偏弱)")

    if amt >= AMT_OK_YI:
        delta += 1
        notes.append(f"竞价{amt:.2f}亿(有真实承接)")
    elif gap >= GAP_BEST[0]:
        delta -= 1
        notes.append(f"高开但竞价仅{amt:.2f}亿(无量,疑假强)")

    if trend == "up":
        delta += 1
        notes.append("9:20起抬升(抢筹在加)")
    elif trend == "down":
        delta -= 1
        notes.append("9:20起回落(有人砸,防高开低走)")

    grade = base_grade or "B"
    step = _GRADE_UP if delta > 0 else _GRADE_DOWN
    for _ in range(abs(delta)):
        grade = step[grade]
    return {"grade": grade, "notes": notes}
