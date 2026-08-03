"""天梯图数据 metrics.ladder.ladder_board 的测试(纯本地构造,无网络)。

重点锁住「断板票定档」这条:档位 = 昨日板数 + 1,且只收昨日 ≥2 板的。
"""

from __future__ import annotations

import pandas as pd
import pytest

from daban_review.metrics.ladder import ladder_board


def _pools(limitup_rows=None, previous_rows=None):
    return {
        "limitup": pd.DataFrame(limitup_rows or []),
        "previous": pd.DataFrame(previous_rows or []),
    }


def _lim(code, name, boards, first_seal, industry="半导体", pct=10.0, seal=1000.0, mv=100000.0,
         last_seal=None, break_times=0):
    return {"code": code, "name": name, "boards": boards, "first_seal": first_seal,
            "last_seal": last_seal if last_seal is not None else first_seal,
            "industry": industry, "pct": pct, "price": 10.0,
            "seal_amount": seal, "float_mv": mv, "break_times": break_times,
            "turnover": 5.0, "zt_stat": ""}


class TestSealed:
    def test_groups_by_board_desc(self):
        d = ladder_board(_pools([
            _lim("A", "甲", 1, "093000"),
            _lim("B", "乙", 3, "092500"),
        ]))
        assert [r["boards"] for r in d["rows"]] == [3, 1]
        assert d["sealed"] == 2 and d["broken"] == 0

    def test_yizi_flag_at_925(self):
        d = ladder_board(_pools([
            _lim("A", "一字", 1, "092502"),
            _lim("B", "盘中", 1, "093042"),
        ]))
        cells = {c["name"]: c for c in d["rows"][0]["stocks"]}
        assert cells["一字"]["is_yizi"] is True
        assert cells["盘中"]["is_yizi"] is False

    def test_yizi_requires_never_opened(self):
        """一字后炸了又回封 → 不算一字板,应显示回封时间(实测顺钠股份 13:33 就是这种)。"""
        d = ladder_board(_pools([
            _lim("A", "假一字", 4, "092502", last_seal="133300", break_times=1),
        ]))
        c = d["rows"][0]["stocks"][0]
        assert c["is_yizi"] is False
        assert c["last_seal"] == "133300"
        assert c["break_times"] == 1
        assert c["seal_minutes"] == 13 * 60 + 33  # 排序/展示都按最终封板

    def test_seal_minutes_uses_last_seal(self):
        d = ladder_board(_pools([_lim("A", "甲", 1, "093000", last_seal="141500")]))
        assert d["rows"][0]["stocks"][0]["seal_minutes"] == 14 * 60 + 15

    def test_sorted_by_last_seal_within_board(self):
        """档内按「几点才稳住」排序:首封早但回封晚的,排在首封晚却一次封住的后面。"""
        d = ladder_board(_pools([
            _lim("A", "早封晚回封", 1, "093100", last_seal="140000", break_times=2),
            _lim("B", "一次封住", 1, "093500"),
        ]))
        assert [c["name"] for c in d["rows"][0]["stocks"]] == ["一次封住", "早封晚回封"]

    def test_bad_seal_time_does_not_crash(self):
        d = ladder_board(_pools([_lim("A", "怪", 1, "")]))
        c = d["rows"][0]["stocks"][0]
        assert c["seal_minutes"] is None and c["is_yizi"] is False


class TestBroken:
    def test_broken_goes_to_prev_boards_plus_one(self):
        """昨日 5 板今日没封住 → 画在 6 板档并标 broken(实测长缆科技就是这样)。"""
        d = ladder_board(_pools(
            [_lim("A", "爱丽家居", 6, "092502")],
            [{"code": "B", "name": "长缆科技", "prev_boards": 5, "pct": -4.83, "industry": "电网设备"}],
        ))
        row6 = next(r for r in d["rows"] if r["boards"] == 6)
        names = {c["name"]: c for c in row6["stocks"]}
        assert names["长缆科技"]["broken"] is True
        assert names["长缆科技"]["pct"] == -4.83
        assert names["爱丽家居"]["broken"] is False

    def test_prev_first_board_not_drawn(self):
        """昨日首板今日断板每天几十只、无信息量 → 不画,否则 2 板档被淹。"""
        d = ladder_board(_pools(
            [_lim("A", "甲", 1, "093000")],
            [{"code": "Z", "name": "昨日首板断了", "prev_boards": 1, "pct": -3.0, "industry": "X"}],
        ))
        assert d["broken"] == 0
        assert all(c["name"] != "昨日首板断了" for r in d["rows"] for c in r["stocks"])

    def test_sealed_today_not_double_counted(self):
        """今天封住的票也在 previous 里(昨日涨停),不能既算封住又算断板。"""
        d = ladder_board(_pools(
            [_lim("A", "连上去了", 3, "093000")],
            [{"code": "A", "name": "连上去了", "prev_boards": 2, "pct": 10.0, "industry": "X"}],
        ))
        assert d["sealed"] == 1 and d["broken"] == 0
        assert d["total"] == 1

    def test_broken_sorted_after_sealed(self):
        d = ladder_board(_pools(
            [_lim("A", "封住", 3, "140000")],
            [{"code": "B", "name": "断板", "prev_boards": 2, "pct": -2.0, "industry": "X"}],
        ))
        row = next(r for r in d["rows"] if r["boards"] == 3)
        assert [c["name"] for c in row["stocks"]] == ["封住", "断板"]

    def test_positive_pct_broken_kept(self):
        """20cm 票涨 10% 也算断板(没到 20% 涨停),实测五洲医疗 +10.28。"""
        d = ladder_board(_pools(
            [], [{"code": "B", "name": "五洲医疗", "prev_boards": 4, "pct": 10.28, "industry": "医疗器械"}],
        ))
        assert d["rows"][0]["boards"] == 5
        assert d["rows"][0]["stocks"][0]["pct"] == 10.28


class TestIndustries:
    def test_small_industries_merged_into_other(self):
        rows = [_lim(f"C{i}", f"票{i}", 1, "093000", industry="软件开发") for i in range(4)]
        rows += [_lim("X1", "冷1", 1, "093000", industry="冷门A"),
                 _lim("X2", "冷2", 1, "093000", industry="冷门B")]
        d = ladder_board(_pools(rows), industry_min=3)
        names = {i["name"]: i["count"] for i in d["industries"]}
        assert names["软件开发"] == 4
        assert names["其他"] == 2  # 两个各 1 只的冷门行业并入其他

    def test_industry_total_matches_stock_total(self):
        rows = [_lim(f"C{i}", f"票{i}", 1, "093000", industry="半导体") for i in range(3)]
        d = ladder_board(_pools(
            rows, [{"code": "B", "name": "断", "prev_boards": 2, "pct": -1.0, "industry": "电力"}],
        ))
        assert sum(i["count"] for i in d["industries"]) == d["total"] == 4  # 断板票也计入行业分布


class TestEmpty:
    def test_empty_pools(self):
        d = ladder_board({})
        assert d == {"rows": [], "industries": [], "total": 0, "sealed": 0, "broken": 0, "max_board": 0}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
