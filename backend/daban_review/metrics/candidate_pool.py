"""四风格候选池:在起 agent 之前用客观因子把「可选标的」筛好排好,agent 只能在池内选。

为什么要有池(设计动机):
- 原先 agent 从整个梯队(几十上百只)凭推理自选候选,`score.grade_candidate` 只在事后贴标签
  → 客观因子没参与「选」,同一天复跑两次会换一批票。把选池前移到纯规则层,复现性才有保障。
- 排序 key 完全确定(含 tie-break),同样输入必得同样池;agent 默认取 rank1,越级须写明理由。

风格硬筛(与 score.py 的身位口径一致):
- 低位连板接力:2-3 板(晋级率最高的接力区)
- 首板打板:1 板,且**必须有题材归属**(无题材的首板=没有打板逻辑,不进池)
- 题材情绪龙头:热度 top N 题材内的最高身位票(并列取封流比更强者)
- 高位龙头接力:≥4 板(赔率转差但仍是市场高度所在)
"""

from __future__ import annotations

import datetime as dt
import pandas as pd

from .kline import volume_ratio
from .ladder import passive_map, stock_profiles
from .pattern_blacklist import get_blacklist
from .score import _first_seal_minutes, grade_candidate
from .sector import theme_heat
from ..data import store

# 与 service.CANDIDATE_STYLES 同名同序(前端展示顺序也依赖它)
STYLES = ["低位连板接力", "首板打板", "题材情绪龙头", "高位龙头接力"]

# 缩量与竞价大单阈值(口径同 kline.py / pattern_blacklist.py)
SHRINK_VR = 0.8          # vr < 此值 = 缩量
BIG_BID_VOL = 200_000    # 竞价买一挂单 >20W手 = 疑似量化大单


def _unplayable(item: dict) -> int:
    """「打不了」标记(1=排到池尾)。

    换手 <1% 且不属于任何热门主线题材(theme_rank 为空)= 一字锁死的消息面独苗:次日要么继续一字
    买不到、要么直接砸,盘中没有可打的承接位,又没有方向联动托底 —— 客观上不具备接力条件。
    注意判据是「有没有主线归属」而非「有没有题材标签」:并购独苗那种冷门标签算不上方向。
    早期版本把这个判断留给 agent(它每次自行决定要不要越级跳过),同一天复跑就会换人;
    收进规则层后 rank1 直接稳定,agent 无须越级。只影响排序,不动 score/grade(保持回测同口径)。
    """
    turnover = float(item.get("turnover") or 0.0)
    return 1 if (0 < turnover < 1.0 and item.get("theme_rank") is None) else 0


def _shrink_penalty(item: dict) -> int:
    """缩量降权:非缩量0 / 一二板缩量1 / 三板及以上缩量2。

    三板缩量比一二板更危险(高度+缩量=接力断档,炸板低开风险更高),所以更重。
    排在 _unplayable 之后:一字锁死的消息面独苗仍是更高优先级的「打不了」。
    """
    if not item.get("is_shrink"):
        return 0
    return 2 if int(item.get("boards") or 0) >= 3 else 1


def _bigbid_penalty(item: dict) -> int:
    """竞价大单降权(量化票特征):挂单 > BIG_BID_VOL → 1,沉到同档非量化票后面。

    比缩量轻:量化大单是「特征」不是「定罪」,降权沉底但保留(不像黑名单那样硬排)。
    """
    return 1 if item.get("is_bigbid") else 0


def _risk_flags(item: dict) -> list[str]:
    """给前端/agent 可见的风险标注(只展示,不参与排序)。"""
    flags: list[str] = []
    if item.get("is_shrink"):
        b = int(item.get("boards") or 0)
        flags.append(f"缩量{b}板" if b else "缩量")
    if item.get("is_bigbid"):
        flags.append("量化大单")
    return flags


def _sort_key(item: dict) -> tuple:
    """确定性排序:可打性 → 缩量 → 竞价大单 → 分数降 → 封流比降 → 首封早 → 代码升。

    末项保证无并列歧义(同样输入必得同样池,保复现性)。"""
    fmin = _first_seal_minutes(item.get("first_seal", ""))
    return (
        _unplayable(item),
        _shrink_penalty(item),
        _bigbid_penalty(item),
        -int(item.get("score") or 0),
        -float(item.get("seal_strength") or 0.0),
        fmin if fmin is not None else 9999,
        item.get("code", ""),
    )


def _theme_ranks(theme_rank: list[dict]) -> dict[str, int]:
    """题材名 → 主线排名(1 起)。

    输入是 sector.theme_heat 的输出(按 zt_count 降序,给前端看热度用)。这里**重排为身位优先**:
    (最高板, 连板数, 涨停数)。原因:「中报预增」「央企」「半年报预增」这类泛业绩/泛属性标签
    经常涨停家数最多但一个连板都没有——它们是标签不是主线,按 zt_count 排会把首板泛标签票
    顶成"题材龙头"。真主线的特征是**有连板高度**。
    """
    ordered = sorted(
        theme_rank or [],
        key=lambda t: (
            -int(t.get("max_board") or 0),
            -int(t.get("lianban_count") or 0),
            -int(t.get("zt_count") or 0),
            str(t.get("theme")),
        ),
    )
    return {str(t.get("theme")): i + 1 for i, t in enumerate(ordered)}


def build_candidate_pool(
    pools: dict,
    emotion: dict,
    themes: dict[str, list[str]] | None = None,
    theme_rank: list[dict] | None = None,
    top: int = 5,
    theme_top: int = 5,
    prev_zbgc: set[str] | None = None,
    today: str | None = None,
) -> dict:
    """构造四风格候选池。

    pools:  fetch.fetch_day 的池子(用 limitup)
    emotion: compute_emotion 结果(取 phase_hint 作打分基准)
    themes: code → 题材名列表(akshare_client.ths_limitup_reasons)
    theme_rank: sector.theme_heat 输出,用于取「热度 top theme_top 题材」
    top: 每种风格保留几只
    prev_zbgc: 前一交易日炸板池代码集(`store.prev_zbgc_codes`),用于标「弱转强」给 score 加分;
      不传就没这份加分(与 score.grade_candidate 的可选 `w2s` 约定一致)

    「被动上板度」(passive)不用额外传参 —— 由 themes 内部算(见 ladder.passive_map)。

    返回 {"phase": ..., "theme_top": [...], "pool": {style: [item...]}},
    item 含打分因子原值 + score/grade/position/reasons + rank + price(涨停价,供触发价算式)。
    """
    lim = pools.get("limitup", pd.DataFrame())
    if lim is None or lim.empty:
        return {"phase": emotion.get("phase_hint", "未知"), "theme_top": [], "pool": {s: [] for s in STYLES}}

    phase = emotion.get("phase_hint", "未知")
    themes = themes or {}
    ranks = _theme_ranks(theme_rank)
    hot_themes = [t for t, r in ranks.items() if r <= theme_top]

    # today:优先入参,否则从 limitup 的 date 列(落库时存的)推断,再否则今天。
    # 候选池缩量/竞价/黑名单都依赖它;取不到时安全退化为不判(同旧行为)。
    if today is None and not lim.empty and "date" in lim.columns:
        today = str(lim["date"].iloc[0])
    if today is None:
        today = dt.date.today().strftime("%Y%m%d")

    # 全池打分(纯规则,与次日验证同口径)
    bl = get_blacklist(today)                # 历史模式黑名单(硬排除)
    bid_vols = store.auction_bid_vols(today)  # 竞价大单(降权)
    scored: list[dict] = []
    zb = prev_zbgc or set()
    profs = stock_profiles(lim)
    # 被动上板度:用**全部 ≥2 只**的题材(不是 theme_rank 用的 top12),与回测口径一致
    passive = passive_map(profs, themes, [t["theme"] for t in theme_heat(pools, themes, top=9999)])
    for p in profs:
        if p["code"] in bl:
            continue  # 历史模式命中(缩量→次日炸板/低开/一字≥2次):硬排除,不进池
        vr = volume_ratio(p["code"], today)
        p = {**p, "w2s": p["code"] in zb, "passive": passive.get(p["code"]),
             "vr": vr,
             "is_shrink": vr is not None and vr < SHRINK_VR,
             "is_bigbid": bid_vols.get(p["code"], 0) > BIG_BID_VOL}
        g = grade_candidate(p, phase)
        my_themes = themes.get(p["code"], [])
        scored.append({
            **p,
            "theme": my_themes,
            "theme_rank": min((ranks[t] for t in my_themes if t in ranks), default=None),
            "score": g["score"],
            "grade": g["grade"],
            "position": g["position"],
            "reasons": g["reasons"],
            "risk_flags": _risk_flags(p),
        })

    def _pick(pred) -> list[dict]:
        got = sorted([s for s in scored if pred(s)], key=_sort_key)[:top]
        return [{**item, "rank": i} for i, item in enumerate(got, 1)]

    # 题材龙头:每个热门题材内的最高身位(并列取封流比强者)
    leaders: dict[str, dict] = {}
    for s in scored:
        for t in s["theme"]:
            if t not in hot_themes:
                continue
            cur = leaders.get(t)
            if cur is None or (s["boards"], s["seal_strength"]) > (cur["boards"], cur["seal_strength"]):
                leaders[t] = {**s, "lead_theme": t, "lead_theme_rank": ranks[t]}
    # 一只票可能同时是多个题材的龙头(如顺钠=数据中心+储能)→ 按 code 去重,保留主线排名最好的那个,
    # 否则同一只票会占掉多个 rank,把池的可选面挤没了。
    dedup: dict[str, dict] = {}
    for v in leaders.values():
        cur = dedup.get(v["code"])
        if cur is None or v["lead_theme_rank"] < cur["lead_theme_rank"]:
            dedup[v["code"]] = v
    # 排序:主线排名优先,同一主线内再按统一 key。龙头的语义是「最强主线的领涨」,
    # 不是「封流比最高的票」——纯 score 排会让泛标签(中报预增)的首板压过真主线的连板。
    leader_sorted = sorted(dedup.values(), key=lambda x: (x["lead_theme_rank"], *_sort_key(x)))
    leader_codes = set(dedup)

    pool = {
        "低位连板接力": _pick(lambda s: 2 <= s["boards"] <= 3),
        "首板打板": _pick(lambda s: s["boards"] == 1 and bool(s["theme"])),
        "题材情绪龙头": [{**item, "rank": i} for i, item in enumerate(leader_sorted[:top], 1)],
        "高位龙头接力": _pick(lambda s: s["boards"] >= 4),
    }
    # 首板池里若已是某热门题材龙头,标注出来(agent 判断题材新鲜度时的加分依据)
    for item in pool["首板打板"]:
        item["is_theme_leader"] = item["code"] in leader_codes

    # 主线题材 top N:一段「方向拆解」直接照这个顺序写,避免每次复跑换一批方向(原先 agent 自行归类,
    # 一次分出「医药」一次分出「中报预增」)。附家数/高度/龙头,省得 agent 再去 sector_heat 里凑数。
    by_name = {str(t.get("theme")): t for t in (theme_rank or [])}
    mainlines = []
    for t, r in sorted(ranks.items(), key=lambda kv: kv[1])[:theme_top]:
        raw = by_name.get(t, {})
        lead = leaders.get(t)
        mainlines.append({
            "theme": t,
            "rank": r,
            "zt_count": raw.get("zt_count"),
            "lianban_count": raw.get("lianban_count"),
            "max_board": raw.get("max_board"),
            "lead": {"code": lead["code"], "name": lead["name"], "boards": lead["boards"],
                     "seal_strength": lead["seal_strength"]} if lead else None,
        })

    return {
        "phase": phase,
        "theme_top": mainlines,
        "profile_targets": _profile_targets(pool, scored),
        "pool": pool,
    }


def _profile_targets(pool: dict, scored: list[dict]) -> list[dict]:
    """二段「重点连板票画像」的固定 4 只(规则选,agent 不得替换)。

    为什么规则化:原先让 agent 自己挑 3-6 只,同日复跑会换人(一次挑爱丽家居、一次挑长城军工),
    整段结论跟着变。改为按打板视角的四个固定席位取,席位内用池的同一套排序:
      ①市场高度(高位池 rank1) ②卡位板(低位池 rank1) ③主线龙头(题材龙头池 rank1)
      ④次高身位补位(去重后从剩余连板票里按 _sort_key 取最强)
    去重后不足 4 只时用剩余连板票补齐;连板票本身不足则有几只算几只。
    """
    picks: list[dict] = []
    seen: set[str] = set()

    def add(item: dict | None, seat: str) -> None:
        if item and item["code"] not in seen:
            seen.add(item["code"])
            picks.append({**item, "seat": seat})

    def first(style: str) -> dict | None:
        items = pool.get(style) or []
        return items[0] if items else None

    add(first("高位龙头接力"), "市场高度")
    add(first("低位连板接力"), "卡位板")
    add(first("题材情绪龙头"), "主线龙头")
    for s in sorted([x for x in scored if x["boards"] >= 2], key=_sort_key):
        if len(picks) >= 4:
            break
        add(s, "次高身位")
    return picks[:4]


def pool_codes(pool_payload: dict) -> dict[str, set[str]]:
    """{style: {code...}},供 service 校验 agent 输出的候选是否越出池外。"""
    return {style: {i["code"] for i in items} for style, items in (pool_payload.get("pool") or {}).items()}
