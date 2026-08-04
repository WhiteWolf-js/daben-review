"""SQLite(WAL)落库:每日一份快照,按 date 覆盖写,历史累积供算晋级率/情绪序列。"""

import datetime as dt
import json
import sqlite3

import pandas as pd

from ..config import CONFIG


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or CONFIG.db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def save_df(conn: sqlite3.Connection, table: str, date: str, df: pd.DataFrame) -> int:
    """把某日某表的 DataFrame 落库(先删该 date 的旧数据再写),返回写入行数。"""
    out = df.copy()
    out.insert(0, "date", date)
    if _table_exists(conn, table):
        conn.execute(f"DELETE FROM {table} WHERE date=?", (date,))
    out.to_sql(table, conn, if_exists="append", index=False)
    conn.commit()
    return len(out)


def read_df(conn: sqlite3.Connection, table: str, date: str) -> pd.DataFrame:
    if not _table_exists(conn, table):
        return pd.DataFrame()
    return pd.read_sql_query(f"SELECT * FROM {table} WHERE date=?", conn, params=(date,))


# ---- 盘中实时监控:watcher 写、API 只读,经此表解耦两进程 ----

def _ensure_live(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS live_snapshot ("
        "date TEXT PRIMARY KEY, payload TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS live_events ("
        "date TEXT, ts TEXT, type TEXT, title TEXT, detail TEXT, key TEXT, "
        "UNIQUE(date, key))"
    )
    conn.commit()


def save_live(date: str, snapshot: dict, index_state: dict | None = None,
              events: list[dict] | None = None) -> None:
    """盘中每轮写:覆盖当日实时快照 + 追加命中事件(按 key 当日去重)。

    只依赖 SQLite,不引 agent/指标层——watcher 进程因此无需加载 Claude SDK。
    """
    zt = int(snapshot.get("zt_count", 0))
    zbgc = int(snapshot.get("zbgc_count", 0))
    base = zt + zbgc
    lim = snapshot.get("limitup", {})
    hot = [{"code": c, "name": lim.get(c, {}).get("name", "")} for c in snapshot.get("hot_top5", [])]
    payload = {
        "ts": snapshot.get("ts", ""),
        "zt_count": zt,
        "zbgc_count": zbgc,
        "lianban_count": int(snapshot.get("lianban_count", 0)),
        "max_board": int(snapshot.get("max_board", 0)),
        "break_rate": round(zbgc / base, 4) if base else 0.0,
        "hot_top5": hot,
        "index": index_state or {},
    }
    conn = get_conn()
    _ensure_live(conn)
    conn.execute(
        "INSERT OR REPLACE INTO live_snapshot(date, payload, updated_at) VALUES(?,?,?)",
        (date, json.dumps(payload, ensure_ascii=False),
         dt.datetime.now().isoformat(timespec="seconds")),
    )
    for ev in events or []:
        conn.execute(
            "INSERT OR IGNORE INTO live_events(date, ts, type, title, detail, key) "
            "VALUES(?,?,?,?,?,?)",
            (date, payload["ts"], ev.get("type", ""), ev.get("title", ""),
             ev.get("detail", ""), ev.get("key", "")),
        )
    conn.commit()
    conn.close()


def get_live() -> dict:
    """前端只读:今日实时快照 + 最近事件(倒序);running = 快照 3 分钟内有更新。"""
    date = dt.date.today().strftime("%Y%m%d")
    conn = get_conn()
    _ensure_live(conn)
    row = conn.execute(
        "SELECT payload, updated_at FROM live_snapshot WHERE date=?", (date,)
    ).fetchone()
    evs = conn.execute(
        "SELECT ts, type, title, detail FROM live_events WHERE date=? ORDER BY rowid DESC LIMIT 30",
        (date,),
    ).fetchall()
    conn.close()

    snapshot, updated_at, running = None, None, False
    if row:
        snapshot = json.loads(row[0]) if row[0] else None
        updated_at = row[1]
        try:
            running = (dt.datetime.now() - dt.datetime.fromisoformat(row[1])).total_seconds() < 180
        except (ValueError, TypeError):
            running = False
    return {
        "date": date,
        "running": running,
        "updated_at": updated_at,
        "snapshot": snapshot,
        "events": [{"ts": e[0], "type": e[1], "title": e[2], "detail": e[3]} for e in evs],
    }


# ---- 盘前竞价快照序列:存每轮撮合价,才能算 9:20→9:25 的变化方向(抢筹在加 or 有人砸) ----

def _ensure_auction(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS auction_snapshot ("
        "date TEXT, ts TEXT, code TEXT, price REAL, amount REAL, "
        "bid_vol REAL, ask_vol REAL, UNIQUE(date, ts, code))"
    )
    conn.commit()


def save_auction_snapshot(date: str, ts: str, quotes: dict[str, dict]) -> None:
    """记一轮竞价快照(ts=HH:MM:SS)。同轮重复写按 UNIQUE 忽略。"""
    if not quotes:
        return
    conn = get_conn()
    _ensure_auction(conn)
    conn.executemany(
        "INSERT OR IGNORE INTO auction_snapshot(date, ts, code, price, amount, bid_vol, ask_vol) "
        "VALUES(?,?,?,?,?,?,?)",
        [
            (date, ts, code, q.get("price", 0), q.get("amount", 0),
             q.get("bid_vol1", 0), q.get("ask_vol1", 0))
            for code, q in quotes.items()
        ],
    )
    conn.commit()
    conn.close()


def read_auction_series(date: str) -> dict[str, list[dict]]:
    """读当日竞价快照序列 {code: [{ts, price, amount}...]}(按 ts 升序)。"""
    conn = get_conn()
    _ensure_auction(conn)
    rows = conn.execute(
        "SELECT code, ts, price, amount FROM auction_snapshot WHERE date=? ORDER BY ts", (date,)
    ).fetchall()
    conn.close()
    out: dict[str, list[dict]] = {}
    for code, ts, price, amount in rows:
        out.setdefault(code, []).append({"ts": ts, "price": price, "amount": amount})
    return out


# ---- 弱转强判据用:前一交易日 + 当日炸板名单 ----

def prev_trade_date(date: str) -> str | None:
    """库里比 date 更早的最近一个有涨停池的交易日;没有返回 None。"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT MAX(date) FROM daily_limitup WHERE date < ?", (date,)).fetchone()
    except Exception:  # noqa: BLE001 表还没建时当作没有
        row = None
    conn.close()
    return row[0] if row and row[0] else None


def zbgc_codes(date: str) -> set[str]:
    """某日炸板池的代码集合;取不到返回空集(调用方据此退化为不给弱转强加分)。"""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT code FROM daily_zbgc WHERE date=?", (date,)).fetchall()
    except Exception:  # noqa: BLE001
        rows = []
    conn.close()
    return {str(r[0]) for r in rows if r and r[0]}


def prev_zbgc_codes(date: str) -> set[str]:
    """前一交易日的炸板名单 —— 「弱转强 = 昨炸板今涨停」的判据。"""
    prev = prev_trade_date(date)
    return zbgc_codes(prev) if prev else set()


# ---- 盘中切换(intraday_rotation):板块分时曲线缓存 ----

def _ensure_rotation(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS intraday_rotation ("
        "date TEXT PRIMARY KEY, json TEXT, created_at TEXT)"
    )
    conn.commit()


def save_rotation(date: str, payload: dict) -> None:
    """存当日盘中切换结果(整块 JSON)。重算覆盖旧的。"""
    conn = get_conn()
    _ensure_rotation(conn)
    conn.execute(
        "INSERT OR REPLACE INTO intraday_rotation(date, json, created_at) VALUES(?,?,?)",
        (date, json.dumps(payload, ensure_ascii=False), dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def read_rotation(date: str) -> dict | None:
    """读缓存;没有返回 None。历史交易日的分时永不变,所以算一次就够(一次要拉 200+ 只分时)。"""
    conn = get_conn()
    _ensure_rotation(conn)
    row = conn.execute("SELECT json FROM intraday_rotation WHERE date=?", (date,)).fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except ValueError:
        return None


# ---- 全 A 股票名录(stock_names):名称 ↔ 代码,持仓截图只有名称时反查用 ----

def _ensure_stock_names(conn: sqlite3.Connection) -> None:
    """名录表。**主键是 name**(用途是名称→代码反查)。

    一开始拿 code 当主键,结果同一 code 的名称变体(除权期的「XD兴业股份」与「兴业股份」)
    互相覆盖,6437 条落库只剩 6348 条 —— 名称变体正是反查最需要留的东西。
    老结构的表直接丢掉重建(数据随时可重拉)。
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='stock_names'"
    ).fetchone()
    if row and "name TEXT PRIMARY KEY" not in (row[0] or ""):
        conn.execute("DROP TABLE stock_names")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS stock_names ("
        "name TEXT PRIMARY KEY, code TEXT, updated_at TEXT)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_names_code ON stock_names(code)")
    conn.commit()


def save_stock_names(name_to_code: dict[str, str]) -> int:
    """落库全 A 名录(整表替换)。传空 dict 不动库——拉取失败时别把已有名录清了。"""
    if not name_to_code:
        return 0
    import datetime as dt

    now = dt.datetime.now().isoformat(timespec="seconds")
    conn = get_conn()
    _ensure_stock_names(conn)
    conn.execute("DELETE FROM stock_names")
    conn.executemany(
        "INSERT OR REPLACE INTO stock_names(name, code, updated_at) VALUES(?,?,?)",
        [(name, code, now) for name, code in name_to_code.items()],
    )
    conn.commit()
    conn.close()
    return len(name_to_code)


def load_stock_names(max_age_days: int = 7) -> dict[str, str]:
    """读库里的全 A 名录 → {名称: 代码}。

    超过 max_age_days 视为过期返回 {}(让调用方重拉)。新股上市/更名不频繁,一周一次够;
    真要立刻刷新用 akshare_client.stock_name_map(force=True)。
    """
    import datetime as dt

    conn = get_conn()
    _ensure_stock_names(conn)
    rows = conn.execute("SELECT name, code, updated_at FROM stock_names").fetchall()
    conn.close()
    if not rows:
        return {}
    newest = max((r[2] or "") for r in rows)
    try:
        age = (dt.datetime.now() - dt.datetime.fromisoformat(newest)).days
    except ValueError:
        return {}
    if age > max_age_days:
        return {}
    return {r[0]: r[1] for r in rows if r[0] and r[1]}


def stock_names_meta() -> dict:
    """名录状态(条数 + 更新时间),给自检脚本/接口看。"""
    conn = get_conn()
    _ensure_stock_names(conn)
    row = conn.execute("SELECT COUNT(*), MAX(updated_at) FROM stock_names").fetchone()
    conn.close()
    return {"count": row[0] or 0, "updated_at": row[1] or ""}


# ---- agent 调用成本(usage_log):每次复盘/持仓分析记一行,供单次显示 + 当日累计 ----

def _ensure_usage(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS usage_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, kind TEXT, code TEXT, "
        "input_tokens INTEGER, output_tokens INTEGER, cache_read INTEGER, cache_write INTEGER, "
        "cost_usd REAL, cost_cny REAL, created_at TEXT)"
    )
    conn.commit()


def save_usage(date: str, kind: str, cost: dict, code: str = "") -> None:
    """记一次调用用量。cost 为 pricing.compute_cost 的返回 dict;kind ∈ review/chat/holding/ocr。"""
    conn = get_conn()
    _ensure_usage(conn)
    conn.execute(
        "INSERT INTO usage_log(date, kind, code, input_tokens, output_tokens, cache_read, "
        "cache_write, cost_usd, cost_cny, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (date, kind, code, cost.get("input_tokens", 0), cost.get("output_tokens", 0),
         cost.get("cache_read", 0), cost.get("cache_write", 0),
         cost.get("cost_usd", 0.0), cost.get("cost_cny", 0.0),
         dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_usage_today(kinds: tuple[str, ...] = ("review", "holding", "ocr")) -> dict:
    """今日累计(按本地自然日;默认统复盘 + 持仓分析 + 持仓截图识别)。"""
    today = dt.date.today().isoformat()  # YYYY-MM-DD,对齐 created_at 前 10 位
    conn = get_conn()
    _ensure_usage(conn)
    ph = ",".join("?" * len(kinds))
    row = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(cost_usd),0), COALESCE(SUM(cost_cny),0), "
        f"COALESCE(SUM(input_tokens+output_tokens+cache_read+cache_write),0) "
        f"FROM usage_log WHERE substr(created_at,1,10)=? AND kind IN ({ph})",
        (today, *kinds),
    ).fetchone()
    conn.close()
    return {"count": row[0], "cost_usd": round(row[1], 4),
            "cost_cny": round(row[2], 4), "total_tokens": int(row[3])}
