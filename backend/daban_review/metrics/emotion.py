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


# 恶化信号阈值。跌停用「跌停/涨停」比值而不是绝对数 —— 绝对数受市况基数影响没法跨日比
# (0728 跌停 49 / 涨停 61 = 0.80,前一日 6 / 111 = 0.05,比值一眼看出恶化)
_DT_RATIO_BAD = 0.5
_BREAK_RATE_BAD = 0.35
_PROMO_BAD = 0.15
# 晋级率低必须配合封板质量差才算恶化:涨停家数一多,首板占比高,总晋级率会被基数天然拉低
# (实测 0721 涨停 121、炸板率仅 6.2%、赚钱 +1.36,总晋级 9.4% —— 封得极死,不是恶化)
_PROMO_BREAK_MIN = 0.20


def _dt_ratio(m: dict) -> float:
    """跌停/涨停。涨停为 0 时:有跌停算最坏(1.0),都没有算 0。"""
    zt, dt = m["zt_count"], m["dt_count"]
    return dt / zt if zt else (1.0 if dt else 0.0)


def _bad_signals(m: dict) -> tuple[int, int]:
    """恶化信号 →(强, 弱)。

    **强弱要分开**:「钱在亏 / 跌停涌现」是资金真的在离场;「炸板率高 / 接力断」只是封板
    质量差,钱可能还在场内。早期版本简单计数 `bad>=2` 就判退潮,结果 0710(涨停 92、
    跌停 4、炸板 49.7%)、0722(涨停 47、跌停 8)都被误判成退潮 —— 它们其实是分歧;
    而且炸板率高与晋级率低本身高度相关,计数等于把同一个现象数了两次。
    """
    me = m["money_effect"]
    po = m.get("promo_overall")
    br = m["break_rate"]
    strong = sum([
        me is not None and me < 0,        # 昨日涨停股今日平均亏钱
        _dt_ratio(m) >= _DT_RATIO_BAD,    # 跌停家数逼近涨停家数
    ])
    weak = sum([
        br >= _BREAK_RATE_BAD,                                        # 封不住
        po is not None and po < _PROMO_BAD and br >= _PROMO_BREAK_MIN,  # 接力断且封板质量差
    ])
    return strong, weak


def _phase_hint(m: dict) -> str:
    """情绪周期单日粗判(冰点/修复/发酵/高潮/退潮/分歧)。仅供 agent 参考。

    判据顺序:未知 → 高潮/冰点(两端极值)→ 恶化计数 → 发酵/修复 → 分歧兜底。
    **改这里必须同步核对 `metrics/score.py` 的按周期加减分与回测分层口径**(两者同口径)。
    """
    me = m["money_effect"]
    if me is None:
        return "未知"
    strong, weak = _bad_signals(m)
    zt = m["zt_count"]
    dt_ratio = _dt_ratio(m)

    # 高潮:高度 + 强赚钱 + 面广,且**一个恶化信号都没有**(涨停≥50 对齐 SkillHub;
    # 60 在缩量市几乎不触发)。带着一堆跌停的普涨顶不是高潮
    if m["max_board"] >= 5 and me > 3 and zt >= 50 and strong + weak == 0:
        return "高潮"
    if zt <= 30 and m["max_board"] <= 2 and me < 0:
        return "冰点"
    # 退潮要有「资金离场」的硬证据:两个强信号,或一强带一弱。
    # 只有弱信号(封不住、接力差)是分歧不是退潮 —— 钱还在场里打,只是打得难看
    if strong >= 2 or (strong >= 1 and weak >= 1):
        return "退潮"
    if me > 2 and (m.get("promo_high") or 0) >= 0.4:
        return "发酵"
    # 修复要求确实在赚钱:+0.6% 贴着零轴不算修复,老判据 `me>0` 太松
    if me >= 1 and strong + weak == 0 and dt_ratio < 0.3:
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
