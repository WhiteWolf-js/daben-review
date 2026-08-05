"""service.get_candidate_pool 的测试(打桩,不联网)。

这个函数存在的意义:前端「明日候选」只显示 agent 写进正文的 rank1,池里 rank2-5 的
A 级票全被藏着。它把完整备选连同**板块联动**吐出来,纯规则零 token。

锁两条最容易出错的:
- `theme_rank` 输入必须用生产口径(theme_heat 默认 top=12),否则显示的池子 ≠ agent 看到的
- 板块联动取**身位最强**的题材,不是家数最多的(泛业绩标签家数多但不是主线)
"""

from __future__ import annotations

import pandas as pd
import pytest

from daban_review.app import service


def _lim(code, name, boards, seal=3e8, mv=1e10, first="093000", last=None, turn=5.0, breaks=0):
    return {"code": code, "name": name, "boards": boards, "pct": 10.0, "price": 11.0,
            "amount": 5e8, "float_mv": mv, "total_mv": mv, "turnover": turn,
            "seal_amount": seal, "first_seal": first,
            "last_seal": last if last is not None else first,
            "break_times": breaks, "zt_stat": f"{boards}/{boards}", "industry": "半导体"}


@pytest.fixture
def stub(monkeypatch):
    """打桩 load_pools / 题材 / 前日炸板,返回可控盘面。"""
    def _set(limitup_rows, themes):
        monkeypatch.setattr(service, "load_pools",
                            lambda d: {"limitup": pd.DataFrame(limitup_rows),
                                       "previous": pd.DataFrame(), "zbgc": pd.DataFrame(),
                                       "dtgc": pd.DataFrame()})
        from daban_review.data import akshare_client as ak
        monkeypatch.setattr(ak, "ths_limitup_reasons", lambda d: themes)
        monkeypatch.setattr(service.store, "prev_zbgc_codes", lambda d: set())
    return _set


class TestGradeFilter:
    def test_only_a_and_above_by_default(self, stub):
        # 两只低位连板:一只强封(A 级以上)、一只弱封高换手炸板(必然 D)
        stub([_lim("A", "强票", 2, seal=5e8, turn=2.0),
              _lim("B", "烂票", 2, seal=1e6, turn=40.0, breaks=5, first="143000")],
             {"A": ["算力租赁"], "B": ["算力租赁"]})
        pool = service.get_candidate_pool("20260804")["pool"]["低位连板接力"]
        names = [x["name"] for x in pool]
        assert "强票" in names and "烂票" not in names

    def test_grades_param_can_widen(self, stub):
        stub([_lim("A", "强票", 2, seal=5e8, turn=2.0),
              _lim("B", "烂票", 2, seal=1e6, turn=40.0, breaks=5, first="143000")],
             {"A": ["算力租赁"], "B": ["算力租赁"]})
        wide = service.get_candidate_pool("20260804", ("A+", "A", "B", "C", "D"))
        assert len(wide["pool"]["低位连板接力"]) == 2


class TestLink:
    def test_picks_strongest_position_theme_not_biggest(self, stub):
        """一只票同属「中报预增」(家数多但零连板)与「核电」(家数少但有连板高度),
        联动必须取核电 —— 泛业绩标签家数最多却不是主线。"""
        rows = [_lim("A", "主票", 2, seal=5e8, turn=2.0)]
        # 中报预增 4 只全首板;核电 2 只、其中一只 3 板
        rows += [_lim(f"P{i}", f"泛{i}", 1) for i in range(3)]
        rows += [_lim("N1", "核电高", 3)]
        themes = {"A": ["中报预增", "核电"], "N1": ["核电"],
                  **{f"P{i}": ["中报预增"] for i in range(3)}}
        stub(rows, themes)
        link = service.get_candidate_pool("20260804")["pool"]["低位连板接力"][0]["link"]
        assert link["theme"] == "核电"
        assert link["max_board"] == 3

    def test_solo_stock_has_no_link(self, stub):
        """题材只此一只 → 不成板块(theme_heat 的 min_count=2)→ link 为 None(孤票)。"""
        stub([_lim("A", "孤票", 2, seal=5e8, turn=2.0)], {"A": ["某独家概念"]})
        assert service.get_candidate_pool("20260804")["pool"]["低位连板接力"][0]["link"] is None

    def test_no_themes_at_all(self, stub):
        stub([_lim("A", "无题材", 2, seal=5e8, turn=2.0)], {})
        assert service.get_candidate_pool("20260804")["pool"]["低位连板接力"][0]["link"] is None


class TestProductionParity:
    def test_pool_built_with_top12_theme_heat_like_runner(self, stub, monkeypatch):
        """喂给 `build_candidate_pool` 的 `theme_rank` 必须是**生产口径**
        (`theme_heat` 默认 top=12,与 `runner.run_review` 一致)。

        传全量会改变 `theme_rank`,进而改变 `_unplayable`(换手<1% 且无主线归属沉池尾)
        的判定 —— 实测欣天科技(换手0.55%)在两种口径下一个沉池尾、一个当 rank1,
        于是前端显示的池子和 agent 当时看到的不是同一个。踩过。
        """
        import daban_review.metrics as M
        seen: list[int] = []
        orig = M.theme_heat

        def spy(pools, themes, top=12, **kw):
            seen.append(top)
            return orig(pools, themes, top=top, **kw)

        monkeypatch.setattr(M, "theme_heat", spy)
        stub([_lim("A", "票", 2, seal=5e8, turn=2.0)], {"A": ["算力租赁"]})
        service.get_candidate_pool("20260804")
        # 一次 top=12 建池(生产口径)、一次全量仅用于查联动读数
        assert seen[0] == 12, f"建池必须先用 top=12,实际调用顺序 {seen}"
        assert 9999 in seen, "联动读数需要全量题材榜"


class TestEmpty:
    def test_empty_pools(self, monkeypatch):
        monkeypatch.setattr(service, "load_pools",
                            lambda d: {"limitup": pd.DataFrame(), "previous": pd.DataFrame()})
        out = service.get_candidate_pool("20260804")
        assert out == {"date": "20260804", "phase": "未知", "pool": {}}

    def test_theme_fetch_failure_still_returns_pool(self, monkeypatch):
        """题材拉取失败只该丢掉联动信息,不能让整个池子出不来。"""
        monkeypatch.setattr(service, "load_pools",
                            lambda d: {"limitup": pd.DataFrame([_lim("A", "票", 2, seal=5e8, turn=2.0)]),
                                       "previous": pd.DataFrame(), "zbgc": pd.DataFrame()})
        from daban_review.data import akshare_client as ak
        monkeypatch.setattr(ak, "ths_limitup_reasons", lambda d: (_ for _ in ()).throw(RuntimeError("网络挂了")))
        monkeypatch.setattr(service.store, "prev_zbgc_codes", lambda d: set())
        out = service.get_candidate_pool("20260804")
        assert out["pool"]["低位连板接力"][0]["link"] is None
