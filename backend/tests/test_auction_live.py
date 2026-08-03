"""盘前竞价判据 metrics/auction_live.py 单测(纯函数,零网络)。"""

from daban_review.metrics import auction_live as al


def _prof(code, name, boards, seal=0.01):
    return {"code": code, "name": name, "boards": boards, "seal_strength": seal}


def _q(last_close=10.0, price=10.5, open_=10.4, amount=1e8, bid=100.0, ask=50.0):
    return {"last_close": last_close, "price": price, "open": open_,
            "amount": amount, "bid_vol1": bid, "ask_vol1": ask}


# ---------- pick_pool ----------

def test_pick_pool_lianban_all_shouban_topn():
    profs = [_prof(f"{i:06d}", f"连{i}", 2 + i % 3) for i in range(5)]  # 5 只连板
    profs += [_prof(f"9{i:05d}", f"首{i}", 1, seal=i / 1000) for i in range(20)]  # 20 只首板
    pool = al.pick_pool(profs, shouban_top=15)
    assert sum(1 for p in pool if p["boards"] >= 2) == 5   # 连板全取
    assert sum(1 for p in pool if p["boards"] == 1) == 15  # 首板只取 15
    # 首板按封流比降序取,最强的在
    seals = [p["seal_strength"] for p in pool if p["boards"] == 1]
    assert seals == sorted(seals, reverse=True)
    assert max(seals) == 0.019


def test_pick_pool_empty():
    assert al.pick_pool([]) == []


# ---------- live_rows:price vs open ----------

def test_bidding_phase_uses_price():
    rows = al.live_rows([_prof("000001", "甲", 2)], {"000001": _q(10.0, 10.5, 10.9)}, "bidding")
    assert rows[0]["gap_pct"] == 5.0   # 用 price 10.5 → +5%
    assert rows[0]["ref_price"] == 10.5


def test_opened_phase_uses_open():
    rows = al.live_rows([_prof("000001", "甲", 2)], {"000001": _q(10.0, 10.5, 10.9)}, "opened")
    assert rows[0]["gap_pct"] == 9.0   # 用 open 10.9 → +9%


def test_pre_cancel_also_uses_price():
    rows = al.live_rows([_prof("000001", "甲", 2)], {"000001": _q(10.0, 10.2, 11.0)}, "pre_cancel")
    assert rows[0]["gap_pct"] == 2.0


def test_row_skips_missing_quote_or_zero():
    pool = [_prof("000001", "甲", 2), _prof("000002", "乙", 2), _prof("000003", "丙", 2)]
    quotes = {"000001": _q(), "000002": _q(last_close=0)}  # 乙昨收0、丙无行情
    rows = al.live_rows(pool, quotes, "bidding")
    assert [r["code"] for r in rows] == ["000001"]


def test_rows_sorted_by_gap_desc_and_fields():
    pool = [_prof("000001", "甲", 3, 0.02), _prof("000002", "乙", 2)]
    quotes = {"000001": _q(10.0, 10.3), "000002": _q(10.0, 10.8)}
    rows = al.live_rows(pool, quotes, "bidding", themes={"000001": ["CPO"]},
                        candidate_codes={"000002"})
    assert [r["name"] for r in rows] == ["乙", "甲"]        # 8% 在前
    assert rows[1]["theme"] == ["CPO"] and rows[1]["prev_boards"] == 3
    assert rows[0]["in_candidates"] is True and rows[1]["in_candidates"] is False
    assert rows[0]["bid_ask_ratio"] == 2.0                  # bid100/ask50


def test_bid_ask_ratio_none_when_no_ask():
    rows = al.live_rows([_prof("000001", "甲", 2)], {"000001": _q(ask=0)}, "bidding")
    assert rows[0]["bid_ask_ratio"] is None


# ---------- 变化方向 ----------

def test_trend_up_down_flat_none():
    pool = [_prof("000001", "甲", 2)]
    # 首轮 price=10.2(+2%),现在 10.5(+5%)→ up
    series = {"000001": [{"ts": "09:20:00", "price": 10.2}, {"ts": "09:22:00", "price": 10.4}]}
    assert al.live_rows(pool, {"000001": _q(10.0, 10.5)}, "bidding", series)[0]["gap_trend"] == "up"
    # 首轮 +8%,现在 +5% → down
    series_d = {"000001": [{"ts": "09:20:00", "price": 10.8}]}
    assert al.live_rows(pool, {"000001": _q(10.0, 10.5)}, "bidding", series_d)[0]["gap_trend"] == "down"
    # 基本没变 → flat
    series_f = {"000001": [{"ts": "09:20:00", "price": 10.5}]}
    assert al.live_rows(pool, {"000001": _q(10.0, 10.5)}, "bidding", series_f)[0]["gap_trend"] == "flat"
    # 无历史 → none
    assert al.live_rows(pool, {"000001": _q(10.0, 10.5)}, "bidding", {})[0]["gap_trend"] == "none"


# ---------- 题材聚合 ----------

def test_theme_agg_strength_and_min_members():
    rows = [
        {"code": "1", "name": "a", "prev_boards": 3, "gap_pct": 6.0, "gap_trend": "up",
         "amount_yi": 1.0, "in_candidates": True, "theme": ["CPO", "算力"]},
        {"code": "2", "name": "b", "prev_boards": 2, "gap_pct": 4.0, "gap_trend": "up",
         "amount_yi": 0.5, "in_candidates": False, "theme": ["CPO"]},
        {"code": "3", "name": "c", "prev_boards": 1, "gap_pct": 9.0, "gap_trend": "flat",
         "amount_yi": 2.0, "in_candidates": False, "theme": ["独苗"]},
    ]
    agg = al.theme_agg(rows)
    names = [a["theme"] for a in agg]
    assert "独苗" not in names          # 单票题材被滤掉(不构成方向)
    assert "算力" not in names          # 同理单票
    cpo = next(a for a in agg if a["theme"] == "CPO")
    assert cpo["members"] == 2 and cpo["avg_gap"] == 5.0
    assert cpo["strength"] == 10.0      # 均高开 5 × 2 只
    assert cpo["max_board"] == 3 and cpo["amount_yi"] == 1.5
    assert [s["name"] for s in cpo["stocks"]] == ["a", "b"]  # 成员按高开降序


def test_theme_agg_ranks_group_over_single_hot():
    """3 只齐涨 4% 的题材,强度应高于 2 只涨 5% 的——一群票齐高开才是方向。"""
    rows = [{"code": str(i), "name": f"x{i}", "prev_boards": 2, "gap_pct": 4.0,
             "gap_trend": "up", "amount_yi": 1.0, "in_candidates": False, "theme": ["群体"]}
            for i in range(3)]
    rows += [{"code": f"y{i}", "name": f"y{i}", "prev_boards": 2, "gap_pct": 5.0,
              "gap_trend": "up", "amount_yi": 1.0, "in_candidates": False, "theme": ["小众"]}
             for i in range(2)]
    agg = al.theme_agg(rows)
    assert agg[0]["theme"] == "群体"    # 4×3=12 > 5×2=10


def test_theme_agg_empty():
    assert al.theme_agg([]) == []


# ---------- 竞价分级叠加 ----------

def test_grade_up_best_gap_with_volume_and_uptrend():
    row = {"gap_pct": 4.0, "amount_yi": 1.2, "gap_trend": "up"}  # +1+1+1 = 升 3 档
    r = al.auction_grade(row, "C")
    assert r["grade"] == "A+"
    assert any("最佳接力区" in n for n in r["notes"])


def test_grade_down_too_high_no_volume_downtrend():
    row = {"gap_pct": 9.0, "amount_yi": 0.1, "gap_trend": "down"}  # -1-1-1 = 降 3 档
    r = al.auction_grade(row, "A")
    assert r["grade"] == "D"
    assert any("溢价过高" in n for n in r["notes"])
    assert any("无量" in n for n in r["notes"])
    assert any("有人砸" in n for n in r["notes"])


def test_grade_low_gap_penalized():
    r = al.auction_grade({"gap_pct": 1.0, "amount_yi": 0.8, "gap_trend": "flat"}, "B")
    assert r["grade"] == "B"  # 高开不足 -1,量能达标 +1 → 抵消
    assert any("情绪偏弱" in n for n in r["notes"])


def test_grade_clamps_at_bounds():
    assert al.auction_grade({"gap_pct": 4.0, "amount_yi": 2.0, "gap_trend": "up"}, "A+")["grade"] == "A+"
    assert al.auction_grade({"gap_pct": 9.0, "amount_yi": 0.0, "gap_trend": "down"}, "D")["grade"] == "D"


def test_grade_low_gap_low_volume_not_double_punished():
    """高开不足且无量:量能罚只针对"高开却无量",低开不重复罚。"""
    r = al.auction_grade({"gap_pct": 0.5, "amount_yi": 0.05, "gap_trend": "none"}, "B")
    assert r["grade"] == "C"  # 只 -1(高开不足)
