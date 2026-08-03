"""盘中切换 metrics.intraday_rotation 的测试(纯本地构造,分时走打桩,无网络)。

重点锁住三条踩过的坑:
- 口径必须含炸板池(少了它就是生存者偏差,曲线全收在涨停)
- prev_close 用「末根 close / (1+pct/100)」反推,不额外请求
- 昨日涨停池(previous)不进封板时序(它的封板时间是昨天的)
"""

from __future__ import annotations

import pandas as pd
import pytest

from daban_review.metrics.intraday_rotation import (
    BUCKETS,
    INDUSTRY_GROUP,
    build_rotation,
    group_of,
)


def _lim(code, name, industry, pct=10.0, boards=1, first_seal="093000",
         last_seal=None, break_times=0):
    return {"code": code, "name": name, "industry": industry, "pct": pct, "price": 11.0,
            "boards": boards, "first_seal": first_seal,
            "last_seal": last_seal if last_seal is not None else first_seal,
            "break_times": break_times, "zt_stat": "1/1"}


def _zb(code, name, industry, pct=-2.0, first_seal="092500", break_times=1):
    """炸板池:注意**没有 boards / last_seal / price 列** —— 真实表就是这样,别在测试里补齐。"""
    return {"code": code, "name": name, "industry": industry, "pct": pct,
            "first_seal": first_seal, "break_times": break_times, "zt_stat": "0/0"}


def _prev(code, name, industry, pct=3.0, prev_boards=2, prev_seal="100000"):
    """昨日涨停池:字段是 prev_boards / prev_seal,今日板数与封板时间都没有。"""
    return {"code": code, "name": name, "industry": industry, "pct": pct,
            "prev_boards": prev_boards, "prev_seal": prev_seal, "turnover": 5.0, "zt_stat": "2/1"}


def _pools(limitup=None, zbgc=None, previous=None):
    return {
        "limitup": pd.DataFrame(limitup or []),
        "zbgc": pd.DataFrame(zbgc or []),
        "previous": pd.DataFrame(previous or []),
    }


def _bars(shape: list[float], last_close: float = 11.0) -> pd.DataFrame:
    """造 240 根分钟线。shape 给 17 个桶点的**相对昨收涨幅%**,线性铺满整天。

    ⚠️ 被测代码是拿池子行的 `pct` 反推昨收的,所以**池子行的 pct 必须等于 shape[-1]**,
    否则桩的绝对水平和断言就对不上(踩过:pct 写死 10.0 而曲线收在 -2%,形态判成了平推)。
    走 `_stub()` 构造就不会写错。
    """
    times, closes = [], []
    prev = last_close / (1 + shape[-1] / 100)
    mins = _minutes()
    for i, hhmm in enumerate(mins):
        bi = min(int(i / len(mins) * len(shape)), len(shape) - 1)  # 分钟落到对应桶
        times.append(hhmm)
        closes.append(prev * (1 + shape[bi] / 100))
    closes[-1] = last_close
    return pd.DataFrame({"time": times, "close": closes})


def _stub(specs: list[tuple[str, str, str, list[float]]]):
    """(code, name, industry, curve) → (涨停池行列表, fetch 桩)。pct 自动取 curve[-1],保证一致。"""
    rows = [_lim(code, name, ind, pct=curve[-1]) for code, name, ind, curve in specs]
    curves = {code: curve for code, _, _, curve in specs}
    return rows, _fetch(curves)


def _minutes() -> list[str]:
    out = []
    for h, m0, m1 in ((9, 31, 60), (10, 0, 60), (11, 0, 31), (13, 1, 60), (14, 0, 61)):
        for m in range(m0, m1):
            out.append(f"{h:02d}:{m % 60:02d}" if m < 60 else "15:00")
    return out[:240]


def _fetch(curves: dict[str, list[float]], last: dict[str, float] | None = None):
    """按 code 返回打桩分时;没配的 code 返回空表(模拟取不到)。"""
    def f(code, date):
        if code not in curves:
            return pd.DataFrame()
        return _bars(curves[code], (last or {}).get(code, 11.0))
    return f


# 早盘冲高回落 / 盘中接棒 的桶点(17 个)
FADE = [9.0, 10.0, 10.0, 8.0, 7.0, 6.5, 6.0, 5.5, 5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0]
TAKE = [1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.5, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
FLAT = [3.0] * 17


class TestGroupMap:
    def test_covers_truncated_names(self):
        """行业名在源头是截断的,映射必须按原样收录,不能靠前缀猜。"""
        assert group_of("IT服务Ⅱ") == "科技应用"
        assert group_of("计算机设") == "科技硬件"
        assert group_of("自动化设") == "高端制造"
        assert group_of("酒店餐饮") == "消费"
        assert group_of("中药Ⅱ") == "医药"
        assert group_of("电网设备") == "电力产业"

    def test_unknown_falls_to_other(self):
        assert group_of("某个新行业") == "其他"
        assert group_of("") == "其他"
        assert group_of(None) == "其他"

    def test_no_duplicate_industry_across_groups(self):
        """同一个行业不能落进两个大类(字典本身保证,这条防手改时写重)。"""
        assert len(INDUSTRY_GROUP) == len(set(INDUSTRY_GROUP))


class TestUniverse:
    def test_includes_broken_pool(self):
        """炸板池必须进口径 —— 少了它就是生存者偏差,看不到「跌下来」那一半。"""
        r = build_rotation(
            _pools(limitup=[_lim("A", "甲", "半导体")], zbgc=[_zb("B", "乙", "半导体")]),
            "20260731",
            fetch_min=_fetch({"A": FLAT, "B": FADE}),
        )
        assert r["universe"] == 2 and r["fetched"] == 2

    def test_previous_pool_without_boards_columns(self):
        """昨日涨停池没有 boards/last_seal/break_times 列,不能因 NaN 抛异常。"""
        r = build_rotation(
            _pools(previous=[_prev("A", "甲", "半导体")]),
            "20260731",
            fetch_min=_fetch({"A": FLAT}),
        )
        assert r["universe"] == 1

    def test_dedup_prefers_limitup(self):
        r = build_rotation(
            _pools(limitup=[_lim("A", "甲", "半导体", pct=10.0)],
                   zbgc=[_zb("A", "甲", "半导体", pct=-2.0)]),
            "20260731",
            fetch_min=_fetch({"A": FLAT}),
        )
        assert r["universe"] == 1

    def test_missing_bars_skipped_not_fatal(self):
        r = build_rotation(
            _pools(limitup=[_lim(c, c, "半导体") for c in "ABCD"]),
            "20260731",
            fetch_min=_fetch({"A": FLAT, "B": FLAT, "C": FLAT}),  # D 取不到
        )
        assert r["universe"] == 4 and r["fetched"] == 3

    def test_empty_pools(self):
        r = build_rotation(_pools(), "20260731", fetch_min=_fetch({}))
        assert r["universe"] == 0 and r["groups"] == [] and r["rotations"] == []


class TestCurve:
    def test_prev_close_derived_from_last_bar(self):
        """涨幅由「末根 close / (1+pct/100)」反推的昨收算出,末点应等于 pct。"""
        rows, fetch = _stub([(c, c, "半导体", FLAT) for c in "ABC"])  # FLAT 收在 +3.0%
        r = build_rotation(_pools(limitup=rows), "20260731", fetch_min=fetch)
        assert r["groups"][0]["points"][-1]["pct"] == pytest.approx(3.0, abs=0.05)

    def test_all_buckets_filled(self):
        rows, fetch = _stub([(c, c, "半导体", FLAT) for c in "ABC"])
        r = build_rotation(_pools(limitup=rows), "20260731", fetch_min=fetch)
        assert [p["t"] for p in r["groups"][0]["points"]] == BUCKETS

    def test_min_stocks_threshold(self):
        """少于 3 只不成板块(与 theme_heat 同口径)。"""
        rows, fetch = _stub([("A", "甲", "半导体", FLAT), ("B", "乙", "半导体", FLAT)])
        r = build_rotation(_pools(limitup=rows), "20260731", fetch_min=fetch)
        assert r["industries"] == []

    def test_leaders_sorted_by_pct(self):
        r = build_rotation(
            _pools(limitup=[_lim("A", "甲", "半导体", pct=5.0),
                            _lim("B", "乙", "半导体", pct=10.0),
                            _lim("C", "丙", "半导体", pct=7.0)]),
            "20260731",
            fetch_min=_fetch({c: FLAT for c in "ABC"}),
        )
        assert [x["name"] for x in r["groups"][0]["leaders"]] == ["乙", "丙", "甲"]


class TestShape:
    def _shape_of(self, curve):
        rows, fetch = _stub([(c, c, "半导体", curve) for c in "ABC"])
        return build_rotation(_pools(limitup=rows), "20260731", fetch_min=fetch)["groups"][0]

    def test_early_fade(self):
        c = self._shape_of(FADE)
        assert c["shape"] == "早盘冲高回落"
        assert c["peak_at"] <= "10:30" and c["fade"] >= 2

    def test_midday_taker(self):
        c = self._shape_of(TAKE)
        assert c["shape"] in ("盘中接棒", "尾盘走强")
        assert c["close"] - c["open"] >= 3

    def test_flat(self):
        assert self._shape_of(FLAT)["shape"] == "全天平推"

    def test_weak_all_day(self):
        assert self._shape_of([-2.0] * 17)["shape"] == "全天弱"


class TestRotations:
    def _rot(self):
        rows, fetch = _stub(
            [(f"F{i}", f"退{i}", "半导体", FADE) for i in range(4)]
            + [(f"T{i}", f"接{i}", "软件开发", TAKE) for i in range(4)]
        )
        return build_rotation(_pools(limitup=rows), "20260731", fetch_min=fetch)

    def test_direction_not_reversed(self):
        """退潮方必须是早见顶回落那个,接棒方是晚见顶守住那个 —— 方向反了整个结论就反了。"""
        r = self._rot()
        assert r["rotations"], "应识别出一条切换"
        x = r["rotations"][0]
        assert x["fader"] == "半导体" and x["taker"] == "软件开发"
        assert x["fader_peak_at"] < x["taker_peak_at"]
        assert x["fader_fade"] >= 2 and x["taker_rise"] >= 3

    def test_evidence_carries_numbers(self):
        x = self._rot()["rotations"][0]
        assert "%" in x["evidence"] and "只" in x["evidence"]

    def test_one_row_per_fader(self):
        r = self._rot()
        faders = [x["fader"] for x in r["rotations"]]
        assert len(faders) == len(set(faders))

    def test_no_rotation_when_all_flat(self):
        rows, fetch = _stub([(c, c, "半导体", FLAT) for c in "ABC"])
        r = build_rotation(_pools(limitup=rows), "20260731", fetch_min=fetch)
        assert r["rotations"] == []


class TestSealTimeline:
    def test_sealed_and_broken_split(self):
        r = build_rotation(
            _pools(limitup=[_lim("A", "甲", "半导体", last_seal="093000")],
                   zbgc=[_zb("B", "乙", "软件开发", first_seal="101500")]),
            "20260731",
            fetch_min=_fetch({"A": FLAT, "B": FADE}),
        )
        rows = {x["t"]: x for x in r["seal_timeline"]}
        assert rows["09:30"]["sealed"].get("科技硬件") == 1
        assert rows["10:30"]["broken"].get("科技应用") == 1

    def test_previous_pool_excluded(self):
        """昨日涨停池的 prev_seal 是**昨天**封的,绝不能计入今日封板时序。"""
        r = build_rotation(
            _pools(previous=[_prev("A", "甲", "半导体", prev_seal="093000")]),
            "20260731",
            fetch_min=_fetch({"A": FLAT}),
        )
        assert all(not x["sealed"] and not x["broken"] for x in r["seal_timeline"])

    def test_last_seal_wins_over_first(self):
        """炸板后回封的票,时序按最终封板那一刻计。"""
        r = build_rotation(
            _pools(limitup=[_lim("A", "甲", "半导体", first_seal="093000",
                                 last_seal="140000", break_times=3)]),
            "20260731",
            fetch_min=_fetch({"A": FLAT}),
        )
        rows = {x["t"]: x for x in r["seal_timeline"]}
        assert rows["14:00"]["sealed"].get("科技硬件") == 1
        assert not rows["09:30"]["sealed"]
