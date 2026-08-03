"""盘中情绪事件判据(纯函数,不碰网络/IO,便于单测)。

盘中不跑 agent(太慢太贵),用规则判据 + 快照对比识别情绪拐点。watcher 负责拉数据、
构造快照、喂本模块判定,命中即通知。三类 P0 事件:

1. 龙头/高度板炸板 —— 上一轮在涨停、这一轮不在(炸开),且是龙头(人气前5)或高度板(≥4板)。
   打板最强的情绪拐点信号:空间被打开/塌了。
2. 炸板潮 —— 实时炸板率突破阈值(退潮/分歧实时预警)。
3. 指数急杀 —— 上证/创业板指近 N 分钟快速下杀(权重砸盘拖情绪)。

去重:每个事件有稳定 key,watcher 维护当日 pushed 集合,已推过的不再推;炸板潮/急杀用
分档 key 允许"恶化"时再推一次。
"""

from __future__ import annotations

import pandas as pd

# 判据阈值(打板经验初值,可按盘感调)
HIGH_BOARD = 4          # ≥4 板算高度板,炸了必推
ZBTIDE_RATE = 0.40      # 炸板率阈值
ZBTIDE_MIN_BASE = 20    # 炸板率基数下限(涨停+炸板),滤早盘小样本误报
IDX_DROP_MIN = 15       # 指数急杀回看分钟数
IDX_DROP_THR = {"上证指数": -0.8, "创业板指": -1.2}  # 近 N 分钟跌幅阈值(%)


def _to_int(v) -> int:
    n = pd.to_numeric(v, errors="coerce")
    return int(n) if pd.notna(n) else 0  # 注:不能用 `n or 0`,NaN 是 truthy 会漏过


def _to_float(v) -> float:
    n = pd.to_numeric(v, errors="coerce")
    return float(n) if pd.notna(n) else 0.0


def build_snapshot(ts: str, limitup: pd.DataFrame, zbgc_count: int,
                   hot_top5: list[str]) -> dict:
    """把一轮实时数据整理成快照 dict(纯计算)。

    limitup: 实时涨停池(fetch 归一后的英文列:code/name/boards/seal_amount/break_times)。
    zbgc_count: 当前炸板池只数。hot_top5: 人气榜前 5 的 6 位代码。
    """
    lim: dict[str, dict] = {}
    if limitup is not None and not limitup.empty:
        for _, r in limitup.iterrows():
            code = str(r.get("code", "")).strip()
            if not code:
                continue
            lim[code] = {
                "name": str(r.get("name", "")),
                "boards": _to_int(r.get("boards")),
                "seal_amount": _to_float(r.get("seal_amount")),
                "break_times": _to_int(r.get("break_times")),
            }
    boards_all = [v["boards"] for v in lim.values()]
    return {
        "ts": ts,
        "limitup": lim,
        "zt_count": len(lim),
        "lianban_count": sum(1 for b in boards_all if b >= 2),
        "max_board": max(boards_all) if boards_all else 0,
        "zbgc_count": int(zbgc_count or 0),
        "hot_top5": [str(c) for c in (hot_top5 or [])[:5]],
    }


def index_drop_pct(index_min: pd.DataFrame, minutes: int = IDX_DROP_MIN) -> float | None:
    """指数近 `minutes` 分钟点位跌幅(%)。输入 index_intraday_min 的 df(需 close 列)。

    取不到/数据不足返回 None。注:指数无"成交均价",只用点位跌幅,不掺 VWAP。
    """
    if index_min is None or index_min.empty or "close" not in index_min:
        return None
    close = pd.to_numeric(index_min["close"], errors="coerce").dropna()
    if len(close) < 2:
        return None
    now = float(close.iloc[-1])
    ago = float(close.iloc[-(minutes + 1)]) if len(close) > minutes else float(close.iloc[0])
    if ago <= 0:
        return None
    return round((now / ago - 1) * 100, 2)


def detect_events(prev: dict | None, cur: dict, index_state: dict[str, float | None],
                  pushed: set[str]) -> list[dict]:
    """对比上一轮/本轮快照 + 指数近 N 分钟跌幅,产出需要推送的新事件。

    prev: 上一轮快照(首轮为 None)。cur: 本轮快照。
    index_state: {指数名: 近N分钟跌幅%(或 None)}。pushed: 当日已推事件 key 集合(本函数不修改)。
    返回 [{type, title, detail, key}],key 未在 pushed 中的才返回。
    """
    events: list[dict] = []

    def emit(etype: str, title: str, detail: str, key: str) -> None:
        if key not in pushed:
            events.append({"type": etype, "title": title, "detail": detail, "key": key})

    # 1) 龙头/高度板炸板:上轮在涨停、本轮不在
    if prev:
        broke = set(prev["limitup"]) - set(cur["limitup"])
        for code in broke:
            info = prev["limitup"][code]
            is_leader = code in prev.get("hot_top5", [])
            is_high = info["boards"] >= HIGH_BOARD
            if not (is_leader or is_high):
                continue
            tag = "龙头" if is_leader else f"{info['boards']}板"
            emit(
                "leader_break",
                f"⚠️ {tag}炸板:{info['name']}",
                f"{info['name']}({code}) {info['boards']}板 于 {cur['ts']} 炸开"
                + ("(人气前5)" if is_leader else ""),
                f"break:{code}",
            )

    # 2) 炸板潮:实时炸板率突破阈值(基数足够)
    base = cur["zt_count"] + cur["zbgc_count"]
    if base >= ZBTIDE_MIN_BASE:
        rate = cur["zbgc_count"] / base
        if rate >= ZBTIDE_RATE:
            bucket = int(rate * 10)  # 0.4→4、0.5→5:每恶化一档补推一次
            emit(
                "zhaban_tide",
                f"🔥 炸板潮:炸板率 {rate:.0%}",
                f"{cur['ts']} 炸板 {cur['zbgc_count']} / 涨停 {cur['zt_count']},炸板率 {rate:.0%}",
                f"zbtide:{bucket}",
            )

    # 3) 指数急杀:近 N 分钟跌幅破阈值
    for name, drop in (index_state or {}).items():
        if drop is None:
            continue
        thr = IDX_DROP_THR.get(name)
        if thr is None or drop > thr:
            continue
        bucket = int(abs(drop) * 10)  # 跌幅每扩大 0.1% 补推一次
        emit(
            "index_plunge",
            f"📉 {name}急杀:{IDX_DROP_MIN}分钟 {drop:.2f}%",
            f"{cur['ts']} {name} 近 {IDX_DROP_MIN} 分钟下杀 {drop:.2f}%(阈值 {thr}%)",
            f"idxdrop:{name}:{bucket}",
        )

    return events
