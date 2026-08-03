"""拉取当日各涨停/跌停池,中文列名 → 英文,落库,返回 dict[str, DataFrame]。"""

import logging

import pandas as pd

from . import akshare_client as ak
from . import store

log = logging.getLogger(__name__)

# 各池:中文列 → 英文列(只保留需要的列)
COLMAP = {
    "limitup": {
        "代码": "code", "名称": "name", "涨跌幅": "pct", "最新价": "price",
        "成交额": "amount", "流通市值": "float_mv", "总市值": "total_mv",
        "换手率": "turnover", "封板资金": "seal_amount",
        "首次封板时间": "first_seal", "最后封板时间": "last_seal",
        "炸板次数": "break_times", "涨停统计": "zt_stat",
        "连板数": "boards", "所属行业": "industry",
    },
    "previous": {
        "代码": "code", "名称": "name", "涨跌幅": "pct", "换手率": "turnover",
        "昨日封板时间": "prev_seal", "昨日连板数": "prev_boards",
        "涨停统计": "zt_stat", "所属行业": "industry",
    },
    "zbgc": {
        "代码": "code", "名称": "name", "涨跌幅": "pct",
        "首次封板时间": "first_seal", "炸板次数": "break_times",
        "涨停统计": "zt_stat", "所属行业": "industry",
    },
    "dtgc": {
        "代码": "code", "名称": "name", "涨跌幅": "pct", "封单资金": "seal_amount",
        "最后封板时间": "last_seal", "连续跌停": "cont_dt",
        "开板次数": "open_times", "所属行业": "industry",
    },
}

_FETCHERS = {
    "limitup": ak.zt_pool,
    "previous": ak.zt_previous,
    "zbgc": ak.zt_zbgc,
    "dtgc": ak.zt_dtgc,
}

# 落库表名
TABLE = {k: f"daily_{k}" for k in _FETCHERS}


def _normalize(name: str, raw: pd.DataFrame) -> pd.DataFrame:
    cols = COLMAP[name]
    keep = [c for c in cols if c in raw.columns]
    df = raw[keep].rename(columns=cols)
    return df


def fetch_day(date: str, persist: bool = True) -> dict[str, pd.DataFrame]:
    """拉取指定交易日(YYYYMMDD)的四个池,归一化列名,可选落库。"""
    result: dict[str, pd.DataFrame] = {}
    conn = store.get_conn() if persist else None
    for name, fetcher in _FETCHERS.items():
        try:
            df = _normalize(name, fetcher(date))
        except Exception as e:  # noqa: BLE001
            log.error("拉取 %s(%s) 失败: %s", name, date, e)
            df = pd.DataFrame(columns=list(COLMAP[name].values()))
        result[name] = df
        if conn is not None and not df.empty:
            store.save_df(conn, TABLE[name], date, df)
    if conn is not None:
        conn.close()
    return result
