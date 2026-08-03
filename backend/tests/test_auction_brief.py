"""盘前解读(auction_brief)存取测试。用临时库隔离,不碰真实 data/daban.db。"""

from __future__ import annotations

import pytest

from daban_review.app import service
from daban_review.data import store


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """把 store.get_conn 指到临时库,避免测试写进真实 SQLite。"""
    db = tmp_path / "t.db"
    orig = store.get_conn
    monkeypatch.setattr(store, "get_conn", lambda db_path=None: orig(str(db)))
    yield


def test_save_and_get_roundtrip():
    service.save_auction_brief("20260727", "电力续强,存储被按")
    got = service.get_auction_brief("20260727")
    assert got is not None
    assert got["brief"] == "电力续强,存储被按"
    assert got["date"] == "20260727"
    assert got["created_at"]


def test_get_missing_returns_none():
    assert service.get_auction_brief("20260101") is None


def test_same_date_overwrites():
    service.save_auction_brief("20260727", "旧解读")
    service.save_auction_brief("20260727", "新解读")
    assert service.get_auction_brief("20260727")["brief"] == "新解读"


def test_blank_brief_not_saved():
    # agent 解读失败时传空串,不该落一条空记录
    service.save_auction_brief("20260728", "   ")
    assert service.get_auction_brief("20260728") is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
