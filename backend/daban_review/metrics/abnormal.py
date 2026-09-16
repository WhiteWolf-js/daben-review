"""N 日累计涨幅异动榜:把窗口内涨停/炸板过的票按累计涨幅排出来,标翻倍/两倍/进入异动。

其余 metrics 全是「当日截面」(谁今天涨停、几板),看不出一只票这 10 天一共涨了多少。
用户做高位接力时要的是后者 —— 10 日翻倍/两倍的票,以及正在冲进异动区的票,这才是
「高位票」的候选池。涨停池/天梯只给今天封住的那批,已断板但累计涨幅巨大的票看不见。

## 口径(踩过的方向,别改)

- **universe = 最近 N 个交易日涨停池 ∪ 炸板池的代码并集**。10 日能翻倍的票这段窗口里必然
  出现过涨停(否则累积不到 100%),所以取这个并集不会漏目标;且数量可控(几百只),
  不必扫全 A 6000 只日线(mootdx 串行十几分钟)。
- **累计涨幅 = 今收 / window 个交易日前那根的收盘 - 1**。mootdx 日线**未复权**,除权日会假跳;
  短期内涨停票除权罕见,面板标「未除权」提示,可接受。别为复权引入新依赖。
- **tier**:triple(≥200%) / double(≥100%) / entering(60–99% 且当日涨) / warm(其余)。
  entering 要「当日涨幅>0」才算「正在冲进异动区」,否则只算 warm —— 一只横盘的老妖不算进入。
- **历史日永不变 → 落库复用**(service 层负责)。一只都没拉到(fetched=0)不落缓存。
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from ..data import akshare_client as ak
from ..data import store

log = logging.getLogger(__name__)

# tier 阈值
_DOUBLE = 1.00   # 累计 ≥100% → 翻倍
_TRIPLE = 2.00   # 累计 ≥200% → 两倍
_ENTER_LO = 0.60  # 60% 起算「进入异动区」


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _window_stats(closes: list[float], window: int) -> dict:
    """从一段收盘价(老→新)算窗口累计涨幅 / 今日涨幅 / 实际窗口。

    不足 window+1 根时,用最早可那根做基准并回填 actual_window(纯函数,单测直接喂 list)。
    """
    closes = [c for c in closes if c is not None and c > 0]
    if not closes:
        return {"pct_window": 0.0, "pct_today": 0.0, "price": 0.0, "actual_window": 0}
    price = closes[-1]
    # 基准:尽量取 window 根之前那根;不够就用第一根,actual_window 如实回填
    base_idx = max(0, len(closes) - 1 - window)
    actual_window = len(closes) - 1 - base_idx
    base = closes[base_idx]
    pct_window = (price / base - 1.0) if base > 0 else 0.0
    pct_today = (price / closes[-2] - 1.0) if len(closes) >= 2 and closes[-2] > 0 else 0.0
    return {
        "pct_window": round(pct_window, 4),
        "pct_today": round(pct_today, 4),
        "price": round(price, 2),
        "actual_window": actual_window,
    }


def _tier(pct_window: float, pct_today: float) -> str:
    if pct_window >= _TRIPLE:
        return "triple"
    if pct_window >= _DOUBLE:
        return "double"
    if pct_window >= _ENTER_LO and pct_today > 0:
        return "entering"
    return "warm"


def _recent_trade_dates(date: str, n: int) -> list[str]:
    """库里 ≤ date 的最近 n 个有涨停池数据的交易日(降序)。取不到返回 []。"""
    conn = store.get_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT date FROM daily_limitup WHERE date <= ? ORDER BY date DESC LIMIT ?",
            (date, n),
        ).fetchall()
    except Exception:  # noqa: BLE001 表没建
        rows = []
    conn.close()
    return [r[0] for r in rows if r and r[0]]


def _universe_with_meta(date: str, window: int) -> dict[str, dict]:
    """最近 window 个交易日涨停池 ∪ 炸板池的代码 → 最新一次出现的 name/industry/boards/pct/price。

    boards(连板高度)取该票最近一次涨停那天的值;炸板池无 boards → 0。只涨停/炸板过但
    已断板的票也会被收进来(它们的累计涨幅往往最大),这正是本榜要看而涨停池截面看不到的。
    """
    dates = _recent_trade_dates(date, window)
    if not dates:
        return {}
    placeholders = ",".join("?" * len(dates))
    conn = store.get_conn()
    code_meta: dict[str, dict] = {}
    for table, has_boards in (("daily_limitup", True), ("daily_zbgc", False)):
        try:
            rows = conn.execute(
                f"SELECT code, name, industry, boards, pct, price, date FROM {table} "
                f"WHERE date IN ({placeholders}) ORDER BY date DESC",
                dates,
            ).fetchall()
        except Exception:  # noqa: BLE001 表没建时跳过
            rows = []
        for code, name, industry, boards, pct, price, d in rows:
            if not code:
                continue
            c = str(code)
            if c not in code_meta:  # ORDER BY date DESC,先命中=最近那天
                code_meta[c] = {
                    "code": c,
                    "name": str(name) if name else "",
                    "industry": str(industry) if industry else "",
                    "boards": int(_num(boards)) if has_boards else 0,
                    "pct_today_pool": round(_num(pct), 2),
                    "price_pool": round(_num(price), 2),
                }
    conn.close()
    return code_meta


def build_abnormal_rank(
    date: str,
    window: int = 10,
    *,
    fetch_bars=None,
    universe: dict[str, dict] | None = None,
) -> dict:
    """构建 N 日累计涨幅异动榜。

    返回 {date, window, fetched, updated_at, rows:[{code,name,price,pct_today,pct_window,
    boards,industry,tier,actual_window}]}。rows 按 pct_window 降序。
    """
    if fetch_bars is None:
        fetch_bars = ak.daily_bars
    meta = universe if universe is not None else _universe_with_meta(date, window)

    # 当日涨停原因(题材),能给则给,断板票拿不到就空
    themes_map: dict[str, list[str]] = {}
    try:
        themes_map = ak.ths_limitup_reasons(date)
    except Exception:  # noqa: BLE001 同花顺接口偶发失败,不阻塞
        log.warning("ths_limitup_reasons 取失败,themes 置空")

    rows: list[dict] = []
    fetched = 0
    for code, m in meta.items():
        try:
            df = fetch_bars(code, window + 1)
        except Exception:  # noqa: BLE001 单股失败不阻塞整榜
            df = None
        if df is None or len(df) == 0:
            continue
        fetched += 1
        closes = pd.to_numeric(df["close"], errors="coerce").tolist()
        st = _window_stats(closes, window)
        rows.append({
            "code": code,
            "name": m["name"],
            "price": st["price"],
            "pct_today": st["pct_today"],
            "pct_window": st["pct_window"],
            "boards": m["boards"],
            "industry": m["industry"],
            "themes": themes_map.get(code, []),
            "tier": _tier(st["pct_window"], st["pct_today"]),
            "actual_window": st["actual_window"],
        })

    rows.sort(key=lambda x: x["pct_window"], reverse=True)
    return {
        "date": date,
        "window": window,
        "fetched": fetched,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
    }
