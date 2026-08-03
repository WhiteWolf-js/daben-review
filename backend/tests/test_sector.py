"""daban_review.metrics.sector 的测试:板块名匹配 + 题材热度附板块强度。

纯本地构造,不触发网络(板块行情由参数注入)。
"""

from __future__ import annotations

import pandas as pd
import pytest

from daban_review.metrics.sector import _norm_name, match_quote, sector_heat, theme_heat


def _quotes() -> dict[str, dict]:
    """模拟 akshare_client.concept_quotes 的返回(同花顺涨停板块榜)。"""
    return {
        "存储芯片": {"pct": 3.21, "limit_up_num": 8, "lianban_num": 2, "high": "5天5板", "code": "885001"},
        "人形机器人": {"pct": -1.52, "limit_up_num": 4, "lianban_num": 1, "high": "首板", "code": "885002"},
        "电力": {"pct": 0.8, "limit_up_num": 6, "lianban_num": 3, "high": "8天7板", "code": "885003"},
        # 真实数据里的两种命名差异(实测失配主因)
        "2026中报预增": {"pct": 3.0, "limit_up_num": 20, "lianban_num": 1, "high": "8天7板", "code": "885004"},
        "数据中心(AIDC)": {"pct": 3.4, "limit_up_num": 17, "lianban_num": 4, "high": "5天5板", "code": "885005"},
    }


class TestNormName:
    def test_strips_suffix(self):
        assert _norm_name("存储芯片概念") == "存储芯片"
        assert _norm_name("人形机器人板块") == "人形机器人"
        assert _norm_name("存储芯片概念股") == "存储芯片"

    def test_strips_bracket(self):
        assert _norm_name("先进封装(Chiplet)") == "先进封装"
        assert _norm_name("先进封装（Chiplet）概念") == "先进封装"
        assert _norm_name("数据中心(AIDC)") == "数据中心"

    def test_strips_year_prefix(self):
        # 同花顺板块爱带年份:「2026中报预增」↔ 涨停原因「中报预增」
        assert _norm_name("2026中报预增") == "中报预增"
        assert _norm_name("2025年报预增") == "年报预增"

    def test_plain_name_unchanged(self):
        assert _norm_name("电力") == "电力"


class TestMatchQuote:
    def test_exact(self):
        assert match_quote("存储芯片", _quotes())["pct"] == 3.21

    def test_suffix_normalized(self):
        # 同花顺「存储芯片概念」↔ 东财「存储芯片」
        assert match_quote("存储芯片概念", _quotes())["pct"] == 3.21

    def test_substring_both_directions(self):
        # 题材名更长,含板块名
        assert match_quote("人形机器人产业链", _quotes())["pct"] == -1.52

    def test_year_prefix_board_matched(self):
        # 涨停原因「中报预增」↔ 板块「2026中报预增」
        assert match_quote("中报预增", _quotes())["pct"] == 3.0

    def test_bracket_board_matched(self):
        # 涨停原因「数据中心」↔ 板块「数据中心(AIDC)」
        assert match_quote("数据中心", _quotes())["pct"] == 3.4

    def test_short_name_not_fuzzy_matched(self):
        # 「芯片」只有 2 字,不做子串匹配以免误配「存储芯片」
        assert match_quote("芯片", _quotes()) is None

    def test_no_match(self):
        assert match_quote("猪肉", _quotes()) is None

    def test_empty_inputs(self):
        assert match_quote("", _quotes()) is None
        assert match_quote("存储芯片", {}) is None


class TestThemeHeatQuotes:
    def _pools(self):
        return {
            "limitup": pd.DataFrame([
                {"code": "A1", "name": "甲", "boards": 3, "industry": "半导体"},
                {"code": "A2", "name": "乙", "boards": 1, "industry": "半导体"},
                {"code": "A3", "name": "丙", "boards": 2, "industry": "电力"},
                {"code": "A4", "name": "丁", "boards": 1, "industry": "电力"},
            ])
        }

    def _themes(self):
        return {
            "A1": ["存储芯片"],
            "A2": ["存储芯片"],
            "A3": ["电力", "人形机器人"],
            "A4": ["电力"],
        }

    def test_attaches_strength_when_quotes_given(self):
        rows = theme_heat(self._pools(), self._themes(), quotes=_quotes())
        by = {r["theme"]: r for r in rows}
        assert by["存储芯片"]["pct"] == 3.21
        assert by["存储芯片"]["board_high"] == "5天5板"
        assert by["存储芯片"]["board_zt"] == 8

    def test_none_when_quotes_absent(self):
        # 不传 quotes(拉取失败降级)→ 强度字段全 None,但聚合照常
        rows = theme_heat(self._pools(), self._themes())
        assert rows
        for r in rows:
            assert r["pct"] is None and r["board_high"] is None and r["board_zt"] is None
            assert r["zt_count"] >= 2  # 聚合逻辑不受影响

    def test_unmatched_theme_gets_none(self):
        rows = theme_heat(self._pools(), self._themes(), quotes={"猪肉": _quotes()["电力"]})
        for r in rows:
            assert r["pct"] is None

    def test_min_count_filters_single_stock_theme(self):
        # 人形机器人只有 A3 一只 → 低于 min_count=2,不计入
        rows = theme_heat(self._pools(), self._themes(), quotes=_quotes())
        assert "人形机器人" not in {r["theme"] for r in rows}

    def test_empty_themes_returns_empty(self):
        assert theme_heat(self._pools(), {}, quotes=_quotes()) == []


class TestSectorHeat:
    def test_industry_aggregation_unaffected(self):
        pools = {
            "limitup": pd.DataFrame([
                {"code": "A1", "name": "甲", "boards": 3, "industry": "半导体"},
                {"code": "A2", "name": "乙", "boards": 1, "industry": "半导体"},
                {"code": "A3", "name": "丙", "boards": 2, "industry": "电力"},
            ])
        }
        rows = sector_heat(pools)
        top = rows[0]
        assert top["sector"] == "半导体"
        assert top["zt_count"] == 2
        assert top["max_board"] == 3

    def test_empty_pools(self):
        assert sector_heat({}) == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
