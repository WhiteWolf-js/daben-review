"""竞价高开榜:对当日连板 + 首板强票算今开/昨收高开幅度,供 agent 与 REST 复用。

抽成公用函数避免 agent.runner 与 app.service 循环依赖。
"""

from __future__ import annotations

from ..data import akshare_client as ak
from .ladder import stock_profiles


def auction_board(pools: dict, date: str, shouban_top: int = 15) -> list[dict]:
    """连板(≥2)全取 + 首板按封单强度 top,算竞价高开,按高开降序。"""
    lim = pools.get("limitup")
    if lim is None or lim.empty:
        return []
    profs = stock_profiles(lim)
    lianban = [p for p in profs if p["boards"] >= 2]
    shouban = sorted(
        [p for p in profs if p["boards"] == 1], key=lambda x: x["seal_strength"], reverse=True
    )[:shouban_top]
    out = []
    for p in lianban + shouban:
        a = ak.auction_metrics(p["code"], date)
        if a:
            a.update({"name": p["name"], "boards": p["boards"], "industry": p["industry"]})
            out.append(a)
    out.sort(key=lambda x: x["gap_pct"], reverse=True)
    return out
