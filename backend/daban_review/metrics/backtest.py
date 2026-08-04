"""评分回测:把历史每日涨停池当候选全集,grade_candidate 打分 × 次日开盘溢价验证。

绕开 agent(不花 token),纯本地读库 + mootdx 日线。与「次日验证」同口径
(隔日开盘溢价 = 次日开盘 / 当日涨停收盘 − 1),用于校准 score.py 因子阈值。

聚合与相关性做成纯函数(可脱离 DB/网络单测);collect 负责取数。
"""

from __future__ import annotations

from typing import Callable

from ..data import akshare_client as ak
from ..data import fetch, store
from .emotion import compute_emotion
from .ladder import stock_profiles
from .score import _first_seal_minutes, grade_candidate


def _open_prem(df, base_date: str) -> float | None:
    """从一只票的日线 df 取隔日开盘溢价;次日未收盘或无数据返回 None。"""
    if df is None or df.empty:
        return None
    df = df.reset_index(drop=True)
    idx = df.index[df["date"] == base_date]
    if not len(idx) or idx[0] + 1 >= len(df):
        return None
    i = idx[0]
    base_close = float(df.iloc[i]["close"])
    if base_close <= 0:
        return None
    return round(float(df.iloc[i + 1]["open"]) / base_close - 1, 4)


def collect(dates: list[str] | None = None,
            daily_bars: Callable = ak.daily_bars) -> list[dict]:
    """回测样本:每条 = 一只涨停票在某日的画像因子 + 评级 + 次日开盘溢价。

    dates 为 None 时取库内全部有涨停池的交易日(除最末日,无次日)。
    daily_bars 可注入(测试用);对每只票的日线按 code 缓存,避免重复拉。
    """
    conn = store.get_conn()
    all_dates = sorted(
        r[0] for r in conn.execute("SELECT DISTINCT date FROM daily_limitup").fetchall()
    )
    if dates is None:
        dates = all_dates[:-1] if len(all_dates) > 1 else []

    cache: dict[str, object] = {}

    def bars(code: str):
        if code not in cache:
            try:
                cache[code] = daily_bars(code, 40)
            except Exception:  # noqa: BLE001 单票拉取失败不阻断整体回测
                cache[code] = None
        return cache[code]

    rows: list[dict] = []
    # 每日炸板名单:判「弱转强 = 前一交易日炸板、今日涨停」。在循环外一次读完,
    # 别在循环里调 store.prev_zbgc_codes —— 那会每天开一次连接。
    zb_by_date = {
        d: set(z["code"].astype(str))
        for d in all_dates
        if (z := store.read_df(conn, "daily_zbgc", d)) is not None and not z.empty
    }

    for i, date in enumerate(dates):
        pools = {n: store.read_df(conn, t, date) for n, t in fetch.TABLE.items()}
        if pools["limitup"].empty:
            continue
        phase = compute_emotion(pools).get("phase_hint", "未知")
        di = all_dates.index(date)
        prev_zb = zb_by_date.get(all_dates[di - 1], set()) if di > 0 else set()
        for p in stock_profiles(pools["limitup"]):
            prem = _open_prem(bars(p["code"]), date)
            if prem is None:
                continue
            w2s = p["code"] in prev_zb
            g = grade_candidate({**p, "w2s": w2s}, phase)
            rows.append({
                "date": date, "code": p["code"], "grade": g["grade"], "score": g["score"],
                "seal": float(p["seal_strength"] or 0), "fmin": _first_seal_minutes(p["first_seal"]),
                "breaks": int(p["break_times"] or 0), "turn": float(p["turnover"] or 0),
                "boards": int(p["boards"] or 0), "w2s": w2s, "phase": phase, "prem": prem,
            })
    conn.close()
    return rows


# ---- 纯聚合(可单测)----

def agg(sub: list[dict]) -> dict | None:
    """一组样本的 n / 胜率 / 平均溢价 / 中位溢价。"""
    n = len(sub)
    if not n:
        return None
    ps = sorted(r["prem"] for r in sub)
    return {
        "n": n,
        "win": round(sum(1 for x in ps if x > 0) / n, 4),
        "avg": round(sum(ps) / n, 4),
        "med": ps[n // 2],
    }


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (vx * vy) if vx and vy else float("nan")


def _rank(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return float("nan")
    return pearson(_rank(xs), _rank(ys))


def summarize(rows: list[dict]) -> dict:
    """结构化汇总:by_grade / by_phase / by_boards / by_w2s / corr。供程序化使用或渲染。

    by_w2s 单列出来是为了**每次回测都复核弱转强这个因子** —— 它进 score.py 时只有
    n=27(p=0.0136),偏薄;样本随交易日累积,不单列就没人会去看它是否还成立。
    对照组要用「同板位」而不是全样本:弱转强票几乎全是首板(26/27)。
    """
    def by(key: str, values) -> dict:
        return {v: agg([r for r in rows if r[key] == v])
                for v in values if agg([r for r in rows if r[key] == v])}

    xs = [r["score"] for r in rows]
    ys = [r["prem"] for r in rows]
    return {
        "n": len(rows),
        "dates": sorted({r["date"] for r in rows}),
        "by_grade": by("grade", ["A+", "A", "B", "C", "D"]),
        "by_phase": by("phase", ["高潮", "发酵", "修复", "分歧", "冰点", "退潮", "未知"]),
        "by_boards": {b: agg([r for r in rows if r["boards"] == b])
                      for b in sorted({r["boards"] for r in rows})
                      if agg([r for r in rows if r["boards"] == b])},
        # 弱转强 vs 同板位对照(只比 1 板,弱转强 26/27 是首板,拿全样本比会高估)
        "by_w2s": {
            k: a for k, a in (
                ("弱转强", agg([r for r in rows if r.get("w2s")])),
                ("1板对照", agg([r for r in rows if not r.get("w2s") and r["boards"] == 1])),
            ) if a
        },
        "pearson": pearson(xs, ys),
        "spearman": spearman(xs, ys),
    }


def format_report(rows: list[dict]) -> str:
    """把汇总渲染成命令行文本表。"""
    if not rows:
        return "无可回测样本(库里需≥2 个有涨停池的交易日,且次日已收盘)。先跑 fetch 累积数据。"
    s = summarize(rows)
    out = [f"评分回测:{s['n']} 样本 / {len(s['dates'])} 交易日 "
           f"({s['dates'][0]}..{s['dates'][-1]}),隔日开盘溢价口径\n"]

    def line(label, a):
        return f"  {label:<10}{a['n']:>6}{a['win']:>8.0%}{a['avg']:>10.2%}{a['med']:>9.2%}"

    out.append("按评级:")
    out.append(f"  {'grade':<10}{'n':>6}{'胜率':>8}{'平均溢价':>10}{'中位':>9}")
    for g, a in s["by_grade"].items():
        out.append(line(g, a))

    out.append("\n按情绪周期:")
    out.append(f"  {'phase':<10}{'n':>6}{'胜率':>8}{'平均溢价':>10}{'中位':>9}")
    for ph, a in s["by_phase"].items():
        out.append(line(ph, a))

    out.append("\n按连板身位(n<3 略):")
    out.append(f"  {'boards':<10}{'n':>6}{'胜率':>8}{'平均溢价':>10}{'中位':>9}")
    for b, a in s["by_boards"].items():
        if a["n"] >= 3:
            out.append(line(f"{b}板", a))

    if s["by_w2s"]:
        out.append("\n弱转强(昨炸板今涨停,对照组=同为首板的其余票):")
        out.append(f"  {'':<10}{'n':>6}{'胜率':>8}{'平均溢价':>10}{'中位':>9}")
        for k, a in s["by_w2s"].items():
            out.append(line(k, a))
        w = s["by_w2s"].get("弱转强")
        if w and w["n"] < 40:
            out.append(f"  ⚠️ 样本仅 {w['n']} 条,进 score.py 时是 27 条(p=0.0136),攒到 ~40 条再复核阈值")

    out.append(f"\nscore ↔ 隔日溢价:  Pearson={s['pearson']:+.3f}   Spearman={s['spearman']:+.3f}")
    return "\n".join(out)
