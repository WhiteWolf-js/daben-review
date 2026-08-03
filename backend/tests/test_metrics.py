"""daban_review.metrics.emotion.compute_emotion 与 ladder.build_ladder/stock_profiles 的测试。

用 pandas 手工构造贴合真实列名的小样本 DataFrame,不触发任何网络。
pools 结构:{"limitup": df, "previous": df, "zbgc": df, "dtgc": df}。
"""

from __future__ import annotations

import pandas as pd
import pytest

from daban_review.metrics.emotion import compute_emotion
from daban_review.metrics.ladder import build_ladder, stock_profiles


# ---------------------------------------------------------------------------
# 构造样本
# ---------------------------------------------------------------------------
def _limitup_df():
    # 今日涨停池:需要 code / boards / industry 列
    return pd.DataFrame([
        {"code": "A001", "boards": 1, "industry": "半导体"},
        {"code": "A002", "boards": 2, "industry": "半导体"},
        {"code": "A003", "boards": 3, "industry": "地产"},
        {"code": "A004", "boards": 1, "industry": "半导体"},
    ])


def _previous_df():
    # 昨日涨停池:需要 code / prev_boards / pct 列
    return pd.DataFrame([
        {"code": "A001", "prev_boards": 1, "pct": 10.0},   # 今日仍涨停(晋级)
        {"code": "A002", "prev_boards": 2, "pct": 5.0},    # 今日仍涨停(高位晋级)
        {"code": "B999", "prev_boards": 1, "pct": -3.0},   # 今日未涨停(炸)
    ])


def _pools():
    return {
        "limitup": _limitup_df(),
        "previous": _previous_df(),
        "zbgc": pd.DataFrame([{"code": "Z1"}]),           # 炸板 1 只
        "dtgc": pd.DataFrame([{"code": "D1"}, {"code": "D2"}]),  # 跌停 2 只
    }


# ---------------------------------------------------------------------------
# compute_emotion
# ---------------------------------------------------------------------------
class TestComputeEmotion:
    def test_counts(self):
        m = compute_emotion(_pools())
        assert m["zt_count"] == 4
        assert m["zbgc_count"] == 1
        assert m["dt_count"] == 2
        assert m["lianban_count"] == 2   # boards>=2 的两只
        assert m["max_board"] == 3

    def test_seal_and_break_rate(self):
        m = compute_emotion(_pools())
        # sealed = 4(封住) + 1(炸板) = 5
        assert m["seal_success_rate"] == 0.8
        assert m["break_rate"] == 0.2

    def test_money_effect_is_prev_pct_mean(self):
        m = compute_emotion(_pools())
        # mean([10.0, 5.0, -3.0]) = 4.0
        assert m["money_effect"] == 4.0

    def test_height_distribution(self):
        m = compute_emotion(_pools())
        # boards = [1,2,3,1]
        assert m["height_dist"] == {1: 2, 2: 1, 3: 1}

    def test_promotion_rates(self):
        m = compute_emotion(_pools())
        # 1进2:prev_boards==1 的 {A001, B999},仅 A001 晋级 → 1/2
        assert m["promo_1to2"] == 0.5
        # 高位:prev_boards>=2 的 {A002},晋级 → 1/1
        assert m["promo_high"] == 1.0
        # 总体:3 只中 2 只晋级 → 2/3
        assert m["promo_overall"] == 0.6667

    def test_phase_hint_faxiao(self):
        # money_effect 4.0>2 且 promo_high 1.0>=0.4 → 发酵
        m = compute_emotion(_pools())
        assert m["phase_hint"] == "发酵"

    def test_phase_gaochao(self):
        # max_board>=5 且 money_effect>3 且 zt_count>=50 → 高潮(阈值从 60 降到 50)
        limitup = pd.DataFrame(
            [{"code": f"C{i}", "boards": 1, "industry": "X"} for i in range(48)]
            + [{"code": "H1", "boards": 5, "industry": "X"},
               {"code": "H2", "boards": 6, "industry": "X"}]
        )  # zt_count = 50, max_board = 6
        previous = pd.DataFrame([{"code": "P", "prev_boards": 1, "pct": 5.0}])  # money_effect = 5 > 3
        m = compute_emotion({"limitup": limitup, "previous": previous,
                             "zbgc": pd.DataFrame(), "dtgc": pd.DataFrame()})
        assert m["zt_count"] == 50
        assert m["max_board"] == 6
        assert m["phase_hint"] == "高潮"

    def test_market_state_concentrated(self):
        m = compute_emotion(_pools())
        # 半导体 3/4 = 75% >= 20% → 主板强势
        assert m["market_state_hint"] == "主板强势(主线集中于「半导体」,占比75%)"

    def test_empty_pools(self):
        m = compute_emotion({})
        assert m["zt_count"] == 0
        assert m["lianban_count"] == 0
        assert m["max_board"] == 0
        assert m["seal_success_rate"] == 0.0
        assert m["break_rate"] == 0.0
        assert m["money_effect"] is None
        assert m["height_dist"] == {}
        assert m["promo_1to2"] is None
        assert m["promo_high"] is None
        assert m["promo_overall"] is None
        assert m["phase_hint"] == "未知"
        assert m["market_state_hint"] == "未知"

    def test_no_previous_pool_promotions_none(self):
        pools = _pools()
        pools["previous"] = pd.DataFrame()
        m = compute_emotion(pools)
        assert m["money_effect"] is None
        assert m["promo_overall"] is None
        # 今日池仍在,计数不受影响
        assert m["zt_count"] == 4

    def test_dispersed_market_state(self):
        # 涨停行业分散,单一行业占比 < 20% → 震荡抱团
        limitup = pd.DataFrame([
            {"code": f"C{i}", "boards": 1, "industry": f"行业{i}"} for i in range(10)
        ])
        m = compute_emotion({"limitup": limitup})
        assert m["market_state_hint"].startswith("震荡抱团")

    def test_phase_tuichao(self):
        # money_effect<0 且 break_rate>=0.4 → 退潮
        pools = {
            "limitup": pd.DataFrame([{"code": "A", "boards": 1, "industry": "X"}]),
            "previous": pd.DataFrame([{"code": "P", "prev_boards": 1, "pct": -5.0}]),
            "zbgc": pd.DataFrame([{"code": "Z1"}, {"code": "Z2"}, {"code": "Z3"}]),
            "dtgc": pd.DataFrame(),
        }
        m = compute_emotion(pools)
        # break_rate = 3/(1+3)=0.75, money_effect=-5 → 退潮
        assert m["break_rate"] == 0.75
        assert m["phase_hint"] == "退潮"

    def test_phase_bingdian(self):
        # zt<=30 且 max_board<=2 且 money_effect<0 → 冰点(且 break_rate 不到退潮阈值)
        pools = {
            "limitup": pd.DataFrame([
                {"code": "A", "boards": 1, "industry": "X"},
                {"code": "B", "boards": 2, "industry": "X"},
            ]),
            "previous": pd.DataFrame([{"code": "P", "prev_boards": 1, "pct": -1.0}]),
            "zbgc": pd.DataFrame(),   # break_rate = 0
            "dtgc": pd.DataFrame(),
        }
        m = compute_emotion(pools)
        assert m["phase_hint"] == "冰点"


# ---------------------------------------------------------------------------
# ladder.stock_profiles / build_ladder
# ---------------------------------------------------------------------------
def _ladder_df():
    return pd.DataFrame([
        {"code": "000001", "name": "AA", "boards": 2, "pct": 10.02,
         "seal_amount": 1000, "float_mv": 50000, "first_seal": "093000",
         "last_seal": "093000", "break_times": 0, "turnover": 8.5,
         "zt_stat": "2/3", "industry": "半导体"},
        {"code": "000002", "name": "BB", "boards": 2, "pct": 9.98,
         "seal_amount": 3000, "float_mv": 50000, "first_seal": "093000",
         "last_seal": "093000", "break_times": 0, "turnover": 8.5,
         "zt_stat": "2/3", "industry": "半导体"},
        {"code": "000003", "name": "CC", "boards": 1, "pct": 10.0,
         "seal_amount": 500, "float_mv": 0, "first_seal": "100000",
         "last_seal": "100000", "break_times": 1, "turnover": 12.0,
         "zt_stat": "1/1", "industry": "地产"},
    ])


class TestStockProfiles:
    def test_seal_strength_computed(self):
        profiles = {p["code"]: p for p in stock_profiles(_ladder_df())}
        assert profiles["000001"]["seal_strength"] == 0.02   # 1000/50000
        assert profiles["000002"]["seal_strength"] == 0.06   # 3000/50000

    def test_zero_float_mv_yields_zero_strength(self):
        profiles = {p["code"]: p for p in stock_profiles(_ladder_df())}
        # float_mv=0 → 除零保护 → 0.0
        assert profiles["000003"]["seal_strength"] == 0.0

    def test_types_and_fields(self):
        p = stock_profiles(_ladder_df())[0]
        assert isinstance(p["code"], str)
        assert isinstance(p["boards"], int)
        assert isinstance(p["break_times"], int)
        assert isinstance(p["turnover"], float)
        assert p["first_seal"] == "093000"
        assert p["industry"] == "半导体"

    def test_missing_columns_use_defaults(self):
        # 只有 code / boards 列,其余缺失应走 _num 默认(不抛)
        df = pd.DataFrame([{"code": "600001", "boards": 3}])
        p = stock_profiles(df)[0]
        assert p["code"] == "600001"
        assert p["boards"] == 3
        assert p["seal_amount"] == 0.0
        assert p["seal_strength"] == 0.0
        assert p["turnover"] == 0.0

    def test_empty_dataframe(self):
        assert stock_profiles(pd.DataFrame()) == []


class TestBuildLadder:
    def test_grouped_by_boards_desc(self):
        ladder = build_ladder(_ladder_df())
        assert list(ladder.keys()) == [2, 1]   # 板级从高到低

    def test_within_board_sorted_by_seal_strength_desc(self):
        ladder = build_ladder(_ladder_df())
        # 2 板档内按封单强度降序:000002(0.06) 在 000001(0.02) 之前
        assert [p["code"] for p in ladder[2]] == ["000002", "000001"]
        assert ladder[2][0]["seal_strength"] >= ladder[2][1]["seal_strength"]

    def test_single_board_group(self):
        ladder = build_ladder(_ladder_df())
        assert [p["code"] for p in ladder[1]] == ["000003"]

    def test_empty_dataframe(self):
        assert build_ladder(pd.DataFrame()) == {}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
