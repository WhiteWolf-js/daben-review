"""盘中监控判据 signals.py 单测(纯函数,零网络)。"""

import pandas as pd
import pytest

from daban_review.monitor import signals


def _limitup(rows):
    """rows: [(code, name, boards, seal_amount, break_times), ...] → 归一后英文列 df。"""
    return pd.DataFrame(rows, columns=["code", "name", "boards", "seal_amount", "break_times"])


# ---------- build_snapshot ----------

def test_build_snapshot_basic():
    df = _limitup([("000001", "甲", 4, 1e8, 0), ("000002", "乙", 2, 5e7, 1)])
    snap = signals.build_snapshot("10:00", df, zbgc_count=3, hot_top5=["000001", "000002"])
    assert snap["ts"] == "10:00"
    assert snap["zt_count"] == 2
    assert snap["zbgc_count"] == 3
    assert snap["hot_top5"] == ["000001", "000002"]
    assert snap["limitup"]["000001"]["boards"] == 4
    assert snap["limitup"]["000001"]["name"] == "甲"
    assert snap["max_board"] == 4
    assert snap["lianban_count"] == 2  # 4板 + 2板都 ≥2


def test_build_snapshot_derived_empty():
    snap = signals.build_snapshot("09:30", pd.DataFrame(), 0, [])
    assert snap["max_board"] == 0 and snap["lianban_count"] == 0


def test_build_snapshot_empty_and_none():
    assert signals.build_snapshot("09:30", pd.DataFrame(), 0, [])["zt_count"] == 0
    assert signals.build_snapshot("09:30", None, 0, None)["limitup"] == {}


def test_build_snapshot_hot_top5_truncated():
    snap = signals.build_snapshot("10:00", pd.DataFrame(), 0, list("abcdefg"))
    assert snap["hot_top5"] == ["a", "b", "c", "d", "e"]


def test_build_snapshot_missing_cols_and_bad_values():
    # 缺 seal_amount / break_times,boards 非数字 → 走默认不炸
    df = pd.DataFrame([{"code": "000001", "name": "甲", "boards": "x"}])
    snap = signals.build_snapshot("10:00", df, 0, [])
    assert snap["limitup"]["000001"]["boards"] == 0
    assert snap["limitup"]["000001"]["seal_amount"] == 0
    assert snap["limitup"]["000001"]["break_times"] == 0


def test_build_snapshot_skips_blank_code():
    df = _limitup([("", "空", 3, 0, 0), ("000001", "甲", 3, 0, 0)])
    snap = signals.build_snapshot("10:00", df, 0, [])
    assert list(snap["limitup"]) == ["000001"]


# ---------- index_drop_pct ----------

def test_index_drop_pct_15min():
    # 20 根,倒数第 16 根为 100,现价 99 → -1.0%
    closes = [100.0] * 5 + [100.0] + [100.5] * 14 + [99.0]
    df = pd.DataFrame({"close": closes})
    # 现价 99,15 分钟前 = 倒数第 16 根
    assert signals.index_drop_pct(df, minutes=15) == round((99.0 / df["close"].iloc[-16] - 1) * 100, 2)


def test_index_drop_pct_short_series_uses_first():
    df = pd.DataFrame({"close": [100.0, 98.0]})  # 不足 15 根,用首根
    assert signals.index_drop_pct(df, minutes=15) == -2.0


def test_index_drop_pct_insufficient_or_empty():
    assert signals.index_drop_pct(pd.DataFrame(), 15) is None
    assert signals.index_drop_pct(pd.DataFrame({"close": [100.0]}), 15) is None
    assert signals.index_drop_pct(None, 15) is None


def test_index_drop_pct_missing_close():
    assert signals.index_drop_pct(pd.DataFrame({"price": [1, 2, 3]}), 15) is None


# ---------- detect_events: 龙头/高度板炸板 ----------

def _snap(ts, codes_boards, zbgc=0, hot5=None):
    """codes_boards: {code: boards} → 快照。"""
    df = _limitup([(c, c, b, 0, 0) for c, b in codes_boards.items()])
    return signals.build_snapshot(ts, df, zbgc, hot5 or [])


def test_high_board_break_pushed():
    prev = _snap("10:00", {"000001": 5, "000002": 2})
    cur = _snap("10:01", {"000002": 2})  # 5 板的 000001 炸了
    evs = signals.detect_events(prev, cur, {}, set())
    assert len(evs) == 1
    assert evs[0]["type"] == "leader_break"
    assert evs[0]["key"] == "break:000001"


def test_low_board_break_not_pushed():
    prev = _snap("10:00", {"000003": 2})
    cur = _snap("10:01", {})  # 2 板炸了,非龙头非高度板 → 不推
    assert signals.detect_events(prev, cur, {}, set()) == []


def test_leader_break_pushed_even_if_low_board():
    prev = _snap("10:00", {"000009": 1}, hot5=["000009"])  # 1 板但人气第一
    cur = _snap("10:01", {})
    evs = signals.detect_events(prev, cur, {}, set())
    assert len(evs) == 1 and evs[0]["key"] == "break:000009"
    assert "人气前5" in evs[0]["detail"]


def test_first_round_no_break_event():
    cur = _snap("09:30", {"000001": 5})
    # prev=None 首轮:无炸板对比(但仍可能有炸板潮/指数事件,这里都不触发)
    assert signals.detect_events(None, cur, {}, set()) == []


def test_break_deduped_by_pushed():
    prev = _snap("10:00", {"000001": 5})
    cur = _snap("10:01", {})
    assert signals.detect_events(prev, cur, {}, {"break:000001"}) == []


def test_reseal_not_double_counted():
    # 炸后回封:code 又回到涨停池,broke 里没有它 → 不再触发
    prev = _snap("10:00", {"000001": 5})
    cur = _snap("10:02", {"000001": 5})
    assert signals.detect_events(prev, cur, {}, {"break:000001"}) == []


# ---------- detect_events: 炸板潮 ----------

def test_zhaban_tide_pushed():
    # 涨停 30 + 炸板 24 = 54 基数,率 = 24/54 = 44% ≥ 40%
    cur = _snap("10:30", {f"{i:06d}": 1 for i in range(30)}, zbgc=24)
    evs = [e for e in signals.detect_events(None, cur, {}, set()) if e["type"] == "zhaban_tide"]
    assert len(evs) == 1
    assert evs[0]["key"] == "zbtide:4"  # 0.44 → 档 4


def test_zhaban_tide_below_base_not_pushed():
    # 基数不足 20(涨停 5 + 炸板 4 = 9),即便率高也不推(滤早盘小样本)
    cur = _snap("09:31", {f"{i:06d}": 1 for i in range(5)}, zbgc=4)
    assert [e for e in signals.detect_events(None, cur, {}, set()) if e["type"] == "zhaban_tide"] == []


def test_zhaban_tide_below_rate_not_pushed():
    # 基数够(涨停 30 + 炸板 5 = 35)但率 14% < 40%
    cur = _snap("10:30", {f"{i:06d}": 1 for i in range(30)}, zbgc=5)
    assert [e for e in signals.detect_events(None, cur, {}, set()) if e["type"] == "zhaban_tide"] == []


def test_zhaban_tide_bucket_allows_reescalation():
    # 率升到 0.5 → 档 5,与 0.4 的档 4 不同 key,可补推
    cur = _snap("10:40", {f"{i:06d}": 1 for i in range(25)}, zbgc=25)  # 25/50 = 50%
    evs = [e for e in signals.detect_events(None, cur, {}, {"zbtide:4"}) if e["type"] == "zhaban_tide"]
    assert len(evs) == 1 and evs[0]["key"] == "zbtide:5"


# ---------- detect_events: 指数急杀 ----------

def test_index_plunge_shanghai():
    cur = _snap("14:00", {})
    evs = [e for e in signals.detect_events(None, cur, {"上证指数": -0.9}, set())
           if e["type"] == "index_plunge"]
    assert len(evs) == 1 and evs[0]["key"] == "idxdrop:上证指数:9"


def test_index_plunge_chinext_higher_threshold():
    cur = _snap("14:00", {})
    # 创业板 -1.0% 未破 -1.2% 阈值 → 不推
    assert [e for e in signals.detect_events(None, cur, {"创业板指": -1.0}, set())
            if e["type"] == "index_plunge"] == []
    # -1.3% 破阈值 → 推
    evs = [e for e in signals.detect_events(None, cur, {"创业板指": -1.3}, set())
           if e["type"] == "index_plunge"]
    assert len(evs) == 1


def test_index_plunge_none_skipped():
    cur = _snap("14:00", {})
    assert signals.detect_events(None, cur, {"上证指数": None}, set()) == []


def test_index_plunge_rise_not_pushed():
    cur = _snap("14:00", {})
    assert signals.detect_events(None, cur, {"上证指数": 0.5}, set()) == []


def test_multiple_events_together():
    prev = _snap("14:00", {"600001": 5})  # 龙头,不在下面 000xxx 区间
    cur = _snap("14:31", {f"{i:06d}": 1 for i in range(30)}, zbgc=24)  # 600001 炸 + 炸板潮
    evs = signals.detect_events(prev, cur, {"上证指数": -0.9}, set())
    types = {e["type"] for e in evs}
    assert types == {"leader_break", "zhaban_tide", "index_plunge"}
