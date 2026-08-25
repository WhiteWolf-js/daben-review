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
            "first_seal": "092500",
            "last_seal": "092500",   # 超早封 ≤9:45 +2(按最终封板算)
            "break_times": 0,        # 干净 +1
            "turnover": 10,          # 5-15% 中性 0
            "boards": 2,             # 低位身位 +1
        }
        r = grade_candidate(stock, "未知")
        assert r["grade"] == "A+"  # 且过硬门槛(超早+强封+低位+0炸板)
        assert r["score"] == 7     # 3+2+1+0+1
        assert r["position"] == "3成"  # 未知周期基准仓位
        assert "超强封(封流比5.0%)" in r["reasons"]
        assert "超早封(≤9:45稳住,隔日溢价最高)" in r["reasons"]

    def test_weak_late_broken_high_gives_d(self):
        stock = {
            "seal_strength": 0.002,  # 弱封 -1
            "first_seal": "130000",
            "last_seal": "143000",   # 尾盘才封 ≥14:00 -2
            "break_times": 4,        # 炸板≥3 -2
            "turnover": 40,          # 高换手 -1
            "boards": 6,             # 高位≥5 -2
        }
        r = grade_candidate(stock, "未知")
        assert r["grade"] == "D"
        assert r["score"] == -8
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

    def test_seal_time_uses_last_seal_not_first(self):
        """封板时间因子的基准是**最终封板**:回测里 last_seal 判别力强于 first_seal
        (r=-0.270 vs -0.207)且分档单调,故只留 last 一个,别两个都算。"""
        base = {"seal_strength": 0.005, "break_times": 3, "turnover": 40, "boards": 5}
        # 首封超早但拖到尾盘才稳住 → 按尾盘罚,不给超早封加分
        early_first_late_last = grade_candidate(
            {**base, "first_seal": "092500", "last_seal": "143000"}, "未知")
        # 反之:首封晚但很快稳住(同一时刻)→ 中性档
        mid = grade_candidate({**base, "first_seal": "101500", "last_seal": "101500"}, "未知")
        superb = grade_candidate({**base, "first_seal": "092500", "last_seal": "092500"}, "未知")
        assert superb["score"] - mid["score"] == 2                    # 超早封 +2
        assert mid["score"] - early_first_late_last["score"] == 2     # 尾盘 -2
        assert any("尾盘才封" in x for x in early_first_late_last["reasons"])
        assert not any("超早封" in x for x in early_first_late_last["reasons"])

    def test_seal_time_tiers(self):
        base = {"seal_strength": 0.005, "break_times": 3, "turnover": 40, "boards": 5}
        f = lambda t: grade_candidate({**base, "last_seal": t}, "未知")["score"]
        assert f("092500") - f("101500") == 2   # ≤9:45 +2
        assert f("101500") == f("133000")       # 9:45–14:00 全中性(回测无区分)
        assert f("101500") - f("143000") == 2   # ≥14:00 -2

    def test_falls_back_to_first_seal_when_last_missing(self):
        """last_seal 缺失(如尾盘回封票故意留空)时退回首封,不能整个因子失效。"""
        base = {"seal_strength": 0.005, "break_times": 0, "turnover": 40, "boards": 5}
        assert grade_candidate({**base, "first_seal": "092500"}, "未知")["score"] == \
            grade_candidate({**base, "first_seal": "092500", "last_seal": ""}, "未知")["score"]

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

    def test_tuichao_no_extra_downgrade(self):
        """退潮**不再在 base 之外额外降级**(原来 base −2 还要再降 1 级)。

        依据 1999 样本 / 28 交易日回测:退潮胜率 53% / 均溢价 +1.16%,逐日 8 天全为正,
        排中游而非垫底 —— 「照抄市面共识降 1-2 级」把中游周期罚成了最差。
        风险由仓位(≤1成)控制,不重复罚在评级上。
        """
        stock = {"seal_strength": 0.05, "first_seal": "", "break_times": 0,
                 "turnover": 10, "boards": 2}
        r = grade_candidate(stock, "退潮")
        # base -1 +3(超强封) +1(break0) +0(换手10中性) +1(身位) = 4 → A,不再降到 B
        assert r["score"] == 4
        assert r["grade"] == "A"
        assert r["position"] == "≤1成"  # 仓位仍然压住

    def test_tuichao_base_minus_one(self):
        # 退潮基准分 -1(原 -2):中性票 score = -1 → C,不再被额外降级成 D
        r = grade_candidate(self._neutral_stock(), "退潮")
        assert r["score"] == -1
        assert r["grade"] == "C"
        assert r["position"] == "≤1成"

    def test_fenqi_base_minus_one(self):
        """分歧基准分 0 → −1:它是实测最差的周期(50% / +0.81%,中位普遍贴 0)。"""
        r = grade_candidate(self._neutral_stock(), "分歧")
        assert r["score"] == -1
        assert r["grade"] == "C"
        assert r["position"] == "2-3成"

    def test_d_grade_still_forces_avoid(self):
        # D 类无论周期都回避(这条与退潮降级无关,单独锁住)
        stock = {"seal_strength": 0.0, "first_seal": "", "break_times": 3,
                 "turnover": 40, "boards": 6}
        r = grade_candidate(stock, "退潮")
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


class TestPassive:
    """被动上板(同题材封板次序)。回测 704 只可判样本:领头档 72.8%/+3.16%、
    垫底档 49.2%/+0.33%,r=-0.327(目前最强单因子,控制封板时刻后仍成立)。"""

    _BASE = {"seal_strength": 0.005, "first_seal": "103000", "last_seal": "103000",
             "break_times": 0, "turnover": 10, "boards": 1}

    def _s(self, **kw):
        return grade_candidate({**self._BASE, **kw}, "未知")

    def test_leader_plus_two(self):
        assert self._s(passive=0.0)["score"] - self._s()["score"] == 2
        assert any("题材领头" in x for x in self._s(passive=0.0)["reasons"])

    def test_laggard_minus_one(self):
        assert self._s()["score"] - self._s(passive=1.0)["score"] == 1
        assert any("被动上板" in x for x in self._s(passive=1.0)["reasons"])

    def test_middle_neutral(self):
        """0.25–0.75 中间两档回测无区分(55-59% / +0.8~1.0%),必须不加不减。"""
        for v in (0.26, 0.5, 0.75):
            assert self._s(passive=v)["score"] == self._s()["score"], v

    def test_boundaries_inclusive(self):
        assert self._s(passive=0.25)["score"] - self._s()["score"] == 2   # ≤0.25 领头
        assert self._s(passive=0.751)["score"] - self._s()["score"] == -1  # >0.75 垫底

    def test_none_gives_nothing(self):
        """同题材不足 3 只 → passive 为 None(次序无意义),不加不减。"""
        assert self._s(passive=None)["score"] == self._s()["score"]

    def test_zero_is_not_treated_as_missing(self):
        """0.0 是「该题材第一个封板」= 最该加分的情形,**不能被当成缺失**
        (`if passive:` 会把 0.0 当假,必须用 `is not None`)。"""
        assert self._s(passive=0.0)["score"] > self._s()["score"]
