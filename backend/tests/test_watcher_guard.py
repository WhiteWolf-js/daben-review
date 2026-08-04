"""watcher 的交易日守卫(`_is_trade_day`)测试。不联网,日线接口打桩。

守卫存在的理由:launchd 按「周一至五 09:20」拉起 watcher,挡得住周末但挡不住法定节假日,
所以进程要能自己判出「今天不是交易日」然后退出,别整天空转、也别让前端显示成「监控中」。

判据是「通达信**当日**日线是否已生成」——没有可用的节假日日历(akshare 那个走 py_mini_racer,
本机已坏)。关键是**返回 None 表示还判不出来**,调用方必须继续监控而不是当成非交易日。
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from daban_review.monitor import watcher


@pytest.fixture
def bars(monkeypatch):
    """打桩 ak.daily_bars,返回给定日期列表。"""
    def _set(dates, exc=None):
        def fake(code, n=8):
            if exc:
                raise exc
            return pd.DataFrame({"date": list(dates)})
        monkeypatch.setattr(watcher.ak, "daily_bars", fake)
    return _set


AFTER = dt.time(10, 0)   # 守卫已生效
BEFORE = dt.time(9, 26)  # 守卫还没到点


class TestGuard:
    def test_too_early_returns_none(self, bars):
        """9:35 前一律 None —— 当日日线要开盘有成交才生成,这会儿判会把真交易日误杀。"""
        bars(["20260731", "20260803"])
        assert watcher._is_trade_day("20260804", BEFORE) is None

    def test_today_present_is_trade_day(self, bars):
        bars(["20260731", "20260803", "20260804"])
        assert watcher._is_trade_day("20260804", AFTER) is True

    def test_today_absent_is_not_trade_day(self, bars):
        """节假日:通达信不会生成当日日线,最近几根都是节前的。"""
        bars(["20260929", "20260930"])
        assert watcher._is_trade_day("20261001", AFTER) is False

    def test_fetch_error_returns_none_not_false(self, bars):
        """网络抖动不能当成非交易日,否则一次拉取失败就把当天监控整个掐掉。"""
        bars([], exc=RuntimeError("mootdx 连接超时"))
        assert watcher._is_trade_day("20260804", AFTER) is None

    def test_guard_boundary_exactly_at_935(self, bars):
        bars(["20260804"])
        assert watcher._is_trade_day("20260804", dt.time(9, 35)) is True
        assert watcher._is_trade_day("20260804", dt.time(9, 34)) is None


def _freeze(monkeypatch, hh: int, mm: int):
    """把 watcher 看到的 now 冻住。

    **必须冻**:`run()` 第一件事就是 `now > 15:00 → break`,不冻的话这些用例在收盘后跑
    会一进循环就退出 —— 于是「非交易日不轮询」变成无论守卫对错都成立的假通过。踩过。
    """
    class _Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 8, 4, hh, mm)

    monkeypatch.setattr(watcher.dt, "datetime", _Frozen)


class TestWiring:
    """守卫接进 run() 循环的接线。判据函数对不代表接线对(break/continue 写错、
    或守卫放在轮询之后都会让它失效)。"""

    def test_non_trade_day_exits_without_polling(self, monkeypatch):
        polled = []
        _freeze(monkeypatch, 10, 0)  # 盘中
        monkeypatch.setattr(watcher, "_is_trade_day", lambda d, n: False)
        monkeypatch.setattr(watcher, "poll_once", lambda d: polled.append(d) or ({}, {}))
        monkeypatch.setattr(watcher.time, "sleep", lambda s: None)

        watcher.run()  # 非交易日应立刻返回,不该卡在循环里
        assert polled == [], "非交易日不该轮询任何数据"

    def test_trade_day_does_poll(self, monkeypatch):
        """对照组:同样冻在盘中,守卫说是交易日就必须真的轮询 ——
        否则上一条的 `polled == []` 说明不了守卫起了作用。"""
        polled: list[str] = []
        _freeze(monkeypatch, 10, 0)
        monkeypatch.setattr(watcher, "_is_trade_day", lambda d, n: True)

        def fake_poll(date):
            polled.append(date)
            if len(polled) >= 2:
                _freeze(monkeypatch, 15, 30)  # 轮两次就"收盘",避免死循环
            return {"ts": "10:00"}, {}

        monkeypatch.setattr(watcher, "poll_once", fake_poll)
        monkeypatch.setattr(watcher.signals, "detect_events", lambda *a, **k: [])
        monkeypatch.setattr(watcher.store, "save_live", lambda *a, **k: None)
        monkeypatch.setattr(watcher.time, "sleep", lambda s: None)

        watcher.run()
        assert len(polled) >= 2

    def test_unknown_keeps_polling(self, monkeypatch):
        """判不出来(None)时必须继续监控 —— 判据没到点/拉取失败都不该掐掉当天。"""
        calls = {"n": 0}
        _freeze(monkeypatch, 9, 30)  # 守卫生效时刻(9:35)之前

        def fake_poll(date):
            calls["n"] += 1
            if calls["n"] >= 2:
                _freeze(monkeypatch, 15, 30)
            return {"ts": "09:30"}, {}

        monkeypatch.setattr(watcher, "_is_trade_day", lambda d, n: None)
        monkeypatch.setattr(watcher, "poll_once", fake_poll)
        monkeypatch.setattr(watcher.signals, "detect_events", lambda *a, **k: [])
        monkeypatch.setattr(watcher.store, "save_live", lambda *a, **k: None)
        monkeypatch.setattr(watcher.time, "sleep", lambda s: None)

        watcher.run()
        assert calls["n"] >= 2, "判不出交易日时应继续轮询"


class TestSessionUnchanged:
    """守卫不该动原有的时段判定。"""

    @pytest.mark.parametrize("hhmm,expect", [
        ((9, 24), False), ((9, 25), True), ((11, 30), True), ((11, 31), False),
        ((12, 30), False), ((13, 0), True), ((15, 0), True), ((15, 1), False),
    ])
    def test_in_session(self, hhmm, expect):
        assert watcher._in_session(dt.time(*hhmm)) is expect

    @pytest.mark.parametrize("hhmm,expect", [
        ((9, 25), True), ((9, 59), True), ((10, 0), False),
        ((14, 29), False), ((14, 30), True), ((14, 59), True), ((15, 0), False),
    ])
    def test_in_rush(self, hhmm, expect):
        assert watcher._in_rush(dt.time(*hhmm)) is expect
