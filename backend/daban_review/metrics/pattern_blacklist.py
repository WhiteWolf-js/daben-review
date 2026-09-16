"""缩量→次日问题(炸板/低开/一字)模式黑名单。

候选池规则化的硬排除项:历史反复出现「缩量涨停后次日炸板/低开/一字」的票,
客观上不具备接力价值(量化票特征:缩量锁筹 + 竞价挂大单,次日要么进不去要么被埋),
不进候选池。原料全部本地:daily_limitup 历史 + daily_bars 量能 + ladder.is_yizi 判据。

扫一次落库(pattern_blacklist 表),候选池构建时只读缓存,不重扫几百次 daily_bars。
"""

from __future__ import annotations

from typing import Callable

from ..data import akshare_client as ak
from ..data import store
from . import kline
from .backtest import _open_prem  # 次日开盘溢价口径同源(复用,不另写一份)
from .ladder import is_yizi

SHRINK_VR = 0.8            # vr < 此值 = 缩量(口径同 kline._tag 的「缩量涨停」)
PATTERN_WINDOW_DAYS = 30   # 扫近 N 个有涨停池的交易日
PATTERN_MIN_HITS = 2       # 缩量后次日问题出现 ≥ 此值 → 拉黑


def _next_day_bad(code: str, date: str, npool: dict[str, dict], bars) -> bool:
    """缩量票的次日是否「有问题」:炸板 / 一字 / 低开。

    - 次日继续涨停:炸板(break_times>0)或一字(is_yizi,买不到)→ 问题;
      继续强势封板不算(那不是缩量该担心的走法)。
    - 次日未涨停:低开(次日 open < 当日 close)才算问题;高开/平开不究。
    """
    nrow = npool.get(code)
    if nrow:
        bt = int(nrow["break_times"])
        if bt > 0:
            return True
        return is_yizi(nrow["first_seal"], bt)
    prem = _open_prem(bars(code), date)
    return prem is not None and prem < 0


def scan_shrinkage_patterns(
    today: str,
    window: int = PATTERN_WINDOW_DAYS,
    daily_bars: Callable = ak.daily_bars,
) -> set[str]:
    """近 window 个有涨停池的交易日里,缩量涨停后次日出现(炸板|低开|一字)≥ MIN_HITS 的 code 集合。

    流程(复用 backtest.collect 的 bars 缓存范式):
    1. 读 daily_limitup 全部日期,取 today 往前 window 个(不含 today,今日可能未收盘)
    2. 每日涨停池每只票 → kline.volume_ratio(df=bars) 判缩量(vr < SHRINK_VR)
    3. 缩量票查次日:见 ``_next_day_bad``
    4. 累计 ≥ MIN_HITS → 进黑名单

    daily_bars 可注入(测试用);按 code 缓存,一只票只拉一次 40 根日线,vr 与次日溢价都从它取。
    """
    conn = store.get_conn()
    try:
        all_dates = sorted(
            r[0] for r in conn.execute("SELECT DISTINCT date FROM daily_limitup").fetchall()
        )
    finally:
        conn.close()
    scan_dates = [d for d in all_dates if d < today][-window:]
    if len(scan_dates) < 2:
        return set()

    # 缩量判定日 + 各自次日(次日可能在 scan_dates 外,如窗口最后一天的次日)
    needed: set[str] = set(scan_dates)
    for d in scan_dates:
        di = all_dates.index(d)
        if di + 1 < len(all_dates):
            needed.add(all_dates[di + 1])

    conn = store.get_conn()
    pools: dict[str, dict[str, dict]] = {}
    for d in needed:
        df = store.read_df(conn, "daily_limitup", d)
        pools[d] = {} if (df is None or df.empty) else {
            str(r["code"]): {
                "first_seal": str(r.get("first_seal", "")),
                "break_times": int(r.get("break_times") or 0),
                "price": float(r.get("price") or 0),
            }
            for _, r in df.iterrows()
        }
    conn.close()

    cache: dict[str, object] = {}

    def bars(code: str):
        if code not in cache:
            try:
                cache[code] = daily_bars(code, 40)
            except Exception:  # noqa: BLE001 单票拉取失败不阻断整体扫描
                cache[code] = None
        return cache[code]

    hits: dict[str, int] = {}
    for d in scan_dates:
        di = all_dates.index(d)
        next_date = all_dates[di + 1] if di + 1 < len(all_dates) else None
        npool = pools.get(next_date, {}) if next_date else {}
        for code in pools[d]:
            vr = kline.volume_ratio(code, d, df=bars(code))
            if vr is None or vr >= SHRINK_VR:
                continue  # 不缩量,跳过
            if _next_day_bad(code, d, npool, bars):
                hits[code] = hits.get(code, 0) + 1
    return {c for c, n in hits.items() if n >= PATTERN_MIN_HITS}


def get_blacklist(today: str, refresh: bool = False) -> set[str]:
    """读黑名单缓存;无缓存(或 refresh=True)则同步 scan 一次并落库。

    refresh=False(候选池构建用):有缓存直接读;首次无缓存会同步扫一次(盘后可接受,
    之后当日复跑都走缓存)。refresh=True:强制重算落库,复盘前主动刷新用。
    """
    if not refresh:
        cached = store.read_blacklist(today)
        if cached is not None:
            return cached
    codes = scan_shrinkage_patterns(today)
    store.save_blacklist(today, codes)
    return codes
