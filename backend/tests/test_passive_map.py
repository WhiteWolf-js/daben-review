"""ladder.passive_map(被动上板度)的测试。纯计算,无网络。

它量化的是复盘录音里那句「尾盘被板块反推上板,属于悟道板」/「缺乏主动性」——
区分**它带动板块**还是**板块推它上板**。

三处口径必须与回测一致(改了分数就与验证脱钩),这里逐条锁住:
1. hot_themes 用全部 ≥2 只的题材(不是面板 top12)
2. 多题材时取 hot_themes 里**靠前**的(= 当日涨停家数最多那个)
3. 排序用**最终封板** last_seal(缺失退回 first_seal)
"""

from __future__ import annotations

from daban_review.metrics.ladder import PASSIVE_MIN_PEERS, passive_map


def _p(code, last=None, first="093000"):
    return {"code": code, "name": code, "first_seal": first,
            "last_seal": last if last is not None else first}


class TestOrder:
    def test_relative_sequence_0_to_1(self):
        """三只同题材:最早封=0、中间=0.5、最晚=1。"""
        profs = [_p("A", "093000"), _p("B", "103000"), _p("C", "143000")]
        m = passive_map(profs, {c: ["算力"] for c in "ABC"}, ["算力"])
        assert (m["A"], m["B"], m["C"]) == (0.0, 0.5, 1.0)

    def test_sorted_by_last_seal_not_first(self):
        """A 首封更早但拖到尾盘才稳住,B 首封晚却很快稳住 → B 才是领头。"""
        profs = [_p("A", first="092500", last="143000"),
                 _p("B", first="103000", last="103000"),
                 _p("C", first="110000", last="113000")]
        m = passive_map(profs, {c: ["算力"] for c in "ABC"}, ["算力"])
        assert m["B"] == 0.0 and m["A"] == 1.0

    def test_missing_last_falls_back_to_first(self):
        profs = [_p("A", last="", first="092500"), _p("B", "103000"), _p("C", "143000")]
        m = passive_map(profs, {c: ["算力"] for c in "ABC"}, ["算力"])
        assert m["A"] == 0.0

    def test_unparsable_time_sinks_to_last(self):
        profs = [_p("A", "093000"), _p("B", "103000"), _p("C", "乱码")]
        m = passive_map(profs, {c: ["算力"] for c in "ABC"}, ["算力"])
        assert m["C"] == 1.0


class TestMinPeers:
    def test_below_min_peers_no_value(self):
        """同题材不足 3 只,封板次序没有意义 → 一个都不给值。"""
        profs = [_p("A", "093000"), _p("B", "143000")]
        assert passive_map(profs, {c: ["算力"] for c in "AB"}, ["算力"]) == {}

    def test_exactly_min_peers_ok(self):
        profs = [_p(c, f"1{i}3000") for i, c in enumerate("ABC")]
        m = passive_map(profs, {c: ["算力"] for c in "ABC"}, ["算力"])
        assert len(m) == PASSIVE_MIN_PEERS

    def test_min_peers_counted_per_picked_theme(self):
        """分组按**各自选中的**题材算,不是题材总家数 —— A/B/C 选算力(3只,可判)、
        D/E 选机器人(2只,不可判)。"""
        profs = [_p(c, f"1{i}3000") for i, c in enumerate("ABCDE")]
        themes = {**{c: ["算力"] for c in "ABC"}, **{c: ["机器人"] for c in "DE"}}
        m = passive_map(profs, themes, ["算力", "机器人"])
        assert set(m) == set("ABC")


class TestThemePick:
    def test_picks_theme_earlier_in_hot_list(self):
        """多题材时取 hot_themes 里靠前的(传入顺序=当日家数降序)。
        A 同属「算力」和「机器人」,算力靠前 → 归到算力组。"""
        profs = [_p("A", "093000"), _p("B", "103000"), _p("C", "143000"),
                 _p("D", "093000"), _p("E", "103000"), _p("F", "143000")]
        themes = {"A": ["机器人", "算力"], "B": ["算力"], "C": ["算力"],
                  "D": ["机器人"], "E": ["机器人"], "F": ["机器人"]}
        m = passive_map(profs, themes, ["算力", "机器人"])
        assert m["A"] == 0.0  # 算力组里 A 最早(A/B/C)
        # 若错归到机器人组(A/D/E/F 四只),A 会与 D 并列最早、值不是 0.0 就是别的
        assert m["D"] == 0.0 and m["F"] == 1.0

    def test_theme_not_in_hot_list_is_ignored(self):
        """题材不在 hot_themes(即当日不足 2 只、不成板块)→ 该票没有被动度。"""
        profs = [_p("A", "093000"), _p("B", "103000"), _p("C", "143000")]
        themes = {"A": ["某独家概念"], "B": ["算力"], "C": ["算力"]}
        m = passive_map(profs, themes, ["算力"])
        assert "A" not in m          # 题材未成板块
        assert m == {}               # 剩下 B/C 只有 2 只,也不够 min_peers


class TestDegrade:
    def test_no_themes(self):
        assert passive_map([_p("A"), _p("B"), _p("C")], {}, ["算力"]) == {}

    def test_no_hot_themes(self):
        profs = [_p(c) for c in "ABC"]
        assert passive_map(profs, {c: ["算力"] for c in "ABC"}, []) == {}

    def test_none_inputs(self):
        assert passive_map([_p("A")], None, None) == {}

    def test_empty_profiles(self):
        assert passive_map([], {"A": ["算力"]}, ["算力"]) == {}
