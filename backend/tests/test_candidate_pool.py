"""四风格候选池 daban_review.metrics.candidate_pool 的单测(纯计算,无网络)。

重点验证「复现性」:同样输入必得同样池与同样 rank —— 这是把候选选择从 agent 手里收回代码层的目的。
"""

from __future__ import annotations

import pandas as pd
import pytest

from daban_review.metrics.candidate_pool import STYLES, build_candidate_pool, pool_codes


def _row(code, name, boards, seal_amount=3e8, float_mv=1e10, first_seal="093000",
         break_times=0, turnover=4.0, price=10.0, industry="电子"):
    return {
        "code": code, "name": name, "boards": boards, "pct": 10.0, "price": price,
        "amount": 5e8, "float_mv": float_mv, "total_mv": float_mv, "turnover": turnover,
        "seal_amount": seal_amount, "first_seal": first_seal, "last_seal": "093000",
        "break_times": break_times, "zt_stat": f"1/{boards}", "industry": industry,
    }


@pytest.fixture
def pools():
    # 3板两只(封流比不同)、1板两只(一只有题材一只无)、5板一只
    return {"limitup": pd.DataFrame([
        _row("000001", "三板强", 3, seal_amount=4e8),          # 封流比 4%
        _row("000002", "三板弱", 3, seal_amount=5e7),          # 封流比 0.5%
        _row("000003", "首板有题材", 1, seal_amount=3e8),
        _row("000004", "首板无题材", 1, seal_amount=3.5e8),
        _row("000005", "五板高位", 5, seal_amount=3e8),
    ])}


@pytest.fixture
def emotion():
    return {"phase_hint": "发酵"}


@pytest.fixture
def themes():
    return {"000001": ["存储芯片"], "000003": ["存储芯片"], "000005": ["人形机器人"]}


@pytest.fixture
def theme_rank():
    return [{"theme": "存储芯片", "zt_count": 2}, {"theme": "人形机器人", "zt_count": 1}]


class TestBuildPool:
    def test_styles_all_present(self, pools, emotion, themes, theme_rank):
        res = build_candidate_pool(pools, emotion, themes, theme_rank)
        assert set(res["pool"].keys()) == set(STYLES)

    def test_low_board_style_only_2_to_3(self, pools, emotion, themes, theme_rank):
        items = build_candidate_pool(pools, emotion, themes, theme_rank)["pool"]["低位连板接力"]
        assert {i["code"] for i in items} == {"000001", "000002"}
        assert all(2 <= i["boards"] <= 3 for i in items)

    def test_first_board_requires_theme(self, pools, emotion, themes, theme_rank):
        """首板无题材=没有打板逻辑,不进池。"""
        items = build_candidate_pool(pools, emotion, themes, theme_rank)["pool"]["首板打板"]
        assert [i["code"] for i in items] == ["000003"]

    def test_high_board_style(self, pools, emotion, themes, theme_rank):
        items = build_candidate_pool(pools, emotion, themes, theme_rank)["pool"]["高位龙头接力"]
        assert [i["code"] for i in items] == ["000005"]

    def test_theme_leader_is_highest_board_in_theme(self, pools, emotion, themes, theme_rank):
        """存储芯片里 3板(000001)身位高于 1板(000003) → 龙头取 000001。"""
        items = build_candidate_pool(pools, emotion, themes, theme_rank)["pool"]["题材情绪龙头"]
        codes = [i["code"] for i in items]
        assert "000001" in codes and "000003" not in codes

    def test_rank_by_score_desc(self, pools, emotion, themes, theme_rank):
        """强封 3板 应排在弱封 3板 之前,rank 从 1 连续编号。"""
        items = build_candidate_pool(pools, emotion, themes, theme_rank)["pool"]["低位连板接力"]
        assert [i["code"] for i in items] == ["000001", "000002"]
        assert [i["rank"] for i in items] == [1, 2]
        assert items[0]["score"] > items[1]["score"]

    def test_carries_price_and_grade(self, pools, emotion, themes, theme_rank):
        """price(触发价算式用)与 grade/position 必须带上,prompt 依赖这几个字段。"""
        top = build_candidate_pool(pools, emotion, themes, theme_rank)["pool"]["低位连板接力"][0]
        for k in ("price", "grade", "position", "score", "reasons", "theme"):
            assert k in top
        assert top["price"] == 10.0

    def test_theme_leader_deduped_by_code(self, emotion):
        """一只票同时是两个热门题材的龙头时只占一个 rank(否则挤没池的可选面)。"""
        p = {"limitup": pd.DataFrame([_row("000001", "双题材龙头", 3), _row("000009", "另一票", 2)])}
        themes = {"000001": ["存储芯片", "液冷"], "000009": ["存储芯片"]}
        rank = [
            {"theme": "存储芯片", "zt_count": 2, "lianban_count": 2, "max_board": 3},
            {"theme": "液冷", "zt_count": 1, "lianban_count": 1, "max_board": 3},
        ]
        items = build_candidate_pool(p, emotion, themes, rank)["pool"]["题材情绪龙头"]
        codes = [i["code"] for i in items]
        assert codes.count("000001") == 1

    def test_theme_leader_mainline_first_not_score_first(self, emotion):
        """龙头=最强主线的领涨:有连板高度的主线优先于「涨停多但零连板」的泛标签,即便后者封流比更高。

        对应真实场景:「中报预增」涨停家数最多却无连板,不该把首板泛标签票顶成题材龙头。
        """
        p = {"limitup": pd.DataFrame([
            _row("000001", "主线连板", 3, seal_amount=1e8),      # 封流比 1%,主线(有连板)
            _row("000002", "泛标签首板", 1, seal_amount=5e8),    # 封流比 5%,score 更高
        ])}
        themes = {"000001": ["军工"], "000002": ["中报预增"]}
        rank = [  # theme_heat 原始顺序按 zt_count:泛标签在前
            {"theme": "中报预增", "zt_count": 9, "lianban_count": 0, "max_board": 1},
            {"theme": "军工", "zt_count": 3, "lianban_count": 2, "max_board": 3},
        ]
        items = build_candidate_pool(p, emotion, themes, rank)["pool"]["题材情绪龙头"]
        assert items[0]["code"] == "000001"
        assert items[0]["lead_theme"] == "军工"

    def test_illiquid_lock_sinks_to_pool_tail(self, emotion):
        """换手<1% 且无题材的一字独苗排到池尾(客观上没有可打的承接位),即便 score 更高。

        对应真实场景:爱丽家居 5板、换手0.2%、无热门题材 —— 次日要么一字买不到要么直接砸。
        原先靠 agent 每次临场判断要不要跳过它,同日复跑就会换人。
        """
        p = {"limitup": pd.DataFrame([
            _row("000001", "一字独苗", 5, seal_amount=5e8, turnover=0.2, first_seal="092500"),
            _row("000002", "有量高位", 5, seal_amount=2e8, turnover=20.0),
        ])}
        items = build_candidate_pool(p, emotion, {"000002": ["军工"]}, [
            {"theme": "军工", "zt_count": 3, "lianban_count": 2, "max_board": 5},
        ])["pool"]["高位龙头接力"]
        assert [i["code"] for i in items] == ["000002", "000001"]

    def test_illiquid_but_has_theme_not_penalized(self, emotion):
        """低换手但有热门题材归属的票不算「打不了」——有方向联动就有接力逻辑。"""
        p = {"limitup": pd.DataFrame([
            _row("000001", "缩量有题材", 5, seal_amount=5e8, turnover=0.5),
            _row("000002", "有量无题材", 5, seal_amount=1e8, turnover=20.0),
        ])}
        rank = [{"theme": "军工", "zt_count": 3, "lianban_count": 2, "max_board": 5}]
        items = build_candidate_pool(p, emotion, {"000001": ["军工"]}, rank)["pool"]["高位龙头接力"]
        assert items[0]["code"] == "000001"

    def test_deterministic_across_runs(self, pools, emotion, themes, theme_rank):
        """同输入两次构建结果完全一致(复现性的根本要求)。"""
        a = build_candidate_pool(pools, emotion, themes, theme_rank)
        b = build_candidate_pool(pools, emotion, themes, theme_rank)
        assert a == b

    def test_top_limit(self, emotion):
        many = {"limitup": pd.DataFrame([
            _row(f"00000{i}" if i < 10 else f"0000{i}", f"票{i}", 3, seal_amount=1e8 * i)
            for i in range(1, 9)
        ])}
        items = build_candidate_pool(many, emotion, {}, [], top=5)["pool"]["低位连板接力"]
        assert len(items) == 5

    def test_empty_limitup(self, emotion):
        res = build_candidate_pool({"limitup": pd.DataFrame()}, emotion, {}, [])
        assert res["pool"] == {s: [] for s in STYLES}

    def test_no_themes_still_gives_board_styles(self, pools, emotion):
        """题材拉取失败(themes 空)时,连板类风格仍可用,题材/首板池为空。"""
        res = build_candidate_pool(pools, emotion, {}, [])["pool"]
        assert res["低位连板接力"] and res["高位龙头接力"]
        assert res["首板打板"] == [] and res["题材情绪龙头"] == []


class TestProfileTargets:
    """二段画像的 4 个固定席位:原先由 agent 自选,同日复跑三次三批人 → 收进规则层。"""

    SEAT_ORDER = ["市场高度", "卡位板", "主线龙头", "次高身位"]

    def test_seats_follow_priority_order(self, pools, emotion, themes, theme_rank):
        """席位按优先序出现;某席位的票已被前面席位占用时(此 fixture 里主线龙头=卡位板同一只)
        该席跳过、由后面的席位顺延填满,不会重复占位。"""
        got = build_candidate_pool(pools, emotion, themes, theme_rank)["profile_targets"]
        seats = [p["seat"] for p in got]
        assert seats == [s for s in self.SEAT_ORDER if s in seats]
        # 该 fixture 只有 3 只连板票(补位只从连板池取,二段是「连板票画像」),故给到 3 只
        assert len(got) == 3
        assert len({p["code"] for p in got}) == 3

    def test_all_four_seats_when_distinct(self, emotion):
        """四个席位分属不同票时,四席齐全且顺序固定。"""
        p = {"limitup": pd.DataFrame([
            _row("000001", "高位龙头", 5, seal_amount=2e8, turnover=20.0),
            _row("000002", "低位强封", 3, seal_amount=4e8),
            _row("000003", "主线龙头", 4, seal_amount=1e8, turnover=20.0),
            _row("000004", "次高身位", 2, seal_amount=3e8),
        ])}
        # 主线题材归属给 000003(4板),让它拿「主线龙头」席而不是高位 rank1
        rank = [{"theme": "军工", "zt_count": 3, "lianban_count": 2, "max_board": 4}]
        got = build_candidate_pool(p, emotion, {"000003": ["军工"]}, rank)["profile_targets"]
        assert [x["seat"] for x in got] == self.SEAT_ORDER
        assert len({x["code"] for x in got}) == 4

    def test_seat_sources_match_pools(self, pools, emotion, themes, theme_rank):
        res = build_candidate_pool(pools, emotion, themes, theme_rank)
        pool, targets = res["pool"], {p["seat"]: p["code"] for p in res["profile_targets"]}
        assert targets["市场高度"] == pool["高位龙头接力"][0]["code"]
        assert targets["卡位板"] == pool["低位连板接力"][0]["code"]

    def test_deduped_across_seats(self, emotion):
        """同一只票既是高位 rank1 又是主线龙头时不重复占席,后面的席位顺延。"""
        p = {"limitup": pd.DataFrame([
            _row("000001", "双席位票", 5, seal_amount=4e8),
            _row("000002", "二板", 2, seal_amount=2e8),
            _row("000003", "另一二板", 2, seal_amount=1e8),
        ])}
        rank = [{"theme": "军工", "zt_count": 3, "lianban_count": 2, "max_board": 5}]
        got = build_candidate_pool(p, emotion, {"000001": ["军工"]}, rank)["profile_targets"]
        codes = [t["code"] for t in got]
        assert len(codes) == len(set(codes))

    def test_at_most_four_and_no_padding_when_scarce(self, emotion):
        p = {"limitup": pd.DataFrame([_row("000001", "唯一二板", 2)])}
        got = build_candidate_pool(p, emotion, {}, [])["profile_targets"]
        assert len(got) == 1 and got[0]["code"] == "000001"

    def test_deterministic(self, pools, emotion, themes, theme_rank):
        a = build_candidate_pool(pools, emotion, themes, theme_rank)["profile_targets"]
        b = build_candidate_pool(pools, emotion, themes, theme_rank)["profile_targets"]
        assert a == b


class TestMainlines:
    def test_theme_top_carries_counts_and_lead(self, pools, emotion, themes, theme_rank):
        """一段方向直接照抄 theme_top,故家数/高度/龙头必须齐(否则 agent 又要自己去凑)。"""
        top = build_candidate_pool(pools, emotion, themes, theme_rank)["theme_top"]
        assert top and top[0]["rank"] == 1
        for k in ("theme", "zt_count", "lianban_count", "max_board", "lead"):
            assert k in top[0]
        assert top[0]["lead"] is None or "boards" in top[0]["lead"]


class TestPoolCodes:
    def test_maps_style_to_code_set(self, pools, emotion, themes, theme_rank):
        codes = pool_codes(build_candidate_pool(pools, emotion, themes, theme_rank))
        assert codes["低位连板接力"] == {"000001", "000002"}
        assert codes["首板打板"] == {"000003"}

    def test_empty_payload(self):
        assert pool_codes({}) == {}
