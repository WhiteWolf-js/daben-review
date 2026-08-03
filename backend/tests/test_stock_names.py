"""全 A 名录落库(store.stock_names)的读写与过期判定。用临时库,不碰真实数据。"""

from __future__ import annotations

import datetime as dt

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把 CONFIG.db_path 指到临时文件,store 的每个函数都自己 get_conn,故改配置即可隔离。"""
    from daban_review.config import CONFIG
    from daban_review.data import store as st

    monkeypatch.setattr(CONFIG, "db_path", str(tmp_path / "t.db"))
    return st


SAMPLE = {"兴业股份": "603928", "好想你": "002582", "顺钠股份": "000533"}


class TestSaveLoad:
    def test_roundtrip(self, store):
        assert store.save_stock_names(SAMPLE) == 3
        assert store.load_stock_names() == SAMPLE

    def test_empty_save_is_noop(self, store):
        """拉取失败传空 dict 时不能把已有名录清掉。"""
        store.save_stock_names(SAMPLE)
        assert store.save_stock_names({}) == 0
        assert store.load_stock_names() == SAMPLE

    def test_save_replaces_whole_table(self, store):
        store.save_stock_names(SAMPLE)
        store.save_stock_names({"新票": "301999"})
        assert store.load_stock_names() == {"新票": "301999"}

    def test_load_on_empty_db(self, store):
        assert store.load_stock_names() == {}

    def test_expired_returns_empty(self, store):
        """超过 max_age_days 视为过期,让调用方重拉。"""
        store.save_stock_names(SAMPLE)
        old = (dt.datetime.now() - dt.timedelta(days=30)).isoformat(timespec="seconds")
        conn = store.get_conn()
        conn.execute("UPDATE stock_names SET updated_at=?", (old,))
        conn.commit()
        conn.close()
        assert store.load_stock_names(max_age_days=7) == {}
        assert store.load_stock_names(max_age_days=3650) == SAMPLE  # 兜底:过期也比没有好

    def test_meta(self, store):
        store.save_stock_names(SAMPLE)
        meta = store.stock_names_meta()
        assert meta["count"] == 3 and meta["updated_at"]


class TestNameMapUsesDb:
    def test_reads_from_db_without_network(self, store, monkeypatch):
        """库里有新鲜名录时 stock_name_map 不该联网(mootdx 打桩成抛异常也能返回)。"""
        from daban_review.data import akshare_client as ak

        store.save_stock_names(SAMPLE)
        monkeypatch.setattr(ak, "_name_map_cache", None)
        monkeypatch.setattr(ak, "_mootdx", lambda: (_ for _ in ()).throw(AssertionError("不该联网")))
        assert ak.stock_name_map() == SAMPLE

    def test_force_bypasses_db(self, store, monkeypatch):
        from daban_review.data import akshare_client as ak

        store.save_stock_names(SAMPLE)
        monkeypatch.setattr(ak, "_name_map_cache", None)
        called: list[str] = []

        def boom():
            called.append("x")
            raise RuntimeError("mootdx down")

        monkeypatch.setattr(ak, "_mootdx", boom)
        monkeypatch.setattr(ak, "_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ak down")))
        # 两个源都挂 → 退回库里的旧名录(而不是空)
        assert ak.stock_name_map(force=True) == SAMPLE
        assert called, "force=True 必须真的去拉一次"
