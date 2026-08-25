"""业务服务:生成/存取复盘报告与情绪指标,供 REST 与定时任务复用。"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable

from ..agent.runner import load_pools, run_review
from ..data import store
from ..metrics import build_ladder, compute_emotion

log = logging.getLogger(__name__)


def _ensure_tables(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS review_report ("
        "date TEXT PRIMARY KEY, markdown TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS emotion_metrics ("
        "date TEXT PRIMARY KEY, metrics TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS candidates ("
        "date TEXT, style TEXT, code TEXT, name TEXT, "
        "trigger_cond TEXT, giveup_cond TEXT, reason TEXT, "
        "grade TEXT, position TEXT, score INTEGER, reasons TEXT)"
    )
    # 旧表补列(已存在的库);重复列忽略
    _cols = (
        ("grade", "TEXT"), ("position", "TEXT"), ("score", "INTEGER"), ("reasons", "TEXT"),
        ("next_date", "TEXT"), ("open_prem", "REAL"), ("close_prem", "REAL"),  # 次日验证
        # 候选池约束(agent 只能在池内选):池内名次、触发价算式、是否越出池外
        ("pool_rank", "INTEGER"), ("price_ref", "TEXT"), ("in_pool", "INTEGER"),
    )
    for col, typ in _cols:
        try:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {col} {typ}")
        except Exception:  # noqa: BLE001 列已存在
            pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS holdings ("
        "code TEXT PRIMARY KEY, name TEXT, buy_date TEXT, buy_price REAL, "
        "buy_boards INTEGER, shares INTEGER, note TEXT, created_at TEXT)"
    )
    try:  # 旧库补列(截图导入带来的持仓股数);已存在则忽略
        conn.execute("ALTER TABLE holdings ADD COLUMN shares INTEGER")
    except Exception:  # noqa: BLE001
        pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS holding_analysis ("
        "code TEXT PRIMARY KEY, analysis_date TEXT, markdown TEXT, verdict TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS auction_brief ("
        "date TEXT PRIMARY KEY, brief TEXT, created_at TEXT)"
    )
    conn.commit()


# 四风格顺序(展示与排序用)
CANDIDATE_STYLES = ["低位连板接力", "首板打板", "题材情绪龙头", "高位龙头接力"]


def _int_or_none(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _extract_candidates(markdown: str) -> list[dict]:
    """从复盘 markdown 尾部提取 agent 输出的 ```json 候选数组;解析失败返回 []。"""
    blocks = re.findall(r"```json\s*(.*?)```", markdown, re.DOTALL)
    if not blocks:
        return []
    try:
        data = json.loads(blocks[-1].strip())
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for it in data:
        if not isinstance(it, dict):
            continue
        code = str(it.get("code", "")).strip()
        if not code:
            continue
        out.append({
            "style": str(it.get("style", "")).strip(),
            "code": code,
            "name": str(it.get("name", "")).strip(),
            "trigger": str(it.get("trigger", "")).strip(),
            "giveup": str(it.get("giveup", "")).strip(),
            "reason": str(it.get("reason", "")).strip(),
            "pool_rank": _int_or_none(it.get("pool_rank")),
            "price_ref": str(it.get("price_ref", "")).strip(),
        })
    return out


def get_emotion(date: str) -> dict:
    """实时算当日情绪(读库快),不依赖是否已生成报告。"""
    pools = load_pools(date)
    return compute_emotion(pools)


def get_ladder(date: str) -> dict:
    pools = load_pools(date)
    return {str(k): v for k, v in build_ladder(pools["limitup"]).items()}


_prev_trade_date = store.prev_trade_date  # 与弱转强判据共用同一份取数,别在这里再写一遍


def get_ladder_board(date: str) -> dict:
    """天梯图数据:各档封住的票 + 昨日连板今日断板的票 + 行业分布(供 LadderPoster 出图)。

    格子里的「所属板块」用**当天真形成板块效应的题材**(≥2 只涨停)而非行业 ——
    行业是静态分类且会误导(美利云恒为 IT服务Ⅱ,实际连板靠算力租赁)。
    断板票今天没涨停原因,用昨日的补(见 `ladder.cell_sector` 的四级回退)。
    题材/热度榜任一步失败都只是退化成显示行业,不该让天梯整个挂掉。
    """
    from ..data import akshare_client as ak
    from ..metrics import ladder_board, theme_heat

    pools = load_pools(date)
    themes: dict[str, list[str]] = {}
    prev_themes: dict[str, list[str]] = {}
    hot: list[str] = []
    try:
        themes = ak.ths_limitup_reasons(date)
        # 取全部 ≥2 只的题材(不是面板的 top12)——否则四成格子找不到归属。
        # **这里按家数排,不按身位**:身位排序有自指偏差 —— 题材的「最高板」往往就是这只票
        # 自己,于是 7 板票会把自己的小众题材顶成第一名(实测传智教育被标成「具身智能」
        # 而非「AI教育」、通宇通讯被标成「商业航天」而非「CPO」)。
        # chip 问的是「它有多少同伴」,厚度才是答案;面板问「今天主线是什么」才用身位。
        hot = [t["theme"] for t in theme_heat(pools, themes, top=9999)]
        pd_ = _prev_trade_date(date)
        if pd_:
            prev_themes = ak.ths_limitup_reasons(pd_)
    except Exception as e:  # noqa: BLE001
        log.warning("天梯题材归属拉取失败(退化为显示行业): %s", e)

    return ladder_board(pools, themes=themes, prev_themes=prev_themes, hot_themes=hot)


_POOL_GRADES = ("A+", "A")


def get_candidate_pool(date: str, grades: tuple[str, ...] = _POOL_GRADES) -> dict:
    """四风格候选池的**完整备选**(默认只留 A 级以上),每只附板块联动。纯规则、零 token。

    为什么要这个:前端「明日候选」读的是 `candidates` 表,那张表只存 agent 写进正文的
    rank1,于是池里 rank2-5 的 A 级票全被藏起来(实测 0804 低位连板接力 5 只全是 A 级以上)。

    ⚠️ **`theme_rank` 输入必须与 `runner.run_review` 完全一致(`theme_heat` 默认 top=12)**,
    否则前端显示的池子和 agent 当时看到的不是同一个 —— 题材榜大小会改变 `theme_rank`,
    进而改变 `_unplayable`(换手<1% 且无主线归属沉池尾)的判定。实测传 top=9999 时
    欣天科技(换手0.55%)从池尾浮成 rank1,和生产口径的池子完全不同。踩过。

    板块联动取**身位最强**的题材(最高板 → 连板数 → 涨停家数),与 `_theme_ranks` 同口径:
    泛业绩标签(中报预增 13只但仅 1 连)家数最多却不是主线,按家数取会盖掉真方向。
    """
    from ..data import akshare_client as ak
    from ..metrics import build_candidate_pool, compute_emotion, theme_heat

    pools = load_pools(date)
    if pools.get("limitup") is None or pools["limitup"].empty:
        return {"date": date, "phase": "未知", "pool": {}}

    emotion = compute_emotion(pools)
    try:
        themes = ak.ths_limitup_reasons(date)
    except Exception as e:  # noqa: BLE001 题材拉不到只是没有联动信息,不该让池子出不来
        log.warning("候选池题材拉取失败(无联动信息): %s", e)
        themes = {}

    heat_prod = theme_heat(pools, themes)                    # 生产口径 top12,喂给池子
    heat_all = theme_heat(pools, themes, top=9999)           # 全量,仅用于查联动读数
    by_theme = {t["theme"]: t for t in heat_all}
    built = build_candidate_pool(pools, emotion, themes, heat_prod,
                                 prev_zbgc=store.prev_zbgc_codes(date))

    def _link(item: dict) -> dict | None:
        """该票身位最强的成板块题材 + 家数/连板数/最高板;全是单票碎片则 None(孤票)。"""
        cand = [t for t in (item.get("theme") or []) if t in by_theme]
        if not cand:
            return None
        best = max(cand, key=lambda t: (by_theme[t]["max_board"], by_theme[t]["lianban_count"],
                                        by_theme[t]["zt_count"]))
        h = by_theme[best]
        return {"theme": best, "zt_count": h["zt_count"], "lianban_count": h["lianban_count"],
                "max_board": h["max_board"], "pct": h.get("pct")}

    keep = {"code", "name", "boards", "grade", "score", "position", "rank", "price",
            "seal_strength", "turnover", "break_times", "first_seal", "last_seal",
            "theme_rank", "w2s", "passive", "reasons"}
    out: dict[str, list[dict]] = {}
    for style, items in built.get("pool", {}).items():
        out[style] = [
            {**{k: v for k, v in it.items() if k in keep}, "link": _link(it)}
            for it in items if it["grade"] in grades
        ]
    return {"date": date, "phase": built.get("phase", "未知"), "pool": out}


def get_intraday_rotation(date: str) -> dict:
    """盘中情绪切换(板块分时曲线 + 退潮/接棒配对)。**吃缓存**。

    算一次要拉 200+ 只分时(0731 实测 14s),但历史交易日的分时永不变 → 落库复用。
    只有 date 是今天才绕过缓存(盘中曲线还在长)。
    """
    import datetime as dt

    from ..metrics.intraday_rotation import build_rotation

    today = dt.date.today().strftime("%Y%m%d")
    if date != today:
        cached = store.read_rotation(date)
        if cached:
            return cached

    out = build_rotation(load_pools(date), date)
    if date != today and out.get("fetched"):  # 今天的别存(还会变);一只都没取到也别存
        store.save_rotation(date, out)
    return out


def list_dates(recent: int = 22) -> list[str]:
    """可选日期 = 最近约 1 个月交易日 ∪ 库里已存日期(倒序)。

    交易日历用个股日线(mootdx)取,天然只含「已收盘」交易日——今天盘前/盘中不会出现
    (规避 akshare 涨停池对未收盘日返回上一交易日顶替的幽灵重复);收盘后自动纳入今天。
    用户选中库里没有的历史交易日时,load_pools 会按需实时拉取入库。
    """
    conn = store.get_conn()
    try:
        rows = conn.execute("SELECT DISTINCT date FROM daily_limitup").fetchall()
    except Exception:
        rows = []
    conn.close()
    have = {r[0] for r in rows}

    recent_days: set[str] = set()
    try:
        from ..data import akshare_client as ak

        cal = ak.daily_bars("000001", recent)  # 平安银行常年交易,date 列 YYYYMMDD
        if not cal.empty:
            recent_days = set(cal["date"].tolist())
    except Exception:  # noqa: BLE001 交易日历拉取失败时回退到库里已有日期
        pass

    return sorted(have | recent_days, reverse=True)


def get_report(date: str) -> dict | None:
    conn = store.get_conn()
    _ensure_tables(conn)
    row = conn.execute(
        "SELECT markdown, created_at FROM review_report WHERE date=?", (date,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"date": date, "markdown": row[0], "created_at": row[1]}


def save_report(date: str, markdown: str) -> None:
    import datetime as dt

    conn = store.get_conn()
    _ensure_tables(conn)
    conn.execute(
        "INSERT OR REPLACE INTO review_report(date, markdown, created_at) VALUES(?,?,?)",
        (date, markdown, dt.datetime.now().isoformat(timespec="seconds")),
    )
    # 算一次:情绪(存 metrics)、周期(打分基准)、个股画像(打分因子来源)、候选池(校验 agent 有没有越界)
    from ..agent.runner import load_pools
    from ..data import akshare_client as ak
    from ..metrics import build_candidate_pool, compute_emotion, pool_codes, theme_heat
    from ..metrics.ladder import stock_profiles
    from ..metrics.score import grade_candidate

    pools = load_pools(date)
    emotion = compute_emotion(pools)
    phase = emotion.get("phase_hint", "未知")
    # 标弱转强 + 被动上板度 —— 必须与候选池/回测同口径,否则同一只票两处分级会不一致
    prev_zb = store.prev_zbgc_codes(date)
    _profs = stock_profiles(pools["limitup"])
    try:
        from ..metrics import theme_heat
        from ..metrics.ladder import passive_map
        _th = ak.ths_limitup_reasons(date)
        _pv = passive_map(_profs, _th, [t["theme"] for t in theme_heat(pools, _th, top=9999)])
    except Exception as e:  # noqa: BLE001 题材拉不到只是少这个因子,不该阻塞报告落库
        log.warning("被动上板度计算跳过(%s)", e)
        _pv = {}
    profiles = {
        p["code"]: {**p, "w2s": p["code"] in prev_zb, "passive": _pv.get(p["code"])}
        for p in _profs
    }

    conn.execute(
        "INSERT OR REPLACE INTO emotion_metrics(date, metrics) VALUES(?,?)",
        (date, json.dumps(emotion, ensure_ascii=False)),
    )

    # 与 runner 起 agent 时同一套规则重算池,用于判定候选是否出自池内(池外票=agent 违规,标记出来)
    try:
        themes = ak.ths_limitup_reasons(date)
        codes_by_style = pool_codes(
            build_candidate_pool(pools, emotion, themes, theme_heat(pools, themes))
        )
    except Exception as e:  # noqa: BLE001 题材拉取失败不该阻塞报告落库
        log.warning("候选池校验跳过(%s)", e)
        codes_by_style = {}

    cands = _extract_candidates(markdown)
    rows = []
    for c in cands:
        prof = profiles.get(c["code"])
        g = grade_candidate(prof, phase) if prof else {"grade": "", "position": "", "score": None, "reasons": []}
        allowed = codes_by_style.get(c["style"])
        in_pool = 1 if (allowed is None or c["code"] in allowed) else 0  # 无池信息时不判违规
        if in_pool == 0:
            log.warning("候选越出池外:%s %s(%s) 不在「%s」池内", date, c["name"], c["code"], c["style"])
        rows.append((
            date, c["style"], c["code"], c["name"], c["trigger"], c["giveup"], c["reason"],
            g["grade"], g["position"], g["score"], json.dumps(g["reasons"], ensure_ascii=False),
            c.get("pool_rank"), c.get("price_ref"), in_pool,
        ))
    conn.execute("DELETE FROM candidates WHERE date=?", (date,))
    conn.executemany(
        "INSERT INTO candidates(date, style, code, name, trigger_cond, giveup_cond, reason, "
        "grade, position, score, reasons, pool_rank, price_ref, in_pool) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def candidate_outcome(code: str, base_date: str) -> dict | None:
    """候选次日验证:隔日溢价 = 次日开盘/当日收盘(涨停价)−1。

    次日尚未开盘返回 None。close_prem 仅次日 15:00 后才填入，盘中返回 None 避免锁入脏数据。
    """
    import datetime as _dt
    from ..data.akshare_client import daily_bars

    try:
        d = daily_bars(code, 12)
    except Exception:  # noqa: BLE001
        return None
    if d is None or d.empty:
        return None
    d = d.reset_index(drop=True)
    idx = d.index[d["date"] == base_date]
    if not len(idx) or idx[0] + 1 >= len(d):
        return None
    i = idx[0]
    base_close = float(d.iloc[i]["close"])
    if base_close <= 0:
        return None
    nxt = d.iloc[i + 1]
    next_date = str(nxt["date"])
    today = _dt.date.today().strftime("%Y%m%d")
    now = _dt.datetime.now()
    next_closed = next_date < today or (
        next_date == today and now.hour * 60 + now.minute >= 15 * 60
    )
    return {
        "next_date": next_date,
        "open_prem": round(float(nxt["open"]) / base_close - 1, 4),
        "close_prem": round(float(nxt["close"]) / base_close - 1, 4) if next_closed else None,
    }


def get_candidates(date: str) -> list[dict]:
    """读某日结构化候选票(按四风格排序);次日已收盘则懒加载算隔日溢价并回存。"""
    conn = store.get_conn()
    _ensure_tables(conn)
    rows = conn.execute(
        "SELECT rowid, style, code, name, trigger_cond, giveup_cond, reason, grade, position, score, "
        "reasons, next_date, open_prem, close_prem, pool_rank, price_ref, in_pool "
        "FROM candidates WHERE date=? ORDER BY rowid",
        (date,),
    ).fetchall()
    out = []
    for r in rows:
        rowid, open_prem, close_prem, next_date = r[0], r[12], r[13], r[11]
        if open_prem is None:  # 未验证过 → 尝试算次日溢价
            oc = candidate_outcome(r[2], date)
            if oc:
                next_date, open_prem, close_prem = oc["next_date"], oc["open_prem"], oc["close_prem"]
                conn.execute(
                    "UPDATE candidates SET next_date=?, open_prem=?, close_prem=? WHERE rowid=?",
                    (next_date, open_prem, close_prem, rowid),
                )
        elif close_prem is None and next_date:  # open_prem 已有但 close_prem 未落（盘中写的）→ 补算
            oc = candidate_outcome(r[2], date)
            if oc and oc["close_prem"] is not None:
                close_prem = oc["close_prem"]
                conn.execute(
                    "UPDATE candidates SET close_prem=? WHERE rowid=?",
                    (close_prem, rowid),
                )
        out.append({
            "style": r[1], "code": r[2], "name": r[3], "trigger": r[4], "giveup": r[5], "reason": r[6],
            "grade": r[7] or "", "position": r[8] or "", "score": r[9],
            "reasons": json.loads(r[10]) if r[10] else [],
            "next_date": next_date, "open_prem": open_prem, "close_prem": close_prem,
            "pool_rank": r[14], "price_ref": r[15] or "",
            "in_pool": True if r[16] is None else bool(r[16]),  # 老数据无此列 → 不显示违规
        })
    conn.commit()
    conn.close()
    order = {s: i for i, s in enumerate(CANDIDATE_STYLES)}
    out.sort(key=lambda c: order.get(c["style"], len(order)))
    return out


def get_candidates_stats() -> dict:
    """滚动命中率:对所有已验证候选(有隔日溢价的),按评级分组统计胜率与平均开盘溢价。"""
    conn = store.get_conn()
    _ensure_tables(conn)
    rows = conn.execute(
        "SELECT grade, open_prem FROM candidates WHERE open_prem IS NOT NULL"
    ).fetchall()
    conn.close()

    def agg(prems: list[float]) -> dict:
        n = len(prems)
        return {
            "n": n,
            "win_rate": round(sum(1 for p in prems if p > 0) / n, 4) if n else 0.0,
            "avg_open_prem": round(sum(prems) / n, 4) if n else 0.0,
        }

    by_grade: dict[str, list[float]] = {}
    for grade, prem in rows:
        by_grade.setdefault(grade or "?", []).append(prem)
    return {
        "by_grade": {g: agg(ps) for g, ps in by_grade.items()},
        "overall": agg([p for ps in by_grade.values() for p in ps]),
    }


def emotion_series(limit: int = 40) -> list[dict]:
    """情绪指标时间序列(供趋势图)。覆盖所有有涨停池的日期:已存 emotion_metrics 直接读,
    未生成过报告的日期当场 compute_emotion 补算(读库快)。"""
    conn = store.get_conn()
    _ensure_tables(conn)
    cached = {
        d: json.loads(m)
        for d, m in conn.execute("SELECT date, metrics FROM emotion_metrics").fetchall()
    }
    dates = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT date FROM daily_limitup ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    ]
    conn.close()
    out = []
    for date in reversed(dates):  # 升序,供折线从左到右
        m = cached.get(date)
        if m is None:
            try:
                m = get_emotion(date)
            except Exception:  # noqa: BLE001 单日数据缺失不阻断整条序列
                continue
        out.append({
            "date": date,
            "zt_count": m.get("zt_count"),
            "lianban_count": m.get("lianban_count"),
            "max_board": m.get("max_board"),
            "break_rate": m.get("break_rate"),
            "promo_overall": m.get("promo_overall"),
            "money_effect": m.get("money_effect"),
        })
    return out


async def generate(date: str, on_text: Callable[[str], None] | None = None) -> str:
    """跑 agent 复盘,存库,返回 markdown。定时任务与手动生成共用。"""
    markdown = await run_review(date, on_text=on_text)
    if markdown.strip():
        save_report(date, markdown)
    return markdown


def _intraday_profile(code: str, date: str) -> dict | None:
    """该票当日的资金面画像,给分时弹窗看强弱:封单强度/封板资金/首末封/炸板/换手/成交额。

    从涨停池取(source=limitup);不在涨停池就查炸板池(source=zbgc,没有封单金额,只有首封与炸板次数)。
    两个池都没有(普通票)返回 None,前端就只画分时不显示这行。
    **必须由接口返回而不是靠前端传**:分时弹窗的调用方五花八门(天梯格子有封流比、持仓列表和
    候选表只有 code/name),靠 props 传会一半有一半没有。
    """
    import pandas as pd

    from ..metrics.ladder import stock_profiles

    try:
        pools = load_pools(date)
    except Exception as e:  # noqa: BLE001 分时是主体,画像拿不到不该让弹窗失败
        log.warning("分时画像:池子读取失败 %s", e)
        return None

    lim = pools.get("limitup")
    if lim is not None and not lim.empty:
        prof = next((p for p in stock_profiles(lim) if p["code"] == code), None)
        if prof:
            row = lim[lim["code"].astype(str) == code]
            amount = float(pd.to_numeric(row.iloc[0].get("amount"), errors="coerce") or 0) if len(row) else 0.0
            float_mv = float(pd.to_numeric(row.iloc[0].get("float_mv"), errors="coerce") or 0) if len(row) else 0.0
            return {
                "source": "limitup",
                "boards": prof["boards"],
                "zt_stat": prof["zt_stat"],
                "seal_strength": prof["seal_strength"],  # 封流比 = 封板资金 / 流通市值
                "seal_amount": prof["seal_amount"],
                "first_seal": prof["first_seal"],
                "last_seal": prof["last_seal"],
                "break_times": prof["break_times"],
                "turnover": prof["turnover"],
                "amount": amount,
                "float_mv": float_mv,
                "industry": prof["industry"],
            }

    zb = pools.get("zbgc")
    if zb is not None and not zb.empty:
        row = zb[zb["code"].astype(str) == code]
        if len(row):
            r = row.iloc[0]
            return {
                "source": "zbgc",  # 炸板票:没封住,故无封单金额/封流比
                "boards": 0,
                "zt_stat": str(r.get("zt_stat") or ""),
                "seal_strength": None,
                "seal_amount": None,
                "first_seal": str(r.get("first_seal") or ""),
                "last_seal": "",
                "break_times": int(pd.to_numeric(r.get("break_times"), errors="coerce") or 0),
                "turnover": None,
                "amount": None,
                "float_mv": None,
                "industry": str(r.get("industry") or ""),
            }
    return None


def get_intraday(code: str, date: str) -> dict:
    """个股当日分时(收盘价 + 量序列 + 昨收参考线 + 当日资金画像),供前端画分时图。"""
    from ..data import akshare_client as ak

    df = ak.stock_intraday_min(code, date)
    prev = None
    d = ak.daily_bars(code, 8)
    if not d.empty:
        d = d.reset_index(drop=True)
        ix = d.index[d["date"] == date]
        if len(ix) and ix[0] > 0:
            prev = round(float(d.iloc[ix[0] - 1]["close"]), 2)
    profile = _intraday_profile(code, date)
    if df.empty:
        return {"code": code, "prev_close": prev, "points": [], "profile": profile}
    points = [{"t": r["time"], "c": float(r["close"]), "v": float(r["vol"])} for _, r in df.iterrows()]
    return {"code": code, "prev_close": prev, "points": points, "profile": profile}


def get_auction(date: str) -> list[dict]:
    """竞价高开榜(复用 metrics.auction_board)。"""
    from ..agent.runner import load_pools
    from ..metrics.auction import auction_board

    return auction_board(load_pools(date), date)


def _auction_phase(now=None) -> str:
    """竞价时段判定:pre_cancel(9:15–9:20 可撤单,数据不可信)/ bidding(9:20–9:25 不可撤)
    / opened(9:25–9:30 已定格)/ closed(其余,显示当日开盘结果)。"""
    import datetime as dt

    t = (now or dt.datetime.now()).time()
    if dt.time(9, 15) <= t < dt.time(9, 20):
        return "pre_cancel"
    if dt.time(9, 20) <= t < dt.time(9, 25):
        return "bidding"
    if dt.time(9, 25) <= t < dt.time(9, 30):
        return "opened"
    return "closed"


def _prev_trade_date(today: str) -> str | None:
    """上一交易日 = 库里 daily_limitup 中 date < today 的最大值(盘前当日池还不存在)。"""
    conn = store.get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(date) FROM daily_limitup WHERE date < ?", (today,)
        ).fetchone()
    except Exception:  # noqa: BLE001 表不存在
        row = None
    conn.close()
    return row[0] if row and row[0] else None


def get_auction_live() -> dict:
    """盘前竞价决策台:上一交易日连板+首板强票的实时竞价高开/量能/趋势 + 题材聚合 + 分级。

    题材在上(定方向)、票在下(选标的)。竞价时段顺带存快照序列,供算 9:20→9:25 变化方向。
    """
    import datetime as dt

    from ..agent.runner import load_pools
    from ..data import akshare_client as ak
    from ..metrics import auction_live as al
    from ..metrics import compute_emotion
    from ..metrics import theme_heat as al_theme_heat
    from ..metrics.ladder import stock_profiles
    from ..metrics.score import grade_candidate

    now = dt.datetime.now()
    today = now.strftime("%Y%m%d")
    phase = _auction_phase(now)
    prev = _prev_trade_date(today)
    if not prev:
        return {"phase": phase, "base_date": None, "themes": [], "rows": [],
                "note": "库里没有历史涨停池,先复盘一天再用"}

    pools = load_pools(prev)
    # 竞价台的底分是「昨日画像分」,弱转强与被动上板度都要按**昨日**那天算
    prev_zb = store.prev_zbgc_codes(prev)
    _profs = stock_profiles(pools["limitup"])
    try:
        from ..metrics.ladder import passive_map
        _th_prev = ak.ths_limitup_reasons(prev)
        _pv = passive_map(_profs, _th_prev, [t["theme"] for t in al_theme_heat(pools, _th_prev, top=9999)])
    except Exception:  # noqa: BLE001
        _pv = {}
    profiles = [{**p, "w2s": p["code"] in prev_zb, "passive": _pv.get(p["code"])} for p in _profs]
    pool = al.pick_pool(profiles)
    quotes = ak.realtime_quotes([p["code"] for p in pool])

    # 9:20 后才存快照(9:15–9:20 可撤单,虚单不入序列)
    if phase in ("bidding", "opened"):
        try:
            store.save_auction_snapshot(today, now.strftime("%H:%M:%S"), quotes)
        except Exception as e:  # noqa: BLE001 落库失败不影响看盘
            print(f"竞价快照落库失败: {e}")

    series = store.read_auction_series(today) if phase in ("bidding", "opened") else {}
    themes = ak.ths_limitup_reasons(prev)
    cand_codes = {c["code"] for c in get_candidates(prev)}
    rows = al.live_rows(pool, quotes, phase, series, themes, cand_codes)

    # 分级:昨日画像分(封流比/首封/炸板/换手/身位 + 情绪周期)叠加今日竞价维度
    phase_hint = compute_emotion(pools).get("phase_hint", "未知")
    prof_by_code = {p["code"]: p for p in profiles}
    for r in rows:
        base = grade_candidate(prof_by_code.get(r["code"], {}), phase_hint)
        g = al.auction_grade(r, base.get("grade", "B"))
        r["grade"] = g["grade"]
        r["notes"] = base.get("reasons", []) + g["notes"]

    return {
        "phase": phase,
        "base_date": prev,
        "ts": now.strftime("%H:%M:%S"),
        "emotion_phase": phase_hint,
        "themes": al.theme_agg(rows),
        "rows": rows,
    }


# ---- 盘前 agent 解读(brief):出图时生成,前端盘前视图读 ----

def save_auction_brief(date: str, brief: str) -> None:
    """存当日盘前解读(出海报时顺带存,供前端展示;同日覆盖)。"""
    import datetime as dt

    if not brief.strip():
        return
    conn = store.get_conn()
    _ensure_tables(conn)
    conn.execute(
        "INSERT OR REPLACE INTO auction_brief(date, brief, created_at) VALUES(?,?,?)",
        (date, brief, dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_auction_brief(date: str) -> dict | None:
    """读当日盘前解读;未生成返回 None。"""
    conn = store.get_conn()
    _ensure_tables(conn)
    row = conn.execute(
        "SELECT brief, created_at FROM auction_brief WHERE date=?", (date,)
    ).fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    return {"date": date, "brief": row[0], "created_at": row[1]}


def get_theme_heat(date: str) -> list[dict]:
    """题材热度榜(同花顺涨停原因聚合),供前端展示当日炒作主线。

    附板块涨跌强度(同花顺涨停板块榜,与涨停原因同源、按 date 取当日,历史日期也准)。
    """
    from ..agent.runner import load_pools
    from ..data import akshare_client as ak
    from ..metrics import theme_heat

    # order=position:按身位(最高板/连板数/涨停数)排,不按涨停家数 —— 家数排序会把
    # 「中报预增(13只/1连)」「超跌反弹(12只/0连)」这类泛标签顶到前排,它们是标签不是方向。
    # 注意只改这里(面板),不动 theme_heat 的默认口径,那个是 agent 的输入。
    return theme_heat(
        load_pools(date), ak.ths_limitup_reasons(date), quotes=ak.concept_quotes(date),
        order="position",
    )


def refresh_day(date: str) -> dict:
    """强制重拉当日各池并覆盖入库(盘中行情在变,绕过 load_pools 的库优先缓存)。"""
    from ..data.fetch import fetch_day

    pools = fetch_day(date, persist=True)
    return {"date": date, "counts": {k: len(v) for k, v in pools.items()}}


def get_live() -> dict:
    """盘中实时快照 + 事件流(watcher 写库,前端只读)。薄封装 store.get_live。"""
    return store.get_live()


def record_usage(date: str, kind: str, cost: dict, code: str = "") -> None:
    """记一次 agent 调用成本(薄封装 store.save_usage)。"""
    store.save_usage(date, kind, cost, code)


def get_usage_today() -> dict:
    """今日 agent 成本累计(复盘 + 持仓分析)。"""
    return store.get_usage_today()


# ---- 持仓分析(已打板买入 → 走势 + 买卖点)----

def add_holding(code: str, name: str, buy_date: str, buy_price: float,
                buy_boards: int = 0, note: str = "", shares: int = 0) -> None:
    """新增/更新一条打板持仓(code 唯一,重复即覆盖——补仓后成本价会变)。"""
    import datetime as dt

    conn = store.get_conn()
    _ensure_tables(conn)
    conn.execute(
        "INSERT OR REPLACE INTO holdings(code, name, buy_date, buy_price, buy_boards, shares, note, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (code, name, buy_date, float(buy_price), int(buy_boards or 0), int(shares or 0), note,
         dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def add_holdings_bulk(items: list[dict]) -> int:
    """批量新增/更新持仓(截图导入用)。跳过无 code 或无成本价的行,返回实际写入条数。"""
    n = 0
    for it in items or []:
        code = str(it.get("code") or "").strip()
        price = it.get("buy_price")
        if not code or price in (None, ""):
            continue
        add_holding(
            code=code,
            name=str(it.get("name") or "").strip(),
            buy_date=str(it.get("buy_date") or "").strip(),
            buy_price=float(price),
            buy_boards=int(it.get("buy_boards") or 0),
            note=str(it.get("note") or "").strip(),
            shares=int(it.get("shares") or 0),
        )
        n += 1
    return n


def delete_holding(code: str) -> None:
    conn = store.get_conn()
    _ensure_tables(conn)
    conn.execute("DELETE FROM holdings WHERE code=?", (code,))
    conn.execute("DELETE FROM holding_analysis WHERE code=?", (code,))
    conn.commit()
    conn.close()


def list_holdings() -> list[dict]:
    """持仓列表,附最新价与盈亏%(最新价=mootdx 日线最近一根收盘)。"""
    from ..data.akshare_client import daily_bars

    conn = store.get_conn()
    _ensure_tables(conn)
    rows = conn.execute(
        "SELECT code, name, buy_date, buy_price, buy_boards, note, shares "
        "FROM holdings ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    out = []
    for code, name, buy_date, buy_price, buy_boards, note, shares in rows:
        cur = None
        try:
            d = daily_bars(code, 3)
            if d is not None and not d.empty:
                cur = round(float(d.iloc[-1]["close"]), 2)
        except Exception:  # noqa: BLE001
            pass
        pnl_pct = round((cur / buy_price - 1) * 100, 2) if cur and buy_price else None
        shares = int(shares or 0)  # 老数据/手动录入没填股数 → 0,金额类字段给 None
        out.append({
            "code": code, "name": name, "buy_date": buy_date, "buy_price": buy_price,
            "buy_boards": buy_boards, "note": note, "cur_price": cur, "pnl_pct": pnl_pct,
            "shares": shares,
            "market_value": round(cur * shares, 2) if cur and shares else None,
            "pnl_amount": round((cur - buy_price) * shares, 2) if cur and shares and buy_price else None,
        })
    return out


def ocr_holdings(image_b64: str, media_type: str = "image/png", date: str = "") -> dict:
    """持仓截图 → 候选持仓行(供前端勾选)。返回 {rows, usage}。

    识别只给「截图里有的」(名称/代码/股数/成本价/现价/盈亏%);这里再补四样系统自己查得到的:
      code       截图没有代码列时(券商 App 很常见)按**股票名称反查**全 A 名称表,
                 并标 code_from="name" 让前端提示核对;识别自带代码时 code_from="image"
      exists     该 code 是否已在持仓(前端标「将覆盖」)
      buy_boards 当日涨停池里的连板数(复用 ladder.stock_profiles),查不到给 0
      buy_date   默认取 date(通常=今天),前端可改
    识别用量按 kind="ocr" 落 usage_log,与复盘/持仓分析同一个成本面板口径。
    """
    import datetime as dt

    from ..agent import pricing, vision
    from ..data.akshare_client import code_by_name

    date = date or dt.date.today().strftime("%Y%m%d")
    rows, usage = vision.extract_holdings(image_b64, media_type)

    # 截图无代码列 → 按名称反查(名称表本身按日缓存,不会每行都拉)
    for r in rows:
        r["code_from"] = "image" if r["code"] else ""
        if not r["code"] and r["name"]:
            try:
                found = code_by_name(r["name"])
            except Exception as e:  # noqa: BLE001 名称表挂了不该让整次识别失败
                log.warning("名称反查代码失败(%s):%s", r["name"], e)
                found = ""
            if found:
                r["code"], r["code_from"] = found, "name"

    cost = pricing.compute_cost(usage)
    try:
        record_usage(date, "ocr", cost)
    except Exception as e:  # noqa: BLE001 计费落库失败不该让识别结果丢掉
        log.warning("识别用量落库失败:%s", e)

    conn = store.get_conn()
    _ensure_tables(conn)
    held = {r[0] for r in conn.execute("SELECT code FROM holdings").fetchall()}
    conn.close()

    # 买入板数:从当日涨停池取。拉不到(非交易日/数据未落库)就整体降级为 0,不阻断识别结果。
    boards_map: dict[str, int] = {}
    try:
        from ..metrics.ladder import stock_profiles

        boards_map = {p["code"]: p["boards"] for p in stock_profiles(load_pools(date)["limitup"])}
    except Exception as e:  # noqa: BLE001
        log.warning("补买入板数失败(%s),置 0", e)

    for r in rows:
        r["exists"] = r["code"] in held
        r["buy_boards"] = boards_map.get(r["code"], 0)
        r["buy_date"] = date
    return {"rows": rows, "usage": cost}


def _holding_info(codes: list[str]) -> list[dict]:
    """取若干持仓的成本/板位(按传入顺序返回,库里没有的跳过)。"""
    codes = [str(c).strip() for c in (codes or []) if str(c).strip()]
    if not codes:
        return []
    conn = store.get_conn()
    _ensure_tables(conn)
    ph = ",".join("?" * len(codes))
    rows = conn.execute(
        f"SELECT code, name, buy_price, buy_boards, shares FROM holdings WHERE code IN ({ph})",
        codes,
    ).fetchall()
    conn.close()
    by_code = {
        r[0]: {"code": r[0], "name": r[1], "buy_price": r[2], "buy_boards": r[3], "shares": r[4] or 0}
        for r in rows
    }
    return [by_code[c] for c in codes if c in by_code]


def _extract_holding_verdict(markdown: str, code: str) -> dict:
    """从持仓分析 markdown 尾部 json 取该 code 的结构化结论(verdict/买卖点)。"""
    blocks = re.findall(r"```json\s*(.*?)```", markdown, re.DOTALL)
    if not blocks:
        return {}
    try:
        data = json.loads(blocks[-1].strip())
    except (json.JSONDecodeError, ValueError):
        return {}
    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict) and str(it.get("code", "")) == code:
                return it
        return data[0] if data and isinstance(data[0], dict) else {}
    return data if isinstance(data, dict) else {}


def _save_holding_analysis(codes: list[str], date: str, markdown: str) -> None:
    """把一次分析的结果存给参与的每只票。

    多票一起分析产出的是**一篇**含全部票的 markdown,这里给每个 code 各存一行:markdown 相同,
    verdict 按 code 从尾部 json 里各取自己那项。这样 HoldingsList / 单票视图的读取逻辑不用变
    (代价是 markdown 重复几份,一篇几 KB,可接受)。
    """
    import datetime as dt

    now = dt.datetime.now().isoformat(timespec="seconds")
    conn = store.get_conn()
    _ensure_tables(conn)
    conn.executemany(
        "INSERT OR REPLACE INTO holding_analysis(code, analysis_date, markdown, verdict, created_at) "
        "VALUES(?,?,?,?,?)",
        [
            (c, date, markdown,
             json.dumps(_extract_holding_verdict(markdown, c), ensure_ascii=False), now)
            for c in codes
        ],
    )
    conn.commit()
    conn.close()


async def analyze_holdings(codes: list[str], date: str, on_text: Callable[[str], None] | None = None,
                           on_usage: Callable[[dict], None] | None = None) -> str:
    """对一只或多只持仓跑 agent 走势/买卖点分析,结果存 holding_analysis。

    多只一起跑比逐只跑更省钱也更准:大盘情绪/题材/热门票 K 线这些上下文只拉一次,
    且 agent 能横向比较(谁该先减、谁还能拿),这正是持仓管理要的。
    """
    info = _holding_info(codes)
    if not info:
        if on_text:
            on_text("选中的持仓不存在,请先添加。")
        return ""
    from ..agent.runner import run_holding

    markdown = await run_holding(info, date, on_text=on_text, on_usage=on_usage)
    if markdown.strip():
        _save_holding_analysis([h["code"] for h in info], date, markdown)
    return markdown


def get_holding_analysis(code: str) -> dict | None:
    conn = store.get_conn()
    _ensure_tables(conn)
    r = conn.execute(
        "SELECT analysis_date, markdown, verdict, created_at FROM holding_analysis WHERE code=?", (code,)
    ).fetchone()
    conn.close()
    if not r:
        return None
    return {
        "code": code, "analysis_date": r[0], "markdown": r[1],
        "verdict": json.loads(r[2]) if r[2] else {}, "created_at": r[3],
    }
