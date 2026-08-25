"""连板梯队与个股画像原料(封单强度/首封时间/炸板/行业),供前端天梯图与 agent 属性归因。"""

from __future__ import annotations

import re

import pandas as pd


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def stock_profiles(limitup: pd.DataFrame) -> list[dict]:
    """把涨停池每只票整理成画像 dict,含封单强度(封板资金/流通市值)。"""
    out: list[dict] = []
    for _, r in limitup.iterrows():
        float_mv = _num(r.get("float_mv"))
        seal_amount = _num(r.get("seal_amount"))
        seal_strength = round(seal_amount / float_mv, 4) if float_mv else 0.0
        out.append({
            "code": str(r.get("code")),
            "name": str(r.get("name")),
            "boards": int(_num(r.get("boards"))),
            "pct": round(_num(r.get("pct")), 2),
            "price": round(_num(r.get("price")), 2),  # 当日收盘=涨停价,供次日触发价推算

            "seal_amount": seal_amount,
            "seal_strength": seal_strength,  # 封单/流通市值,越大封得越结实
            "first_seal": str(r.get("first_seal")),
            "last_seal": str(r.get("last_seal")),
            "break_times": int(_num(r.get("break_times"))),
            "turnover": round(_num(r.get("turnover")), 2),
            "zt_stat": str(r.get("zt_stat")),
            "industry": str(r.get("industry")),
        })
    return out


def build_ladder(limitup: pd.DataFrame) -> dict[int, list[dict]]:
    """按连板数分组的天梯:{板级: [个股画像...]},板级从高到低。"""
    profiles = stock_profiles(limitup)
    ladder: dict[int, list[dict]] = {}
    for p in profiles:
        ladder.setdefault(p["boards"], []).append(p)
    # 每档内按封单强度降序
    for b in ladder:
        ladder[b].sort(key=lambda x: x["seal_strength"], reverse=True)
    return dict(sorted(ladder.items(), key=lambda kv: kv[0], reverse=True))


# ---- 天梯图(含炸板票 + 行业分布),供 LadderPoster 出图 ----

def _seal_minutes(first_seal) -> int | None:
    """首封时间 '092500' / '09:25:00' → 当日分钟数;解析不了返回 None。"""
    digits = "".join(ch for ch in str(first_seal) if ch.isdigit())
    if len(digits) < 4:
        return None
    hh, mm = int(digits[:2]), int(digits[2:4])
    return hh * 60 + mm if 0 <= hh <= 23 and 0 <= mm <= 59 else None


# 集合竞价即涨停(≤9:25)= 一字板
_YIZI_MIN = 9 * 60 + 25
INDUSTRY_MIN_COUNT = 3  # 行业分布里低于此数的并进「其他」


# 只画「昨日≥2板今日断板」的票:昨日首板今日断板每天几十只、无信息量,画上去会淹掉 2 板档
BROKEN_MIN_PREV_BOARDS = 2

# 判「涨幅是否已到涨停」时留的舍入余量:涨停价按分四舍五入,同日实测出现过
# 9.98 / 9.99 / 10.01 / 10.08 都是涨停价
LIMIT_EPS = 0.15


def _limit_pct(code: str) -> float:
    """该票当日涨跌幅限制(%)。**必须按板块取**,一刀切 9.9 会把 20cm 判错。

    ST 不再单列:沪深主板风险警示股涨跌幅 **2026-07-06 起由 5% 调为 10%**,与主板普通股一致
    (2026-04-24 三大交易所发布修订规则);创业板/科创板 ST 本来就是 20%、北交所 30%。
    所以限制纯粹由板块决定,和是否戴帽无关。

    已知边界:库内 20260703 这一天还属旧规(主板 ST 5%),仅此一天,不做特殊处理。
    """
    c = str(code)
    if c.startswith(("30", "688")):
        return 20.0  # 创业板 / 科创板
    if c.startswith(("8", "4")):
        return 30.0  # 北交所
    return 10.0      # 沪深主板(含 ST)


PASSIVE_MIN_PEERS = 3  # 同题材不足这么多只,封板次序没有意义 → 不给被动度


def passive_map(
    profiles: list[dict],
    themes: dict[str, list[str]] | None,
    hot_themes: list[str] | None,
    min_peers: int = PASSIVE_MIN_PEERS,
) -> dict[str, float]:
    """code → **被动上板度** 0~1:它在同题材里第几个封板(0=第一个封,1=最后被推上去)。

    量化的是复盘里那句「尾盘被板块反推上板,属于悟道板,预期不好」/「缺乏主动性」——
    区分**它带动板块**还是**板块推它上板**。

    本地回测 22 交易日、704 只可判样本(需同题材 ≥min_peers 只):
      0–0.25 最早封 n=217 胜72.8% 均+3.16%
      0.25–0.5      n=181 胜55.2% 均+0.97%
      0.5–0.75      n=115 胜59.1% 均+0.77%
      0.75–1.0 最后 n=191 胜49.2% 均+0.33%
    相关性 r=-0.327,**强于 last_seal(-0.270)与封流比**,是目前测过最强的单因子。
    且不是 last_seal 的马甲:只看封板时刻在中性档(9:45–14:00)的票,最早封仍
    65.0%/+1.75% vs 最后封 59.0%/+0.96% —— 同一时段封板,谁是本题材领头很关键。

    ⚠️ 三处口径必须与回测一致,改了分数就与验证脱钩:
    1. hot_themes 用**全部 ≥2 只**的题材(theme_heat(top=9999)),不是面板的 top12
    2. 一只票多题材时取 **hot_themes 里靠前的**(即当日涨停家数最多的那个)——
       这里要的是「同伴最多的那条线」,与天梯 chip 同规则,但**不同于**候选池 link 的
       「身位最强」口径(那个服务于另一个问题)
    3. 排序用**最终封板** last_seal(缺失退回 first_seal);同题材按此排序取相对次序
    """
    rank = {t: i for i, t in enumerate(hot_themes or [])}
    tm = themes or {}
    pick: dict[str, str] = {}
    for p in profiles:
        ts = [t for t in (tm.get(p["code"]) or []) if t in rank]
        if ts:
            pick[p["code"]] = min(ts, key=lambda t: rank[t])

    groups: dict[str, list[dict]] = {}
    for p in profiles:
        t = pick.get(p["code"])
        if t:
            groups.setdefault(t, []).append(p)

    out: dict[str, float] = {}
    for ps in groups.values():
        if len(ps) < min_peers:
            continue
        ps = sorted(ps, key=lambda x: _seal_minutes(x.get("last_seal") or x.get("first_seal")) or 9999)
        for i, p in enumerate(ps):
            out[p["code"]] = round(i / (len(ps) - 1), 3)
    return out


_SW_SUFFIX = re.compile(r"[ⅠⅡⅢⅣ]+$")


def _clean_industry(name: str) -> str:
    """去掉申万行业名的罗马数字后缀(`燃气Ⅱ`→`燃气`)—— 纯展示噪音,格子里空间金贵。"""
    return _SW_SUFFIX.sub("", str(name or "").strip())


def cell_sector(
    code: str,
    industry: str,
    themes: dict[str, list[str]] | None,
    prev_themes: dict[str, list[str]] | None,
    hot_rank: dict[str, int] | None,
) -> tuple[str, bool]:
    """个股在天梯格子里显示的「所属板块」→ (标签, 是否真板块)。

    为什么不用行业:行业是申万静态分类,跟今天为什么涨停无关,而且源头名字被截断。
    实测美利云行业恒为 `IT服务Ⅱ`,而它连板靠的是 `算力租赁`;豪尔赛行业 `装修装饰`
    实际是 `液冷服务器`、胜通能源 `燃气Ⅱ` 实际是 `机器人` —— 行业在这里是**主动误导**。

    四级回退(实测 0804 逐级累计覆盖 82% → 99% → 100% → 兜底):
    1. 该股今日题材里**当天真形成板块效应**的(hot_rank 来自 theme_heat 的 ≥2 只题材),
       取热度最好的那个 → 返回 True
    2. 榜外的今日题材(只此一只的碎片标签)→ 返回 False
    3. 今日无题材(断板票今天没涨停,自然没有涨停原因)→ 用**昨日**题材同样处理。
       语义也对:「昨日连板今日断板」问的就是它昨天靠什么涨的
    4. 都没有 → 行业(去罗马后缀),返回 False

    第二个返回值供前端分层:真板块亮色、碎片/昨日暗一档 —— 一眼看出哪些票有板块托底、
    哪些是孤票,正对应方法论里「有无同题材联动票同步」。
    """
    rank = hot_rank or {}
    for src in (themes, prev_themes):
        ts = (src or {}).get(code) or []
        if not ts:
            continue
        hot = sorted((rank[t], t) for t in ts if t in rank)
        if hot:
            return hot[0][1], True
        return ts[0], False  # 有题材但都不成板块 → 碎片标签
    return _clean_industry(industry), False


def ladder_board(
    pools: dict,
    industry_min: int = INDUSTRY_MIN_COUNT,
    themes: dict[str, list[str]] | None = None,
    prev_themes: dict[str, list[str]] | None = None,
    hot_themes: list[str] | None = None,
) -> dict:
    """天梯图数据:每档 = 今日封住的票 + **昨日连板今日断板的票**,外加行业分布。

    themes / prev_themes(code → 题材名列表,来自 `ths_limitup_reasons`)与
    hot_themes(当天 ≥2 只的题材名,按热度排好序)都是**可选**的:不传就退化成
    只显示行业的老行为,免得动到别的调用方。

    断板票来源是 `previous`(昨日涨停今日表现)而非炸板池 —— 断板不一定摸过板
    (实测长缆科技 6 板位置 −4.83%,全天没碰涨停,压根不在炸板池里),
    用炸板池会漏掉最关键的「高度被打掉」信息。档位 = 昨日板数 + 1。

    **断板要用涨幅兜底一次**:涨停池会漏收「反复炸板尾盘回封」的票(它们被归进炸板池),
    只按「不在涨停池」判断会把这种票误划成断板。收盘涨幅到涨停幅度的,改判 `reseal`。

    只收昨日 ≥2 板的断板票(见 BROKEN_MIN_PREV_BOARDS);昨日首板今日断板几十只,
    画上去会把 2 板档淹掉,且没有信息量。
    """
    lim = pools.get("limitup", pd.DataFrame())
    prev = pools.get("previous", pd.DataFrame())
    # 热度名 → 排名(0 最强)。只含 ≥2 只的题材,即「当天真形成板块效应」的那批
    hot_rank = {t: i for i, t in enumerate(hot_themes or [])}

    def _sector(code: str, industry: str) -> dict:
        label, is_hot = cell_sector(code, industry, themes, prev_themes, hot_rank)
        return {"sector": label, "sector_hot": is_hot}

    sealed_codes: set[str] = set()
    by_board: dict[int, list[dict]] = {}

    if lim is not None and not lim.empty:
        for p in stock_profiles(lim):
            sealed_codes.add(p["code"])
            first_min = _seal_minutes(p["first_seal"])
            # 展示用「最终封板时间」= 几点才真正稳住;缺失时退回首封
            mins = _seal_minutes(p["last_seal"])
            if mins is None:
                mins = first_min
            by_board.setdefault(p["boards"], []).append({
                "code": p["code"], "name": p["name"], "industry": p["industry"],
                **_sector(p["code"], p["industry"]),
                "first_seal": p["first_seal"], "last_seal": p["last_seal"],
                "seal_minutes": mins,  # 排序与展示都用最终封板
                # 真一字要求全天没开板:一字后炸了又回封的,该显示回封时间而不是标一字
                "is_yizi": first_min is not None and first_min <= _YIZI_MIN and p["break_times"] == 0,
                "break_times": p["break_times"],  # >0 = 炸过又回封,质量打折
                "seal_strength": p["seal_strength"], "pct": p["pct"],
                "broken": False,
            })

    if prev is not None and not prev.empty:
        # 炸板池:给「其实封住了但涨停池没收录」的票补炸板次数(见下面的兜底判据)
        zb = pools.get("zbgc")
        zb_breaks: dict[str, int] = {}
        if zb is not None and not zb.empty and "code" in zb.columns:
            for _, z in zb.iterrows():
                zb_breaks[str(z.get("code"))] = int(_num(z.get("break_times")))

        for _, r in prev.iterrows():
            code = str(r.get("code"))
            pb = int(_num(r.get("prev_boards")))
            if code in sealed_codes or pb < BROKEN_MIN_PREV_BOARDS:
                continue  # 今天封住了 → 已在上面;昨日首板断板 → 不画
            name = str(r.get("name"))
            pct = round(_num(r.get("pct")), 2)
            base = {
                "code": code, "name": name, "industry": str(r.get("industry")),
                **_sector(code, str(r.get("industry"))),
                "first_seal": "", "last_seal": "", "seal_minutes": None, "is_yizi": False,
                "seal_strength": 0.0, "pct": pct,
            }
            if pct >= _limit_pct(code) - LIMIT_EPS:
                # 收盘涨幅已经到涨停 → 它其实封住了,只是 akshare 涨停池漏收 ——
                # 反复炸板、尾盘才回封的票会被归进炸板池。实测 002827 高争民爆:
                # 09:25 一字开盘、炸板 26 次、收盘 41.87 = 涨停价 38.06×1.1,
                # 却只出现在炸板池里,于是被当成断板划了线。
                # **故意不填封板时间**:最终回封时刻拿不到,拿首封顶替会把烂板显示成
                # 「超早封」(评分体系里最强的信号),宁可留空,靠炸板次数说明质量。
                by_board.setdefault(pb + 1, []).append({
                    **base, "break_times": zb_breaks.get(code, 0),
                    "broken": False, "reseal": True,
                })
                sealed_codes.add(code)
                continue
            by_board.setdefault(pb + 1, []).append({**base, "broken": True})

    # 档内排序:先封住的(按首封时间早→晚),炸板的排最后
    for b in by_board:
        by_board[b].sort(key=lambda s: (s["broken"], s["seal_minutes"] if s["seal_minutes"] is not None else 9999))

    rows = [{"boards": b, "stocks": by_board[b]} for b in sorted(by_board, reverse=True)]

    # 行业分布(封住+炸板全算,与图上各档票数总和一致);少于 industry_min 的并进「其他」
    counts: dict[str, int] = {}
    for row in rows:
        for s in row["stocks"]:
            counts[s["industry"] or "其他"] = counts.get(s["industry"] or "其他", 0) + 1
    main = [(k, v) for k, v in counts.items() if v >= industry_min and k != "其他"]
    main.sort(key=lambda kv: (-kv[1], kv[0]))
    others = sum(v for k, v in counts.items() if (v < industry_min or k == "其他"))
    industries = [{"name": k, "count": v} for k, v in main]
    if others:
        industries.append({"name": "其他", "count": others})

    total = sum(len(r["stocks"]) for r in rows)
    return {
        "rows": rows,
        "industries": industries,
        "total": total,
        "sealed": sum(1 for r in rows for s in r["stocks"] if not s["broken"]),
        "broken": sum(1 for r in rows for s in r["stocks"] if s["broken"]),
        "max_board": rows[0]["boards"] if rows else 0,
    }
