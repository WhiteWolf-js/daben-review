"""板块热度:从涨停池按行业聚合,识别当日资金主攻的方向。

纯本地计算(涨停池自带 industry 字段),不额外请求、不限频。
输出按涨停数排序的板块,每个板块含连板数/最高板/代表票,供 agent 做方向拆解。
"""

from __future__ import annotations

import re

import pandas as pd

# 板块名归一:去后缀/括注/年份前缀,提高题材名 ↔ 板块名命中率。
# 实测失配主因就是这三类:「2026中报预增」vs「中报预增」、「数据中心(AIDC)」vs「数据中心」、
# 「存储芯片概念」vs「存储芯片」。
_SUFFIX = re.compile(r"(概念板块|概念股|概念|板块|指数)$")
_BRACKET = re.compile(r"[(（][^)）]*[)）]")
_YEAR_PREFIX = re.compile(r"^(19|20)\d{2}\s*")

# 宽方向根词(有序,靠前优先级高)。
# 规则:_norm_name(hot_rank 题材) 含某根词 → 展示该根词。
# 长词排前,避免 "AI算力" 被 2 字 "AI" 截断;每组内从具体到宽泛。
_BROAD_ROOTS: list[str] = [
    # AI/算力
    "数据中心",
    "光模块",
    "液冷",
    "算力",
    "存储芯片",
    "芯片",
    "半导体",
    "机器人",
    "人工智能",
    "华为",
    "鸿蒙",
    # 新能源
    "储能",
    "光伏",
    "风电",
    "锂电",
    "新能源",
    # 军工/航天
    "卫星",
    "低空",
    "军工",
    "航空",
    # 大宗
    "黄金",
    "白银",
    # 医药
    "创新药",
    "中药",
]


def _norm_name(s: str) -> str:
    s = _BRACKET.sub("", str(s)).strip()
    return _SUFFIX.sub("", _YEAR_PREFIX.sub("", s)).strip()


def match_quote(theme: str, quotes: dict[str, dict]) -> dict | None:
    """把同花顺题材名匹配到东财概念板块行情。

    两家命名体系不同(如「存储芯片」vs「存储芯片概念」),故:①归一后精确匹配
    ②双向含子串(长度≥3 才允许,避免「芯片」误配一堆)。匹配不到返回 None。
    """
    if not theme or not quotes:
        return None
    norm = {_norm_name(k): v for k, v in quotes.items()}
    t = _norm_name(theme)
    if t in norm:
        return norm[t]
    if len(t) < 3:
        return None
    for k, v in norm.items():
        if len(k) >= 3 and (t in k or k in t):
            return v
    return None


def broad_concept_name(theme: str, quotes: dict[str, dict]) -> str | None:
    """把细粒度题材名映射到宽粒度方向名。

    两级匹配(静态根词优先,保证宽化效果):
    1. _BROAD_ROOTS 静态根词:「液冷服务器」→「液冷」,「算力集成」→「算力」
    2. concept_quotes key 集合(动态 top-20):兜底映射到 THS 日榜方向名
    """
    if not theme:
        return None
    t = _norm_name(theme)
    # 1. static root (highest priority — ensures coarsening regardless of concept_quotes content)
    for root in _BROAD_ROOTS:
        if root in t:
            return root
    # 2. concept_quotes match (dynamic daily top-20)
    for key in (quotes or {}):
        k = _norm_name(key)
        if not k:
            continue
        if t == k:
            return k
        if len(t) >= 3 and len(k) >= 3 and (t in k or k in t):
            return k
    return None


def sector_heat(pools: dict, top: int = 12) -> list[dict]:
    lim = pools.get("limitup", pd.DataFrame())
    if lim is None or lim.empty:
        return []

    buckets: dict[str, dict] = {}
    for _, r in lim.iterrows():
        ind = str(r.get("industry") or "其他")
        boards = int(pd.to_numeric(r.get("boards"), errors="coerce") or 0)
        b = buckets.setdefault(
            ind, {"sector": ind, "zt_count": 0, "lianban_count": 0, "max_board": 0, "stocks": []}
        )
        b["zt_count"] += 1
        if boards >= 2:
            b["lianban_count"] += 1
        b["max_board"] = max(b["max_board"], boards)
        b["stocks"].append({"code": str(r.get("code") or ""), "name": str(r.get("name")), "boards": boards})

    res = sorted(buckets.values(), key=lambda x: (x["zt_count"], x["max_board"]), reverse=True)
    for b in res:
        b["stocks"].sort(key=lambda s: s["boards"], reverse=True)
        b["stocks"] = b["stocks"][:8]  # 每板块最多列 8 只代表票
    return res[:top]


def theme_heat(
    pools: dict,
    themes: dict[str, list[str]],
    top: int = 12,
    min_count: int = 2,
    quotes: dict[str, dict] | None = None,
    order: str = "count",
) -> list[dict]:
    """按题材(同花顺涨停原因标签)聚合涨停池,一只票的多个题材分别计入。

    题材维度比行业更贴近当日炒作主线(哈药=医药+科技)。只保留 ≥min_count 只涨停的题材——
    **单票独有的题材是个股标签、不构成板块效应**(天梯 chip 判「真板块」用的就是这条)。
    themes 为空(拉取失败)时返回 []。

    order:
    - `count`(默认,**别改**)—— 按涨停家数。`runner.run_review` 喂给 agent 的
      `get_sector_heat` 用这个;改了会变动 agent 的输入,按仓库铁律得同日复跑比对。
    - `position` —— 按身位 (最高板, 连板数, 涨停数)。给前端题材热度面板用:
      家数排序会把「中报预增(13只/1连)」「超跌反弹(12只/0连)」这类**泛标签**顶到前排,
      它们是标签不是方向;真主线的特征是有连板高度(实测改成身位后前排变成
      具身智能 3只/7板、AI教育 2只/7板、液冷服务器、商业航天)。与
      `candidate_pool._theme_ranks` 同口径。

    quotes(可选,来自 akshare_client.concept_quotes)给每个题材附板块强度:pct(板块涨幅%)、
    board_high(板块内最高身位)、board_zt(同花顺口径板块涨停数)。同花顺只出 top20 板块,
    冷门题材匹配不到 → 这几个字段为 None,前端显示「—」。
    """
    lim = pools.get("limitup", pd.DataFrame())
    if lim is None or lim.empty or not themes:
        return []

    buckets: dict[str, dict] = {}
    for _, r in lim.iterrows():
        code = str(r.get("code") or "")
        boards = int(pd.to_numeric(r.get("boards"), errors="coerce") or 0)
        for theme in themes.get(code, []):
            b = buckets.setdefault(
                theme, {"theme": theme, "zt_count": 0, "lianban_count": 0, "max_board": 0, "stocks": []}
            )
            b["zt_count"] += 1
            if boards >= 2:
                b["lianban_count"] += 1
            b["max_board"] = max(b["max_board"], boards)
            b["stocks"].append({"code": code, "name": str(r.get("name")), "boards": boards})

    res = [b for b in buckets.values() if b["zt_count"] >= min_count]
    if order == "position":
        res.sort(key=lambda x: (x["max_board"], x["lianban_count"], x["zt_count"]), reverse=True)
    else:
        res.sort(key=lambda x: (x["zt_count"], x["max_board"]), reverse=True)
    for b in res:
        b["stocks"].sort(key=lambda s: s["boards"], reverse=True)
        b["stocks"] = b["stocks"][:8]
        q = match_quote(b["theme"], quotes or {})
        b["pct"] = q.get("pct") if q else None            # 板块涨幅 %
        b["board_high"] = q.get("high") if q else None    # 板块内最高身位,如「8天7板」
        b["board_zt"] = q.get("limit_up_num") if q else None  # 同花顺口径板块涨停数(与本地聚合互校)
    return res[:top]
