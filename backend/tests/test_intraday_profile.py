"""分时弹窗的当日资金画像:涨停池 → 炸板池 → 都没有。纯本地,池子用打桩。"""

from __future__ import annotations

import pandas as pd
import pytest


def _lim_row(code="000533", name="顺钠股份", seal_amount=3e8, float_mv=1e10):
    return {
        "code": code, "name": name, "boards": 3, "pct": 10.0, "price": 10.51,
        "amount": 5.2e8, "float_mv": float_mv, "total_mv": float_mv, "turnover": 9.51,
        "seal_amount": seal_amount, "first_seal": "093027", "last_seal": "145900",
        "break_times": 2, "zt_stat": "3/3", "industry": "电子",
    }


def _zb_row(code="002580", name="圣阳股份"):
    return {"code": code, "name": name, "pct": 6.1, "first_seal": "101500",
            "break_times": 3, "zt_stat": "1/1", "industry": "电池"}


@pytest.fixture
def svc(monkeypatch):
    from daban_review.app import service

    def fake_pools(_date):
        return {
            "limitup": pd.DataFrame([_lim_row()]),
            "zbgc": pd.DataFrame([_zb_row()]),
        }

    monkeypatch.setattr(service, "load_pools", fake_pools)
    return service


class TestFromLimitup:
    def test_seal_fields(self, svc):
        p = svc._intraday_profile("000533", "20260728")
        assert p["source"] == "limitup"
        assert p["seal_strength"] == 0.03  # 3e8/1e10
        assert p["seal_amount"] == 3e8
        assert p["first_seal"] == "093027" and p["last_seal"] == "145900"
        assert p["break_times"] == 2 and p["turnover"] == 9.51
        assert p["boards"] == 3 and p["zt_stat"] == "3/3"

    def test_carries_amount_and_float_mv(self, svc):
        """成交额与流通市值也要带上:封流比要靠流通市值才能理解,成交额是资金强弱的直接量。"""
        p = svc._intraday_profile("000533", "20260728")
        assert p["amount"] == 5.2e8 and p["float_mv"] == 1e10


class TestFromZbgc:
    def test_broken_stock_has_no_seal_data(self, svc):
        """炸板票没封住 → 封单金额/封流比/换手为 None,但首封与炸板次数要有。"""
        p = svc._intraday_profile("002580", "20260728")
        assert p["source"] == "zbgc"
        assert p["seal_strength"] is None and p["seal_amount"] is None
        assert p["first_seal"] == "101500" and p["break_times"] == 3


class TestMisses:
    def test_ordinary_stock_returns_none(self, svc):
        assert svc._intraday_profile("600000", "20260728") is None

    def test_empty_pools(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "load_pools",
                            lambda _d: {"limitup": pd.DataFrame(), "zbgc": pd.DataFrame()})
        assert service._intraday_profile("000533", "20260728") is None

    def test_pool_load_failure_is_swallowed(self, monkeypatch):
        """池子读不出来时返回 None 而不是抛 —— 分时图是主体,画像只是附加信息。"""
        from daban_review.app import service

        def boom(_d):
            raise RuntimeError("db gone")

        monkeypatch.setattr(service, "load_pools", boom)
        assert service._intraday_profile("000533", "20260728") is None


class TestGetIntradayShape:
    def test_profile_present_even_without_points(self, svc, monkeypatch):
        """没有分时数据(非交易日/数据源空)时也要带 profile,前端才能显示封单信息。"""
        from daban_review.data import akshare_client as ak

        monkeypatch.setattr(ak, "stock_intraday_min", lambda *a, **k: pd.DataFrame())
        monkeypatch.setattr(ak, "daily_bars", lambda *a, **k: pd.DataFrame())
        out = svc.get_intraday("000533", "20260728")
        assert out["points"] == [] and out["profile"] is not None
        assert out["profile"]["seal_strength"] == 0.03
