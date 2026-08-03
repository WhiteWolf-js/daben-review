"""情绪温度骨架:涨停/连板/晋级率/炸板率/赚钱效应,以及情绪周期与市场状态的规则初判。

规则初判仅是单日 heuristic,agent 层会结合历史序列与盘面属性再修正。
"""

from __future__ import annotations

import pandas as pd


def _to_int(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0).astype(int)


def _to_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def compute_emotion(pools: dict[str, pd.DataFrame]) -> dict:
    """输入 fetch_day 的结果,返回情绪指标 dict。"""
    limitup = pools.get("limitup", pd.DataFrame())
    previous = pools.get("previous", pd.DataFrame())
    zbgc = pools.get("zbgc", pd.DataFrame())
    dtgc = pools.get("dtgc", pd.DataFrame())

    zt_count = len(limitup)
    zbgc_count = len(zbgc)
    dt_count = len(dtgc)

    boards = _to_int(limitup["boards"]) if zt_count else pd.Series(dtype=int)
    lianban_count = int((boards >= 2).sum())
    max_board = int(boards.max()) if zt_count else 0

    sealed = zt_count + zbgc_count  # 尝试涨停的总数(封住+炸板)
    seal_success_rate = round(zt_count / sealed, 4) if sealed else 0.0
    break_rate = round(zbgc_count / sealed, 4) if sealed else 0.0

    # 晋级率:昨日连板股今日是否再涨停(以今日涨停池为准)
    promo = _promotion(previous, limitup)

    # 赚钱效应:昨日涨停股今日平均涨跌幅
    money_effect = None
    if len(previous):
        money_effect = round(float(_to_float(previous["pct"]).mean()), 2)

    # 连板高度分布
    height_dist = {}
    if zt_count:
        vc = boards.value_counts().sort_index()
        height_dist = {int(k): int(v) for k, v in vc.items()}

    metrics = {
        "zt_count": zt_count,
        "lianban_count": lianban_count,
        "max_board": max_board,
        "zbgc_count": zbgc_count,
        "dt_count": dt_count,
        "seal_success_rate": seal_success_rate,
        "break_rate": break_rate,
        "money_effect": money_effect,
        "height_dist": height_dist,
        **promo,
    }
    metrics["phase_hint"] = _phase_hint(metrics)
    metrics["market_state_hint"] = _market_state_hint(limitup)
    return metrics


def _promotion(previous: pd.DataFrame, limitup: pd.DataFrame) -> dict:
    """晋级率:1进2、高位(>=2板)晋级、总体。"""
    if not len(previous) or not len(limitup):
        return {"promo_1to2": None, "promo_high": None, "promo_overall": None}
    prev_boards = _to_int(previous["prev_boards"])
    zt_codes = set(limitup["code"].astype(str))
    promoted = previous["code"].astype(str).isin(zt_codes)

    def rate(mask: pd.Series) -> float | None:
        base = int(mask.sum())
        if not base:
            return None
        return round(int((mask & promoted).sum()) / base, 4)

    return {
        "promo_1to2": rate(prev_boards == 1),
        "promo_high": rate(prev_boards >= 2),
        "promo_overall": rate(prev_boards >= 1),
    }


def _phase_hint(m: dict) -> str:
    """情绪周期单日粗判(冰点/修复/发酵/高潮/退潮/分歧)。仅供 agent 参考。"""
    me = m["money_effect"]
    if me is None:
        return "未知"
    if m["max_board"] >= 5 and me > 3 and m["zt_count"] >= 50:  # 涨停≥50家(对齐 SkillHub;60 在缩量市几乎不触发)
        return "高潮"
    if me < 0 and m["break_rate"] >= 0.4:
        return "退潮"
    if m["zt_count"] <= 30 and m["max_board"] <= 2 and me < 0:
        return "冰点"
    if me > 2 and (m.get("promo_high") or 0) and (m["promo_high"] or 0) >= 0.4:
        return "发酵"
    if me > 0:
        return "修复"
    return "分歧"


def _market_state_hint(limitup: pd.DataFrame) -> str:
    """震荡抱团 vs 主板强势:据涨停在行业上的集中度粗判。"""
    if not len(limitup):
        return "未知"
    top = limitup["industry"].value_counts()
    if top.empty:
        return "未知"
    concentration = top.iloc[0] / len(limitup)
    lead = top.index[0]
    if concentration >= 0.2:
        return f"主板强势(主线集中于「{lead}」,占比{concentration:.0%})"
    return "震荡抱团(涨停分散,无明显主线)"
