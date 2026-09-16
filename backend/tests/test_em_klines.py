"""东财 push2his K线源(替代 mootdx)的解析与降级测试。全部打桩,不联网。

背景:2026-09-11 起公开通达信服务器对数据类接口一律空返(请求 5 根日线只回 2 字节,
头部声称 800 根却没有数据),14 台可达服务器行为一致 —— 服务端不再供数,换客户端无用。
于是 K线主源改东财 `push2his`,mootdx 退为兜底。

夹具是真实抓到的响应片段(fields2=f51..f57 → 时间,开,收,高,低,量,额)。
"""

from __future__ import annotations

import pandas as pd
import pytest

from daban_review.data import akshare_client as ak

# 真实响应:2026-09-01 起西陇科学(002584)日线
DAILY_KLINES = [
    "2026-09-01,8.39,8.38,8.40,8.25,219767,184500000.00",
    "2026-09-02,8.29,8.39,8.45,8.20,240000,201000000.00",
    "2026-09-03,8.40,8.68,8.68,8.36,310000,265000000.00",
]
MIN_KLINES = [
    "2026-09-16 09:31,9.10,9.15,9.16,9.09,1200,1098000.00",
    "2026-09-16 09:32,9.15,9.20,9.21,9.14,900,828000.00",
    "2026-09-15 14:59,8.80,8.81,8.82,8.79,500,440000.00",  # 前一日,应被过滤掉
]


@pytest.fixture
def em(monkeypatch):
    """打桩 _em_klines,记录被请求的 (secid, klt, limit)。"""
    calls = []

    def _set(klines):
        def fake(secid, klt, limit):
            calls.append((secid, klt, limit))
            return klines
        monkeypatch.setattr(ak, "_em_klines", fake)
        return calls
    return _set


class TestSecid:
    """代码 → 东财 secid。沪深分错市场会直接查无此票。"""

    @pytest.mark.parametrize("code,want", [
        ("002584", "0.002584"),   # 深主板
        ("300750", "0.300750"),   # 创业板
        ("000993", "0.000993"),   # 深主板
        ("605058", "1.605058"),   # 沪主板
        ("603042", "1.603042"),   # 沪主板
        ("688981", "1.688981"),   # 科创板也是 6 开头 → 沪
    ])
    def test_market_prefix(self, code, want):
        assert ak._em_secid(code) == want

    def test_index_secid_is_explicit_not_derived(self):
        """指数不能按前缀推:000001 既是上证指数也是平安银行,必须用固定映射。"""
        assert ak._EM_INDEX_SECID["999999"] == "1.000001"   # 上证指数
        assert ak._EM_INDEX_SECID["399006"] == "0.399006"   # 创业板指
        assert ak._em_secid("000001") == "0.000001"         # 个股规则下是平安银行


class TestFrame:
    def test_parses_seven_fields(self):
        df = ak._em_frame(DAILY_KLINES)
        assert len(df) == 3
        assert df.iloc[0]["open"] == 8.39 and df.iloc[0]["close"] == 8.38
        assert df.iloc[0]["high"] == 8.40 and df.iloc[0]["low"] == 8.25
        assert df.iloc[0]["vol"] == 219767

    def test_drops_short_rows(self):
        """字段缺失的行直接丢,不要让 NaN 混进量价计算。"""
        assert ak._em_frame(["2026-09-01,8.39,8.38"]).empty

    def test_empty_in_empty_out(self):
        assert ak._em_frame([]).empty


class TestDailyBars:
    def test_normalizes_columns_and_date(self, em):
        em(DAILY_KLINES)
        d = ak.daily_bars("002584", 3)
        assert list(d.columns) == ["date", "open", "close", "high", "low", "vol", "amount"]
        assert d.iloc[0]["date"] == "20260901"  # 东财给 2026-09-01,统一成 YYYYMMDD
        assert d.iloc[2]["close"] == 8.68

    def test_requests_daily_klt_and_n(self, em):
        calls = em(DAILY_KLINES)
        ak.daily_bars("605058", 40)
        assert calls == [("1.605058", 101, 40)]  # klt=101 日线

    def test_falls_back_to_mootdx_when_em_empty(self, em, monkeypatch):
        em([])
        fake = pd.DataFrame({
            "datetime": ["2026-09-16 00:00"], "open": [1.0], "close": [2.0],
            "high": [2.1], "low": [0.9], "vol": [100.0], "amount": [200.0],
        })
        monkeypatch.setattr(ak, "_mootdx", lambda: type("Q", (), {"bars": lambda *a, **k: fake})())
        d = ak.daily_bars("002584", 8)
        assert len(d) == 1 and d.iloc[0]["date"] == "20260916"

    def test_returns_empty_not_raise_when_both_sources_dead(self, em, monkeypatch):
        """两个源都挂 → 空表。抛异常会让 abnormal/pattern_blacklist 整批扫描废掉。"""
        em([])

        def boom():
            raise RuntimeError("tdx 空返")
        monkeypatch.setattr(ak, "_mootdx", boom)
        assert ak.daily_bars("002584", 8).empty


class TestIntradayMin:
    def test_filters_to_requested_day(self, em):
        em(MIN_KLINES)
        d = ak.stock_intraday_min("002584", "20260916")
        assert len(d) == 2                      # 09-15 那根被过滤
        assert list(d["time"]) == ["09:31", "09:32"]
        assert d.iloc[0]["close"] == 9.15

    def test_uses_minute_klt(self, em):
        calls = em(MIN_KLINES)
        ak.stock_intraday_min("002584", "20260916")
        assert calls[0][1] == 1                 # klt=1 一分钟

    def test_empty_when_day_absent(self, em):
        em(["2026-09-15 14:59,8.80,8.81,8.82,8.79,500,440000.00"])
        assert ak.stock_intraday_min("002584", "20260916").empty


class TestIndexIntradayMin:
    def test_maps_tdx_code_to_em_secid(self, em):
        calls = em(["2026-09-16 09:31,3200.1,3201.5,3202.0,3199.8,10000,120000000.00"])
        d = ak.index_intraday_min("999999", "20260916")
        assert calls[0][0] == "1.000001"        # 上证指数
        assert list(d.columns) == ["time", "close", "high", "low", "vol", "amount"]
        assert d.iloc[0]["close"] == 3201.5

    def test_unknown_index_code_skips_em(self, em, monkeypatch):
        """不在映射表里的指数代码不该瞎猜 secid,直接走兜底。"""
        calls = em(DAILY_KLINES)
        monkeypatch.setattr(ak, "_mootdx", lambda: type("Q", (), {"index": lambda *a, **k: None})())
        with pytest.raises(Exception):
            ak.index_intraday_min("880888", "20260916")
        assert calls == []                      # 压根没请求东财
