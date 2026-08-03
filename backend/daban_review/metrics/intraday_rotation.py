"""盘中情绪切换与板块接力:把日内分时聚合成板块级涨幅曲线,找出「谁退潮、谁接棒」。

其余 metrics 全是**日终截面**(涨停池/天梯/封流比都是收盘那一刻的快照),看不出
资金在盘中怎么换方向。而收盘看起来一样强的两个板块,一个是早盘冲高回落的退潮方、
一个是盘中接棒收在高位的进攻方,次日赔率完全相反 —— 这个差别只有时间轴能给。

分时走 mootdx(免费不限频、可回溯约 10 天),所以事后复盘也能重建曲线。
242 只实测 10.6s;结果建议由 service 落库缓存(历史日曲线永不变)。

## 三条铁律(踩过,别改回去)

1. **口径必须含炸板池 + 昨日涨停**。只取当日涨停池是生存者偏差:每条曲线最后都收在
   +10% 平掉,因为"跌下来"的票恰好是没封住的那些(0731 炸板池 107 只,比涨停池还多)。
2. **只按 industry 聚合,不用题材**。`ths_limitup_reasons` 是涨停原因,对炸板池覆盖率
   实测 **0%**(风华高科/德明利全空)→ 题材维度画不出回落曲线。
3. **炸板次数取池子字段,不从曲线推**。分钟收盘价看不到瞬时开板:华天酒店池子里
   `break_times=6`,但 240 根分钟收盘全在 +9.9%。
"""

from __future__ import annotations

import pandas as pd

# ── 大类映射 ───────────────────────────────────────────────────────────────
# 为什么要这层:行业分类太细,答不了「科技 vs 消费」。0731 消费被拆成 酒店餐饮2只/
# 饮料乳品2只/白酒2只,全部进不了 MIN_STOCKS 门槛;聚成大类才有 23 只、才看得出
# 它收盘创当日新高。实测全库 116 个行业名 3527 条记录 100% 归桶、零「其他」。
#
# 行业名来自涨停池,**是截断的**(「IT服务Ⅱ」「计算机设」「自动化设」「互联网电」
# 「炼化及贸」「摩托车及」),所以这里按原样精确匹配,不要改成前缀/关键词匹配。
_GROUPS: dict[str, str] = {
    "科技硬件": "半导体 元件 消费电子 光学光电 通信设备 电子化学 其他电子 军工电子 计算机设 玻璃玻纤",
    "科技应用": "软件开发 IT服务Ⅱ 通信服务 互联网电 数字媒体 广告营销 影视院线 游戏Ⅱ 出版 教育 "
                "文娱用品 专业服务",
    "消费": "饮料乳品 白酒Ⅱ 非白酒 休闲食品 食品加工 调味发酵 农产品加 酒店餐饮 一般零售 专业连锁 "
            "旅游及景 纺织制造 服装家纺 化妆品 个护用品 饰品 家居用品 家电零部 厨卫电器 小家电 "
            "黑色家电 养殖业 种植业 饲料 渔业 林业Ⅱ 造纸 贸易Ⅱ 包装印刷",
    "医药": "化学制药 中药Ⅱ 医疗服务 医疗器械 医药商业 生物制品 动物保健",
    "电力产业": "电网设备 电力 风电设备 光伏设备 其他电源 电池 燃气Ⅱ 环保设备 环境治理 照明设备",
    "高端制造": "通用设备 专用设备 自动化设 工程机械 电机Ⅱ 轨交设备 摩托车及 商用车 乘用车 汽车零部 "
                "航天装备 航空装备 地面兵装 航海装备",
    "周期资源": "化学制品 化学原料 化学纤维 农化制品 塑料 橡胶 工业金属 贵金属 小金属 能源金属 "
                "金属新材 普钢 特钢Ⅱ 冶钢原料 非金属材 水泥 装修建材 煤炭开采 油气开采 油服工程 "
                "炼化及贸 航运港口",
    "建筑金融": "基础建设 专业工程 工程咨询 装修装饰 房屋建设 证券Ⅱ 多元金融 房地产开 房地产服 "
                "铁路公路 物流 综合Ⅱ",
}
INDUSTRY_GROUP: dict[str, str] = {
    name: group for group, names in _GROUPS.items() for name in names.split()
}
GROUP_ORDER: list[str] = list(_GROUPS)


def group_of(industry: str) -> str:
    """行业 → 大类;没收录的新行业名归「其他」(别让它静默消失,前端能看见就会来加)。"""
    return INDUSTRY_GROUP.get(str(industry or "").strip(), "其他")


# ── 时间桶与形态阈值 ────────────────────────────────────────────────────────
# 采样到 15 分钟:一天 240 根分钟线压到 17 个点,曲线形状不丢、输出体积可控。
# 没有 13:00 桶:A股午后首根分时是 13:01,(11:30, 13:00] 区间永远空,留着图上会有个洞。
BUCKETS: list[str] = [
    "09:35", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30",
    "13:15", "13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00",
]
MIN_STOCKS = 3          # 少于 3 只不算板块(单票标签不构成板块效应,与 theme_heat 同口径)
FADE_STRONG = 2.0       # 峰值→收盘回落多少个点算「退潮」
FADE_HELD = 1.5         # 回落小于多少算「守住」
RISE_TAKER = 3.0        # 收盘−开盘涨多少算「接棒」
EARLY_PEAK = "10:30"    # 峰值不晚于此算早盘见顶
LATE_PEAK = "11:00"     # 峰值不早于此算盘中/下午见顶
TAIL_PEAK = "14:30"     # 峰值不早于此算尾盘走强


def _bucket_series(times: list[str], vals: list[float]) -> dict[str, float]:
    """分钟序列 → 15 分钟桶(取桶内最后一个值,即该时点的现价)。"""
    out: dict[str, float] = {}
    bi = 0
    for t, v in zip(times, vals):
        while bi < len(BUCKETS) - 1 and t > BUCKETS[bi]:
            bi += 1
        if t <= BUCKETS[bi]:
            out[BUCKETS[bi]] = v
    return out


def _int(v, default: int = 0) -> int:
    """安全取整。**不能写 `int(pd.to_numeric(x) or 0)`** —— NaN 在 Python 里是 truthy,
    `or` 兜不住,int(NaN) 直接抛。炸板池/昨日涨停没有 boards 列,踩过。"""
    n = pd.to_numeric(v, errors="coerce")
    return default if pd.isna(n) else int(n)


def _universe(pools: dict) -> dict[str, dict]:
    """全口径个股:涨停 + 炸板 + 昨日涨停,按 code 去重(先到先留,涨停池优先)。

    炸板池是关键 —— 少了它曲线只剩守住的票,看不到"跌下来"那一半(见模块头注铁律 1)。
    """
    uni: dict[str, dict] = {}
    for src in ("limitup", "zbgc", "previous"):
        df = pools.get(src)
        if df is None or getattr(df, "empty", True):
            continue
        for _, r in df.iterrows():
            code = str(r.get("code") or "")
            pct = pd.to_numeric(r.get("pct"), errors="coerce")
            if not code or pd.isna(pct):
                continue
            if code in uni:
                continue
            ind = str(r.get("industry") or "其他")
            uni[code] = {
                "code": code,
                "name": str(r.get("name") or ""),
                "industry": ind,
                "group": group_of(ind),
                "pct": round(float(pct), 2),
                "src": src,
                # 昨日涨停池没有 boards,它的板位字段叫 prev_boards(是昨天的板位)
                "boards": _int(r.get("boards")) or _int(r.get("prev_boards")),
                # 只取今日封板时间。昨日涨停池的 prev_seal 是**昨天**封的,拿来当今日会污染时序
                "first_seal": str(r.get("first_seal") or ""),
                "last_seal": str(r.get("last_seal") or ""),
                # 炸板次数只信池子字段,分钟收盘看不到瞬时开板(铁律 3)
                "break_times": _int(r.get("break_times")),
            }
    return uni


def _shape(c: dict) -> str:
    """给曲线定形态。判据全是相对量(回落/涨幅),不受当日大盘绝对位置影响。"""
    peak_at, fade = c["peak_at"], c["fade"]
    rise = c["close"] - c["open"]
    if peak_at and peak_at <= EARLY_PEAK and fade >= FADE_STRONG:
        return "早盘冲高回落"
    if peak_at and peak_at >= TAIL_PEAK and fade <= FADE_HELD:
        return "尾盘走强"
    if peak_at and peak_at >= LATE_PEAK and fade <= FADE_HELD and rise >= RISE_TAKER:
        return "盘中接棒"
    if fade >= FADE_STRONG:
        return "冲高回落"
    return "全天平推" if c["close"] >= 0 else "全天弱"


def _curve(name: str, stocks: list[dict], series: dict[str, dict[str, float]]) -> dict | None:
    """一个板块的均值曲线 + 派生读数。桶内不足 MIN_STOCKS 只有曲线的票则返回 None。"""
    codes = [s["code"] for s in stocks if s["code"] in series]
    if len(codes) < MIN_STOCKS:
        return None
    pts: dict[str, float] = {}
    for b in BUCKETS:
        vs = [series[c][b] for c in codes if b in series[c]]
        if vs:
            pts[b] = round(sum(vs) / len(vs), 2)
    if not pts:
        return None

    peak_at = max(pts, key=lambda b: pts[b])
    close = pts.get(BUCKETS[-1], pts[peak_at])
    c = {
        "name": name,
        "count": len(codes),
        "points": [{"t": b, "pct": pts[b]} for b in BUCKETS if b in pts],
        "open": pts.get(BUCKETS[0], close),
        "peak": pts[peak_at],
        "peak_at": peak_at,
        "close": close,
        "fade": round(pts[peak_at] - close, 2),
        "am_pm": round(close - pts.get("11:30", close), 2),  # 下午净变化:午后是谁在做
        # 代表票:当日涨幅最高的前 3(供 tooltip 与点击看分时)
        "leaders": [
            {"code": s["code"], "name": s["name"], "pct": s["pct"], "boards": s["boards"],
             "first_seal": s["first_seal"], "break_times": s["break_times"]}
            for s in sorted(stocks, key=lambda x: x["pct"], reverse=True)[:3]
        ],
    }
    c["shape"] = _shape(c)
    return c


def _rotations(curves: list[dict], top: int = 3) -> list[dict]:
    """退潮方 × 接棒方 配对:一方早见顶且明显回落,另一方晚见顶且守住且涨上来。

    只做**同日内的时间先后**判断,不声称因果(资金是不是真从 A 流到 B 无从证实),
    所以字段叫 fader/taker 而不是 from/to。

    排序按 `(回落+涨幅) × √min(两边只数)`:**必须给样本数加权**,否则 3 只票的小板块
    因为幅度大就压过 10 只票的半导体(0731 实测「金属新材3只」排到「半导体10只」前面),
    而小样本的均值曲线本来就抖。每个退潮方只留它最强的一条,避免同一个接棒方刷满前三。
    """
    faders = [c for c in curves if c["fade"] >= FADE_STRONG]
    takers = [c for c in curves if c["fade"] <= FADE_HELD and c["close"] - c["open"] >= RISE_TAKER]
    out = []
    for f in faders:
        for t in takers:
            if f["name"] == t["name"] or not (f["peak_at"] < t["peak_at"]):
                continue
            out.append({
                "fader": f["name"], "taker": t["name"],
                "fader_peak": f["peak"], "fader_peak_at": f["peak_at"],
                "fader_close": f["close"], "fader_fade": f["fade"],
                "taker_open": t["open"], "taker_peak_at": t["peak_at"], "taker_close": t["close"],
                "taker_rise": round(t["close"] - t["open"], 2),
                "evidence": (
                    f"{f['name']}{f['count']}只 {f['peak_at']} 见顶{f['peak']:+.1f}% → "
                    f"收{f['close']:+.1f}%(回落{f['fade']:.1f});"
                    f"{t['name']}{t['count']}只 开盘{t['open']:+.1f}% → "
                    f"{t['peak_at']} 峰值 → 收{t['close']:+.1f}%(涨{t['close'] - t['open']:+.1f})"
                ),
                "_w": (f["fade"] + t["close"] - t["open"]) * min(f["count"], t["count"]) ** 0.5,
            })
    out.sort(key=lambda x: x["_w"], reverse=True)
    best: list[dict] = []
    seen: set[str] = set()
    for o in out:
        if o["fader"] in seen:
            continue
        seen.add(o["fader"])
        o.pop("_w", None)
        best.append(o)
    return best[:top]


# 封板/炸板时序用 30 分钟桶:分钟级太碎,看不出"哪个时段是谁在封"
_SEAL_BUCKETS = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"]


def _hhmm(seal: str) -> str:
    """池子里的封板时间是 HHMMSS(如 093409)→ HH:MM;取不到返回空串。"""
    t = "".join(ch for ch in str(seal or "") if ch.isdigit())
    return f"{t[:2]}:{t[2:4]}" if len(t) >= 4 else ""


def _seal_timeline(uni: dict[str, dict]) -> list[dict]:
    """每 30 分钟 × 大类的封板数 / 炸板数。纯本地零请求,与曲线互相印证。

    封板取 last_seal(最终封住那一刻)优先、退回 first_seal;炸板取炸板池里的票。
    **昨日涨停池(previous)整体排除** —— 它的封板时间是昨天的,今天多数根本没封。
    """
    rows = {b: {"t": b, "sealed": {}, "broken": {}} for b in _SEAL_BUCKETS}

    def _put(bag: str, bucket: str, group: str) -> None:
        d = rows[bucket][bag]
        d[group] = d.get(group, 0) + 1

    for m in uni.values():
        if m["src"] == "previous":
            continue
        hm = _hhmm(m["last_seal"] or m["first_seal"])
        if not hm:
            continue
        bucket = next((b for b in _SEAL_BUCKETS if hm <= b), _SEAL_BUCKETS[-1])
        _put("broken" if m["src"] == "zbgc" else "sealed", bucket, m["group"])
    return [rows[b] for b in _SEAL_BUCKETS]


def build_rotation(pools: dict, date: str, fetch_min=None) -> dict:
    """当日盘中切换全量结果。

    fetch_min(code, date) -> DataFrame[time, close, ...];走参数注入,单测才能打桩不联网。
    返回 {date, universe, fetched, groups[], industries[], rotations[], seal_timeline[]},
    groups/industries 是同一套曲线结构(name/count/points/shape/派生读数),前端两个口径切换。
    """
    if fetch_min is None:  # 延迟导入:纯计算部分不该依赖网络模块
        from ..data.akshare_client import stock_intraday_min as fetch_min

    uni = _universe(pools)
    series: dict[str, dict[str, float]] = {}
    for code, m in uni.items():
        try:
            df = fetch_min(code, date)
        except Exception:  # noqa: BLE001 —— 单只票取不到不该让整个复盘失败
            continue
        if df is None or len(df) < 100:  # 半天以下的数据算不出形态,宁缺勿滥
            continue
        closes = pd.to_numeric(df["close"], errors="coerce").tolist()
        if not closes or pd.isna(closes[-1]) or closes[-1] <= 0:
            continue
        prev = closes[-1] / (1 + m["pct"] / 100)  # 末根 close 反推昨收,省一次日线请求
        if prev <= 0:
            continue
        times = [str(t) for t in df["time"].tolist()]
        series[code] = _bucket_series(times, [round((c / prev - 1) * 100, 2) for c in closes])

    def _by(key: str, order: list[str] | None) -> list[dict]:
        bags: dict[str, list[dict]] = {}
        for m in uni.values():
            bags.setdefault(m[key], []).append(m)
        cs = [c for name, ss in bags.items() if (c := _curve(name, ss, series))]
        if order:  # 大类按固定顺序,行业按收盘强弱
            cs.sort(key=lambda c: order.index(c["name"]) if c["name"] in order else 99)
        else:
            cs.sort(key=lambda c: c["close"], reverse=True)
        return cs

    groups = _by("group", GROUP_ORDER)
    industries = _by("industry", None)
    return {
        "date": date,
        "universe": len(uni),
        "fetched": len(series),
        "groups": groups,
        "industries": industries,
        # 切换配对在行业层找(细,真轮动发生在这一层),大类层只用于概览曲线
        "rotations": _rotations(industries),
        "group_rotations": _rotations(groups),
        "seal_timeline": _seal_timeline(uni),
    }
