"""天梯图数据 metrics.ladder.ladder_board 的测试(纯本地构造,无网络)。

重点锁住「断板票定档」这条:档位 = 昨日板数 + 1,且只收昨日 ≥2 板的。
"""

from __future__ import annotations

import pandas as pd
import pytest

from daban_review.metrics.ladder import ladder_board


def _pools(limitup_rows=None, previous_rows=None, zbgc_rows=None):
    return {
        "limitup": pd.DataFrame(limitup_rows or []),
        "previous": pd.DataFrame(previous_rows or []),
        "zbgc": pd.DataFrame(zbgc_rows or []),
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
        """20cm 票涨 10% 也算断板(没到 20% 涨停),实测五洲医疗 +10.28。

        代码必须用真实的创业板段 —— 涨停兜底判据按代码段取涨跌幅限制。
        """
        d = ladder_board(_pools(
            [], [{"code": "301234", "name": "五洲医疗", "prev_boards": 4, "pct": 10.28,
                  "industry": "医疗器械"}],
        ))
        assert d["rows"][0]["boards"] == 5
        assert d["rows"][0]["stocks"][0]["broken"] is True
        assert d["rows"][0]["stocks"][0]["pct"] == 10.28


class TestReseal:
    """涨停池漏收「反复炸板尾盘回封」的票 → 不能判成断板(实测 002827 高争民爆)。"""

    def test_closed_at_limit_not_broken(self):
        """收盘涨幅到涨停(+10.01) → 改判回封,并从炸板池补炸板次数。"""
        d = ladder_board(_pools(
            [],
            [{"code": "002827", "name": "高争民爆", "prev_boards": 4, "pct": 10.01,
              "industry": "化学制品"}],
            [{"code": "002827", "name": "高争民爆", "first_seal": "092500", "break_times": 26}],
        ))
        c = d["rows"][0]["stocks"][0]
        assert d["rows"][0]["boards"] == 5  # 昨日 4 板 + 今日涨停 = 5 板
        assert c["broken"] is False and c["reseal"] is True
        assert c["break_times"] == 26
        assert d["sealed"] == 1 and d["broken"] == 0

    def test_reseal_has_no_fake_seal_time(self):
        """回封时刻拿不到就留空 —— 拿首封(09:25)顶替会把烂板显示成超早封一字。"""
        d = ladder_board(_pools(
            [],
            [{"code": "002827", "name": "高争民爆", "prev_boards": 4, "pct": 10.01, "industry": "化学制品"}],
            [{"code": "002827", "name": "高争民爆", "first_seal": "092500", "break_times": 26}],
        ))
        c = d["rows"][0]["stocks"][0]
        assert c["first_seal"] == "" and c["last_seal"] == ""
        assert c["seal_minutes"] is None
        assert c["is_yizi"] is False
        assert c["seal_strength"] == 0.0  # 炸板池没有封单数据,别假装有

    def test_reseal_without_zbgc_row(self):
        """炸板池也没收录时仍按涨停算,炸板次数退 0(宁可少标,不要判成断板)。"""
        d = ladder_board(_pools(
            [], [{"code": "600123", "name": "某主板", "prev_boards": 2, "pct": 9.98, "industry": "煤炭"}],
        ))
        c = d["rows"][0]["stocks"][0]
        assert c["reseal"] is True and c["break_times"] == 0

    def test_20cm_at_10pct_still_broken(self):
        """创业板 +10.01 离 20% 涨停远得很 → 必须还是断板,不能被兜底判据捞上来。"""
        d = ladder_board(_pools(
            [], [{"code": "300123", "name": "某创业板", "prev_boards": 3, "pct": 10.01, "industry": "软件开发"}],
        ))
        assert d["rows"][0]["stocks"][0]["broken"] is True

    def test_20cm_at_limit_is_reseal(self):
        d = ladder_board(_pools(
            [], [{"code": "688123", "name": "某科创板", "prev_boards": 3, "pct": 19.97, "industry": "半导体"}],
        ))
        assert d["rows"][0]["stocks"][0]["reseal"] is True

    def test_mainboard_st_limit_is_10pct(self):
        """主板 ST 涨停自 2026-07-06 起是 10%(旧规 5%)→ 戴帽不再单独判。"""
        d = ladder_board(_pools(
            [], [{"code": "600321", "name": "ST某某", "prev_boards": 2, "pct": 10.02, "industry": "房地产"}],
        ))
        assert d["rows"][0]["stocks"][0]["reseal"] is True

    def test_mainboard_st_at_old_5pct_is_broken(self):
        """新规下 +5% 对主板 ST 已经不是涨停,必须还判断板。"""
        d = ladder_board(_pools(
            [], [{"code": "600321", "name": "*ST某某", "prev_boards": 2, "pct": 5.02, "industry": "房地产"}],
        ))
        assert d["rows"][0]["stocks"][0]["broken"] is True

    def test_gem_st_still_20pct(self):
        """创业板 ST 仍是 20%:+10.01 不算涨停。"""
        d = ladder_board(_pools(
            [], [{"code": "300456", "name": "ST某创", "prev_boards": 2, "pct": 10.01, "industry": "软件开发"}],
        ))
        assert d["rows"][0]["stocks"][0]["broken"] is True

    def test_bj_limit_is_30pct(self):
        d = ladder_board(_pools(
            [], [{"code": "830123", "name": "某北交所", "prev_boards": 2, "pct": 29.94, "industry": "通用设备"}],
        ))
        assert d["rows"][0]["stocks"][0]["reseal"] is True

    def test_reseal_sorted_after_clean_seal(self):
        """封板时刻未知(seal_minutes=None)→ 排在同档正常封住的票后面。"""
        d = ladder_board(_pools(
            [_lim("600001", "一次封住", 5, "093000")],
            [{"code": "002827", "name": "高争民爆", "prev_boards": 4, "pct": 10.01, "industry": "化学制品"}],
            [{"code": "002827", "name": "高争民爆", "first_seal": "092500", "break_times": 26}],
        ))
        row = next(r for r in d["rows"] if r["boards"] == 5)
        assert [c["name"] for c in row["stocks"]] == ["一次封住", "高争民爆"]


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


class TestSector:
    """格子里的「所属板块」:用当天真形成板块效应的题材,不用行业。

    行业是申万静态分类,跟今天为什么涨停无关而且会误导 —— 实测美利云行业恒为
    `IT服务Ⅱ` 但连板靠 `算力租赁`、胜通能源 `燃气Ⅱ` 实际是 `机器人`。
    """

    def _one(self, **kw):
        d = ladder_board(_pools([_lim("A", "甲", 2, "093000", industry="IT服务Ⅱ")]), **kw)
        return d["rows"][0]["stocks"][0]

    def test_hot_theme_wins(self):
        """热度第一的题材胜出,再宽化成方向名(算力租赁 → 算力)。"""
        s = self._one(themes={"A": ["东数西算", "算力租赁"]}, hot_themes=["算力租赁", "东数西算"])
        assert (s["sector"], s["sector_hot"]) == ("算力", True)

    def test_picks_best_ranked_among_hot(self):
        """多个题材都成板块时取热度最好的那个(hot_themes 已按热度排好序)。

        同时锁死:hot[0]「东数西算」不在 `_BROAD_ROOTS` 里宽化不了,也**不许**顺着
        往下拿能宽化的 hot[1]「算力租赁」→「算力」。根词表人工维护必然不全,
        那样写会让没收录的真热门方向被次热题材系统性顶掉。
        """
        s = self._one(themes={"A": ["东数西算", "算力租赁"]}, hot_themes=["东数西算", "算力租赁"])
        assert s["sector"] == "东数西算"

    def test_fragment_theme_marked_not_hot(self):
        """只此一只的碎片标签仍比行业有信息量,但要标成非真板块(前端暗一档)。"""
        s = self._one(themes={"A": ["宁德时代供应商"]}, hot_themes=["算力租赁"])
        assert (s["sector"], s["sector_hot"]) == ("宁德时代供应商", False)

    def test_falls_back_to_industry_without_roman_suffix(self):
        s = self._one(themes={}, hot_themes=[])
        assert (s["sector"], s["sector_hot"]) == ("IT服务", False)  # 去掉 Ⅱ

    def test_industry_kept_alongside(self):
        """原 industry 字段不动 —— 行业分布与 tooltip 还要用。"""
        s = self._one(themes={"A": ["算力租赁"]}, hot_themes=["算力租赁"])
        assert s["industry"] == "IT服务Ⅱ"

    def test_broken_stock_uses_yesterday_theme(self):
        """断板票今天没涨停 → 没有今日涨停原因,用昨日的补(它昨天靠什么涨的)。"""
        d = ladder_board(
            _pools([], [{"code": "B", "name": "断", "prev_boards": 3, "pct": -4.8, "industry": "电网设备"}]),
            themes={},
            prev_themes={"B": ["可控核聚变"]},
            hot_themes=["可控核聚变"],
        )
        s = d["rows"][0]["stocks"][0]
        assert s["broken"] is True
        assert (s["sector"], s["sector_hot"]) == ("可控核聚变", True)

    def test_today_theme_beats_yesterday(self):
        s = self._one(themes={"A": ["今日题材"]}, prev_themes={"A": ["昨日题材"]}, hot_themes=["昨日题材"])
        assert s["sector"] == "今日题材"  # 有今日的就不看昨日

    def test_no_themes_passed_degrades_to_industry(self):
        """不传题材参数时退化成老行为(别的调用方不受影响)。"""
        s = self._one()
        assert s["sector"] == "IT服务" and s["sector_hot"] is False


class TestEmpty:
    def test_empty_pools(self):
        d = ladder_board({})
        assert d == {"rows": [], "industries": [], "total": 0, "sealed": 0, "broken": 0, "max_board": 0}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
