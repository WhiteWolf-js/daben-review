"""异动榜核心逻辑单测:窗口统计 / tier 分档 / 排序 / actual_window 退化。

只测纯函数(_window_stats / _tier / build_abnormal_rank 的排序与打标),
不连真实 mootdx:fetch_bars 与 universe 都注入造数据。
"""

from __future__ import annotations

import pandas as pd

from daban_review.metrics.abnormal import build_abnormal_rank, _tier, _window_stats


def test_window_stats_full_window():
    # 11 根,老→新,基准=第一根 10,末根 20 → +100%
    closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    st = _window_stats(closes, 10)
    assert st["pct_window"] == 1.0
    assert st["pct_today"] == round(20 / 19 - 1, 4)
    assert st["actual_window"] == 10


def test_window_stats_short_history_degrades():
    # 只有 4 根、window=10:基准回退到第一根,actual_window=3
    closes = [10, 12, 15, 18]
    st = _window_stats(closes, 10)
    assert st["pct_window"] == round(18 / 10 - 1, 4)  # +80%
    assert st["actual_window"] == 3


def test_window_stats_empty():
    assert _window_stats([], 10)["pct_window"] == 0.0
    assert _window_stats([None, 0.0], 10)["pct_window"] == 0.0


def test_tier_thresholds():
    assert _tier(2.5, 0.05) == "triple"
    assert _tier(1.0, 0.0) == "double"
    assert _tier(0.8, 0.03) == "entering"  # 60-99% 且当日涨
    assert _tier(0.8, -0.02) == "warm"  # 当日跌,不算进入
    assert _tier(0.5, 0.05) == "warm"  # 不足 60%


def _df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


def test_build_rank_sorts_and_tags():
    universe = {
        "A": {"code": "A", "name": "甲", "industry": "半导体", "boards": 3, "pct_today_pool": 10.0, "price_pool": 20.0},
        "B": {"code": "B", "name": "乙", "industry": "中药", "boards": 0, "pct_today_pool": -2.0, "price_pool": 5.0},
        "C": {"code": "C", "name": "丙", "industry": "", "boards": 2, "pct_today_pool": 5.0, "price_pool": 8.0},
    }
    # A: 10→20 翻倍(+100%)  B: 5→15 (+200%)  C: 8→10 (+25%)
    bars = {
        "A": _df([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]),
        "B": _df([5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]),
        "C": _df([8, 8.5, 9, 9.5, 10, 10, 10, 10, 10, 10, 10]),
    }
    out = build_abnormal_rank(
        "20260903", 10, fetch_bars=lambda c, n: bars[c], universe=universe
    )
    assert out["fetched"] == 3
    pcts = [r["pct_window"] for r in out["rows"]]
    assert pcts == sorted(pcts, reverse=True)  # 降序
    by = {r["code"]: r for r in out["rows"]}
    assert by["B"]["tier"] == "triple"   # +200%
    assert by["A"]["tier"] == "double"   # +100%
    assert by["C"]["tier"] == "warm"     # +25%


def test_build_rank_skips_fetch_failure():
    universe = {"X": {"code": "X", "name": "X", "industry": "", "boards": 0, "pct_today_pool": 0, "price_pool": 0}}

    def fail(code, n):
        raise RuntimeError("mootdx 挂了")

    out = build_abnormal_rank("20260903", 10, fetch_bars=fail, universe=universe)
    assert out["fetched"] == 0
    assert out["rows"] == []
