"""回测聚合/相关性纯函数单测(不依赖 DB 与网络)。"""

from __future__ import annotations

import math

import pytest

from daban_review.metrics.backtest import agg, format_report, pearson, spearman, summarize


def _rows():
    # 构造评级与溢价单调正相关的样本
    return [
        {"grade": "A+", "score": 7, "phase": "修复", "boards": 2, "prem": 0.09, "date": "20260721"},
        {"grade": "A", "score": 3, "phase": "修复", "boards": 1, "prem": 0.03, "date": "20260721"},
        {"grade": "B", "score": 1, "phase": "分歧", "boards": 1, "prem": 0.005, "date": "20260722"},
        {"grade": "D", "score": -3, "phase": "分歧", "boards": 5, "prem": -0.02, "date": "20260722"},
    ]


class TestAgg:
    def test_basic(self):
        a = agg([{"prem": 0.1}, {"prem": -0.05}, {"prem": 0.2}])
        assert a["n"] == 3
        assert a["win"] == round(2 / 3, 4)
        assert a["avg"] == round((0.1 - 0.05 + 0.2) / 3, 4)
        assert a["med"] == 0.1  # 排序后中位

    def test_empty(self):
        assert agg([]) is None


class TestCorr:
    def test_pearson_perfect_positive(self):
        assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)

    def test_pearson_perfect_negative(self):
        assert pearson([1, 2, 3], [6, 4, 2]) == pytest.approx(-1.0)

    def test_pearson_too_few_points_is_nan(self):
        assert math.isnan(pearson([1], [2]))

    def test_pearson_zero_variance_is_nan(self):
        assert math.isnan(pearson([1, 1, 1], [1, 2, 3]))

    def test_spearman_monotonic_but_nonlinear(self):
        # 单调非线性 → Spearman = 1
        assert spearman([1, 2, 3, 4], [1, 4, 9, 16]) == pytest.approx(1.0)


class TestSummarize:
    def test_groups_and_corr(self):
        s = summarize(_rows())
        assert s["n"] == 4
        assert set(s["by_grade"]) == {"A+", "A", "B", "D"}
        assert s["by_grade"]["A+"]["n"] == 1
        assert set(s["by_phase"]) == {"修复", "分歧"}
        assert s["by_phase"]["修复"]["n"] == 2
        # score 与 prem 正相关
        assert s["pearson"] > 0.9


class TestFormatReport:
    def test_empty_rows_message(self):
        out = format_report([])
        assert "无可回测样本" in out

    def test_report_contains_sections(self):
        out = format_report(_rows())
        assert "评分回测" in out
        assert "按评级" in out
        assert "Pearson" in out
        assert "A+" in out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
