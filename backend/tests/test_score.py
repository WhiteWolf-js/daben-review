"""候选票客观分级 daban_review.metrics.score 的单元测试(纯计算,无网络)。"""

from __future__ import annotations

import pytest

from daban_review.metrics.score import _first_seal_minutes, grade_candidate


# ---------------------------------------------------------------------------
# _first_seal_minutes:首封时间字符串解析
# ---------------------------------------------------------------------------
class TestFirstSealMinutes:
    def test_normal_hhmmss(self):
        assert _first_seal_minutes("092500") == 9 * 60 + 25  # 565

    def test_open_board_930(self):
        assert _first_seal_minutes("093000") == 9 * 60 + 30

    def test_afternoon_1300(self):
        assert _first_seal_minutes("130000") == 13 * 60

    def test_strips_non_digits(self):
        # 带冒号也能解析
        assert _first_seal_minutes("09:25:00") == 565

    def test_illegal_non_numeric(self):
        assert _first_seal_minutes("abc") is None

    def test_empty_string(self):
        assert _first_seal_minutes("") is None

    def test_too_short(self):
        # 不足 4 位数字
        assert _first_seal_minutes("093") is None

    def test_invalid_minute(self):
        # 分钟 60 越界
        assert _first_seal_minutes("0960") is None

    def test_invalid_hour(self):
        # 小时 99 越界
        assert _first_seal_minutes("9999") is None

    def test_accepts_non_string_input(self):
        # 内部 str() 兜底,非字符串不报错(用无前导零的时刻验证)
        assert _first_seal_minutes(130000) == 13 * 60

    def test_int_loses_leading_zero(self):
        # 传 int 会丢前导零:92500 → "92500" → 小时被解析为 92 → None
        assert _first_seal_minutes(92500) is None


# ---------------------------------------------------------------------------
# grade_candidate:综合分级 + 仓位
# ---------------------------------------------------------------------------
class TestGradeCandidate:
    def test_strong_early_clean_gives_a_plus(self):
        stock = {
            "seal_strength": 0.05,   # 超强封 ≥3% +3
            "first_seal": "092500",  # 超早封 ≤9:45 +2
            "break_times": 0,        # 干净 +1
            "turnover": 10,          # 5-15% 中性 0
            "boards": 2,             # 低位身位 +1
        }
        r = grade_candidate(stock, "未知")
        assert r["grade"] == "A+"  # 且过硬门槛(超早+强封+低位+0炸板)
        assert r["score"] == 7     # 3+2+1+0+1
        assert r["position"] == "3成"  # 未知周期基准仓位
        assert "超强封(封流比5.0%)" in r["reasons"]
        assert "超早封(≤9:45,隔日溢价最高)" in r["reasons"]

    def test_weak_late_broken_high_gives_d(self):
        stock = {
            "seal_strength": 0.002,  # 弱封 -1
            "first_seal": "130000",  # 晚封 -1
            "break_times": 4,        # 炸板≥3 -2
            "turnover": 40,          # 高换手 -1
            "boards": 6,             # 高位≥5 -2
        }
        r = grade_candidate(stock, "未知")
        assert r["grade"] == "D"
        assert r["score"] == -7
        # D 类无论周期都回避
        assert r["position"] == "回避/空仓"
        assert any("炸板4次" in x for x in r["reasons"])
        assert any("6板高位" in x for x in r["reasons"])

    def test_breaks_zero_bonus_vs_three_penalty(self):
        base = {"seal_strength": 0.01, "turnover": 20, "boards": 4, "first_seal": ""}
        clean = grade_candidate({**base, "break_times": 0}, "未知")
        broken = grade_candidate({**base, "break_times": 3}, "未知")
        # 炸板 0 得 +1,炸板 3 得 -2,共差 3 分
        assert clean["score"] - broken["score"] == 3

    def test_turnover_reversed_low_best_high_penalized(self):
        # 回测校准后方向反转:<5% 缩量锁筹 +1,15-35% 与 >35% 均 -1,5-15% 中性
        base = {"seal_strength": 0.01, "break_times": 0, "boards": 4, "first_seal": ""}
        low = grade_candidate({**base, "turnover": 3}, "未知")     # <5% +1
        mid = grade_candidate({**base, "turnover": 10}, "未知")    # 5-15% 中性 0
        highish = grade_candidate({**base, "turnover": 20}, "未知")  # 15-35% -1
        very_high = grade_candidate({**base, "turnover": 40}, "未知")  # >35% -1
        assert low["score"] - mid["score"] == 1
        assert mid["score"] - highish["score"] == 1
        assert highish["score"] == very_high["score"]
        assert any("缩量锁筹" in x for x in low["reasons"])
        assert any("高换手" in x for x in very_high["reasons"])

    def test_low_turnover_rewarded_over_midhigh(self):
        # 缩量(<5%)优于偏高换手(15-35%),差 2 分
        base = {"seal_strength": 0.01, "break_times": 0, "boards": 4, "first_seal": ""}
        low = grade_candidate({**base, "turnover": 2}, "未知")
        midhigh = grade_candidate({**base, "turnover": 25}, "未知")
        assert low["score"] - midhigh["score"] == 2

    def test_board_position_low_bonus_high_penalty(self):
        base = {"seal_strength": 0.01, "break_times": 0, "turnover": 20, "first_seal": ""}
        low = grade_candidate({**base, "boards": 2}, "未知")   # 1-3 板 +1
        high = grade_candidate({**base, "boards": 5}, "未知")  # ≥5 板 -2
        assert low["score"] - high["score"] == 3
        assert any("5板高位" in x for x in high["reasons"])

    def test_first_seal_illegal_no_time_effect(self):
        # 非法首封时间 → fmin None → 不加不减;break=0(+1) 与 4板(-1) 相抵 → 0
        base = {"seal_strength": 0.01, "break_times": 0, "turnover": 20, "boards": 4}
        illegal = grade_candidate({**base, "first_seal": "xx"}, "未知")
        legal_early = grade_candidate({**base, "first_seal": "092500"}, "未知")
        assert illegal["score"] == 0
        # 合法超早封(≤9:45)比非法首封多 +2
        assert legal_early["score"] - illegal["score"] == 2

    def test_a_plus_requires_hard_gate_not_just_score(self):
        # 5板高位即便强封+超早+0炸板凑到 A+ 分,也被硬门槛(须低位1-3)拦回 A
        stock = {"seal_strength": 0.05, "first_seal": "092500", "break_times": 0,
                 "turnover": 10, "boards": 5}
        r = grade_candidate(stock, "发酵")  # base+1 +2(封)+2(早)+1(净)+1(换)-2(5板) = 5 → A+初判
        assert r["score"] == 5
        assert r["grade"] == "A"  # boards5 违反低位,降 A
        assert any("A+硬门槛" in x for x in r["reasons"])

    def test_a_plus_gate_passes_when_all_hard_conditions_met(self):
        # 超早+强封+低位+0炸板 全满足 → 保留 A+
        stock = {"seal_strength": 0.03, "first_seal": "093000", "break_times": 0,
                 "turnover": 10, "boards": 2}
        r = grade_candidate(stock, "未知")  # +2+2+1+1 = 6
        assert r["grade"] == "A+"
        assert not any("A+硬门槛" in x for x in r["reasons"])

    def test_first_seal_only_super_early_and_afternoon_scored(self):
        # 回测校准:9:45–13:00 中性(无区分),仅 ≤9:45 +2、午后 -1
        base = {"seal_strength": 0.005, "break_times": 3, "turnover": 40, "boards": 5}
        superb = grade_candidate({**base, "first_seal": "092500"}, "未知")   # +2
        midday = grade_candidate({**base, "first_seal": "101500"}, "未知")   # 中性 0
        late = grade_candidate({**base, "first_seal": "140000"}, "未知")     # 午后 -1
        assert superb["score"] - midday["score"] == 2
        assert midday["score"] - late["score"] == 1
        assert not any("早盘封" in x for x in midday["reasons"])

    def test_seal_strength_tiers(self):
        # 封流比分档:≥3% +3 / 2-3% +2 / 1-2% +1 / <1% -1
        base = {"break_times": 0, "turnover": 10, "boards": 2, "first_seal": ""}
        weak = grade_candidate({**base, "seal_strength": 0.005}, "未知")     # -1
        mid = grade_candidate({**base, "seal_strength": 0.015}, "未知")      # +1
        strong = grade_candidate({**base, "seal_strength": 0.025}, "未知")   # +2
        superb = grade_candidate({**base, "seal_strength": 0.05}, "未知")    # +3
        assert mid["score"] - weak["score"] == 2
        assert strong["score"] - mid["score"] == 1
        assert superb["score"] - strong["score"] == 1
        assert any("超强封" in x for x in superb["reasons"])
        assert any("中封" in x for x in mid["reasons"])

    def test_board_four_penalized(self):
        # 4板 -1 vs 3板 +1,差 2
        base = {"seal_strength": 0.015, "break_times": 0, "turnover": 20, "first_seal": ""}
        b3 = grade_candidate({**base, "boards": 3}, "未知")
        b4 = grade_candidate({**base, "boards": 4}, "未知")
        assert b3["score"] - b4["score"] == 2
        assert any("4板高位" in x for x in b4["reasons"])


# ---------------------------------------------------------------------------
# 情绪周期基准分与降级规则
# ---------------------------------------------------------------------------
class TestPhaseEffects:
    def _neutral_stock(self):
        # 中性票:中封 0.01(+1)+break0(+1) 与 换手20(-1)+4板(-1) 相抵,净因子 0,故 score = 周期基准分
        return {"seal_strength": 0.01, "break_times": 0, "turnover": 20, "boards": 4, "first_seal": ""}

    def test_faxiao_base_plus_one(self):
        # 发酵基准分 +1:中性票 score = 1(base) + 0(净因子) = 1 → B
        r = grade_candidate(self._neutral_stock(), "发酵")
        assert r["score"] == 1
        assert r["grade"] == "B"
        assert r["position"] == "4-6成"

    def test_bingdian_base_minus_one(self):
        # 冰点基准分 -1:score = -1 + 0 = -1 → C
        r = grade_candidate(self._neutral_stock(), "冰点")
        assert r["score"] == -1
        assert r["grade"] == "C"
        assert r["position"] == "≤2成"

    def test_unknown_phase_base_zero(self):
        r = grade_candidate(self._neutral_stock(), "未知")
        assert r["score"] == 0
        assert r["grade"] == "B"
        assert r["position"] == "3成"

    def test_undefined_phase_falls_back_to_default(self):
        # 未在 _PHASE_BASE 中的周期名 → 默认 (0, "3成")
        r = grade_candidate(self._neutral_stock(), "不存在的周期")
        assert r["score"] == 0
        assert r["position"] == "3成"

    def test_tuichao_downgrades_one_level(self):
        # 退潮:基准 -2,一只强封低位早封票在其他周期本是 A,退潮降为 B
        stock = {"seal_strength": 0.05, "first_seal": "", "break_times": 0,
                 "turnover": 10, "boards": 2}
        r = grade_candidate(stock, "退潮")
        # base -2 +3(超强封) +1(break0) +0(换手10中性) +1(身位) = 3 → A → 降级 B
        assert r["score"] == 3
        assert r["grade"] == "B"
        assert r["position"] == "≤1成"

    def test_tuichao_downgrade_to_d_forces_avoid(self):
        # 退潮:本是 C 的票降级为 D,仓位被强制改为回避
        stock = {"seal_strength": 0.01, "first_seal": "", "break_times": 0,
                 "turnover": 0, "boards": 4}
        r = grade_candidate(stock, "退潮")
        # base -2 +1(中封0.01) +1(break0) +0(换手0) -1(4板) = -1 → C → 降级 D
        assert r["score"] == -1
        assert r["grade"] == "D"
        assert r["position"] == "回避/空仓"

    def test_gaochao_reduces_position(self):
        # 高潮基准分 0,仓位建议减仓 2-3 成
        r = grade_candidate(self._neutral_stock(), "高潮")
        assert r["position"] == "2-3成"


class TestWeakToStrong:
    """弱转强(前日炸板 → 今日涨停)+2。

    本地回测 22 交易日 1508 样本:弱转强 n=27 胜率 74.1% / 均溢价 +3.19%,
    同板位(它们 26/27 是首板)对照 n=1254 胜 58% / 均 +1.24%,置换检验 p=0.0136。
    """

    _BASE = {"seal_strength": 0.005, "first_seal": "103000", "break_times": 0,
             "turnover": 10, "boards": 1}

    def test_adds_two_points(self):
        off = grade_candidate(self._BASE, "未知")
        on = grade_candidate({**self._BASE, "w2s": True}, "未知")
        assert on["score"] - off["score"] == 2
        assert "弱转强(昨炸板今涨停)" in on["reasons"]

    def test_absent_field_gives_no_bonus(self):
        """老调用方供不上 w2s 就不该拿到加分(向后兼容的关键)。"""
        assert grade_candidate(self._BASE, "未知")["score"] == \
            grade_candidate({**self._BASE, "w2s": False}, "未知")["score"]

    def test_can_lift_grade(self):
        """+2 足以把 B 抬到 A —— 这才是这个因子的实际作用。"""
        assert grade_candidate(self._BASE, "未知")["grade"] == "B"
        assert grade_candidate({**self._BASE, "w2s": True}, "未知")["grade"] == "A"

    def test_does_not_bypass_a_plus_hard_gate(self):
        """弱转强票平均封流比只有 0.82%,过不了 A+ 硬门槛(需强封)——
        不能因为加了 2 分就让它跳过门禁,n=27 不足以支撑放宽硬门槛。"""
        r = grade_candidate({**self._BASE, "first_seal": "092500", "w2s": True}, "未知")
        assert r["grade"] != "A+"


class TestRobustness:
    def test_empty_stock_defaults(self):
        # 全缺省字段:仅 break=0 给 +1
        r = grade_candidate({}, "未知")
        assert r["grade"] == "B"
        assert r["score"] == 1
        assert r["reasons"] == []

    def test_none_values_treated_as_zero(self):
        stock = {"seal_strength": None, "break_times": None,
                 "turnover": None, "boards": None, "first_seal": None}
        r = grade_candidate(stock, "未知")
        assert r["score"] == 1  # 同全缺省

    def test_string_numeric_fields_coerced(self):
        # 字段是字符串数字也应被 int/float 兜底
        stock = {"seal_strength": "0.05", "break_times": "0",
                 "turnover": "10", "boards": "2", "first_seal": "092500"}
        r = grade_candidate(stock, "未知")
        assert r["grade"] == "A+"
        assert r["score"] == 7


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
