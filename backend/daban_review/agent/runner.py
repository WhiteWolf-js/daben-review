"""agent 执行:预拉当日数据→算指标→挂 in-process 工具→跑 Claude→返回/流式复盘文本。"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from ..config import CONFIG
from ..data import fetch, store
from ..metrics import (
    auction_board,
    build_candidate_pool,
    build_hot_klines,
    build_ladder,
    compute_emotion,
    sector_heat,
    theme_heat,
)
from .prompt import ASK_SYSTEM_PROMPT, AUCTION_BRIEF_PROMPT, HOLDING_SYSTEM_PROMPT, SYSTEM_PROMPT
from .tools import SERVER_NAME, make_server

log = logging.getLogger(__name__)

# 完整复盘必须调全的工具(短名)。少调一个就意味着这次复盘的数据基础与上次不同 → 结论漂移。
REQUIRED_TOOLS = {
    "get_market_emotion", "get_limitup_ladder", "get_sector_heat",
    "get_auction", "get_hot_klines", "get_candidate_pool",
}


def _resolve_cli() -> str | None:
    """用系统新版 claude CLI(支持 --thinking adaptive);bundled 2.1.97 太老不支持。找不到则回退 bundled。"""
    p = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    return p if p and os.path.exists(p) else None


_CLI_PATH = _resolve_cli()


def load_pools(date: str) -> dict:
    """优先读库,库里没有再实时拉(并落库)。"""
    conn = store.get_conn()
    pools = {name: store.read_df(conn, table, date) for name, table in fetch.TABLE.items()}
    conn.close()
    if pools.get("limitup") is None or pools["limitup"].empty:
        log.info("库中无 %s 数据,实时拉取", date)
        pools = fetch.fetch_day(date, persist=True)
    return pools


def _load_report_md(date: str) -> str:
    """读已存的当日复盘 markdown(供追问作背景);无则空串。"""
    conn = store.get_conn()
    try:
        row = conn.execute("SELECT markdown FROM review_report WHERE date=?", (date,)).fetchone()
    except Exception:  # noqa: BLE001
        row = None
    conn.close()
    return row[0] if row and row[0] else ""


def _hot_stocks(date: str, pools: dict) -> list[dict]:
    """热门票列表(供 K 线感知):最近交易日用实时人气榜前20,历史日退化用当日涨停池成交额 Top20。

    返回 [{code, name, boards, turnover}]。turnover 取自当日涨停池(非涨停票为 None)。
    """
    import datetime as dt

    import pandas as pd

    from ..data import akshare_client as ak

    lim = pools.get("limitup")
    board_map, name_map, turn_map = {}, {}, {}
    if lim is not None and not lim.empty:
        for _, r in lim.iterrows():
            c = str(r.get("code"))
            board_map[c] = int(pd.to_numeric(r.get("boards"), errors="coerce") or 0)
            name_map[c] = str(r.get("name"))
            turn_map[c] = round(float(pd.to_numeric(r.get("turnover"), errors="coerce") or 0), 2)

    try:
        days_ago = (dt.date.today() - dt.datetime.strptime(date, "%Y%m%d").date()).days
    except ValueError:
        days_ago = 0

    stocks: list[dict] = []
    if 0 <= days_ago <= 1:  # 实时人气榜是「此刻」热度,仅今天/昨天复盘适用;更早用当日涨停池
        for h in ak.hot_rank_top(20):
            c = h["code"]
            stocks.append({"code": c, "name": h["name"] or name_map.get(c, ""),
                           "boards": board_map.get(c, 0), "turnover": turn_map.get(c)})
    if not stocks and lim is not None and not lim.empty:  # 历史日退化:涨停池成交额 Top20
        top = lim.copy()
        top["_amt"] = pd.to_numeric(top["amount"], errors="coerce")
        for _, r in top.nlargest(20, "_amt").iterrows():
            c = str(r.get("code"))
            stocks.append({"code": c, "name": name_map.get(c, ""),
                           "boards": board_map.get(c, 0), "turnover": turn_map.get(c)})
    return stocks


def _extract_usage(msg) -> dict:
    """从 ResultMessage 取 token 用量 + SDK 成本,供 pricing.compute_cost 计价。"""
    u = getattr(msg, "usage", None) or {}
    if not isinstance(u, dict):
        u = getattr(u, "__dict__", {}) or {}
    return {"usage": u, "total_cost_usd": getattr(msg, "total_cost_usd", None)}


async def run_review(
    date: str,
    question: str | None = None,
    on_text: Callable[[str], None] | None = None,
    on_tool: Callable[[str, dict], None] | None = None,
    on_usage: Callable[[dict], None] | None = None,
    max_turns: int = 40,
) -> str:
    """跑一次复盘/追问。on_text 逐段回调(供 SSE 流式);返回完整文本。"""
    pools = load_pools(date)
    emotion = compute_emotion(pools)
    ladder = build_ladder(pools["limitup"])
    auction = auction_board(pools, date)

    # 板块热度:行业维度 + 题材维度(同花顺涨停原因,多属性)
    from ..data import akshare_client as ak

    themes = ak.ths_limitup_reasons(date)
    sector = {"industry": sector_heat(pools), "theme": theme_heat(pools, themes)}

    # 热门票 K 线拉取较重(~20 票日线)。完整复盘才拉;追问跳过(省时),改注入已生成的复盘作背景。
    if question:
        hot_klines = []
    else:
        hot_klines = build_hot_klines(_hot_stocks(date, pools), date)

    # 候选池:纯规则先筛好排好,agent 只能在池内选(复现性的关键,见 metrics/candidate_pool.py)
    # prev_zbgc 让候选池能标「弱转强」(昨炸板今涨停,回测有 +1.8pp 超额)
    pool = build_candidate_pool(pools, emotion, themes, sector["theme"],
                                prev_zbgc=store.prev_zbgc_codes(date))
    server, tool_names = make_server(date, emotion, ladder, sector, auction, hot_klines, pool)

    options = ClaudeAgentOptions(
        model=CONFIG.claude_model,
        # 追问是答问不是复盘:复盘那套「6 工具门禁 + 五段结构 + 候选池选择权」对追问纯属负担
        # (会让它把一句问话答成一整篇复盘),故换精简的 ASK 提示词,轮数也收紧。
        system_prompt=ASK_SYSTEM_PROMPT if question else SYSTEM_PROMPT,
        allowed_tools=tool_names,
        mcp_servers={SERVER_NAME: server},
        tools=[],  # 只用上面的 in-process MCP 工具;内置工具(Bash/Read/Edit/WebFetch…)一个都不需要,
                   # 它们的定义会白占约 26k tokens 的 prompt(实测 cache_write 139k→113k、快 8s)
        permission_mode="bypassPermissions",
        max_turns=12 if question else max_turns,
        env=CONFIG.claude_env(),
        thinking={"type": "adaptive"},  # 网关要求 adaptive(不再支持 thinking.type.enabled)
        # 完整复盘用 high:推理更稳(复跑结论更收敛)、属性归因更细;追问维持 medium 控成本
        effort="medium" if question else "high",
        cli_path=_CLI_PATH,  # 用系统新版 CLI(bundled 太老,--thinking adaptive 不生效)
    )

    if question:
        report_md = _load_report_md(date)
        bg = (
            f"以下是今日({date})已生成的复盘,请基于它回答用户追问,必要时再调工具补数据:\n\n"
            f"{report_md}\n\n---\n"
        ) if report_md else ""
        prompt = f"{bg}用户追问:{question}"
    else:
        prompt = (
            f"请对 {date} 的盘面做一次完整复盘,并给出明日四种风格的打板候选。"
            "先看情绪、梯队、板块热度、竞价高开、热门票K线量价,再基于截面数据做属性归因。"
        )

    parts: list[str] = []
    used: set[str] = set()
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
                        if on_text:
                            on_text(block.text)
                    elif isinstance(block, ToolUseBlock):
                        used.add(block.name.split("__")[-1])
                        if on_tool:
                            on_tool(block.name, block.input)
            elif isinstance(msg, ResultMessage):
                if on_usage:
                    on_usage(_extract_usage(msg))
                break

    if not question:  # 完整复盘要求调全工具(prompt 里也有门禁);缺了说明数据基础不完整,复跑会飘
        missing = REQUIRED_TOOLS - used
        if missing:
            log.warning("复盘 %s 漏调工具 %s(数据基础不完整,结论可复现性下降)", date, sorted(missing))
    return "".join(parts)


def _holding_detail(h: dict, date: str, pools: dict, themes: dict) -> dict:
    """单只持仓的分析素材:成本/盈亏 + 近日K线量价 + 涨停池截面(若有)+ 题材。"""
    from ..metrics.kline import build_hot_klines
    from ..metrics.ladder import stock_profiles

    code = h["code"]
    kl = build_hot_klines([{"code": code, "name": h.get("name", ""), "boards": 0, "turnover": None}], date)
    kline = kl[0] if kl else None
    prof = next((p for p in stock_profiles(pools["limitup"]) if p["code"] == code), None)
    cur = kline["bars"][-1] if kline and kline.get("bars") else None
    return {
        "code": code,
        "name": h.get("name", ""),
        "buy_price": h.get("buy_price"),
        "buy_boards": h.get("buy_boards"),
        "theme": themes.get(code, []),
        "profile": prof,  # 封单强度/首末封/炸板/换手/连板(在当日涨停池才有)
        "vol_trend": kline.get("vol_trend") if kline else None,
        "bars": kline.get("bars") if kline else [],  # 近日 K线量价特征
        "last_bar": cur,
    }


async def run_holding(
    holdings_info: list[dict],
    date: str,
    on_text: Callable[[str], None] | None = None,
    on_tool: Callable[[str, dict], None] | None = None,
    on_usage: Callable[[dict], None] | None = None,
    max_turns: int = 40,
) -> str:
    """持仓分析:注入持仓 detail + 挂大盘工具(情绪/板块/热门票风格),agent 给走势+买卖点。"""
    import json as _json

    from ..data import akshare_client as ak

    pools = load_pools(date)
    emotion = compute_emotion(pools)
    ladder = build_ladder(pools["limitup"])
    auction = auction_board(pools, date)
    themes = ak.ths_limitup_reasons(date)
    sector = {"industry": sector_heat(pools), "theme": theme_heat(pools, themes)}
    hot_klines = build_hot_klines(_hot_stocks(date, pools), date)  # 让 agent 感知当前风格/审美
    server, tool_names = make_server(date, emotion, ladder, sector, auction, hot_klines)

    details = [_holding_detail(h, date, pools, themes) for h in holdings_info]
    prompt = (
        f"以下是 {date} 收盘时的持仓(含成本/买入板数/近日K线量价/涨停池截面/题材),"
        "请逐只诊断、判断未来走势(T+1 + 短波段)并给出买卖点。可调工具看大盘情绪、板块题材、"
        "热门票K线以确认当前市场风格是否还认这些持仓:\n\n"
        f"{_json.dumps(details, ensure_ascii=False, indent=2)}"
    )

    options = ClaudeAgentOptions(
        model=CONFIG.claude_model,
        system_prompt=HOLDING_SYSTEM_PROMPT,
        allowed_tools=tool_names,
        mcp_servers={SERVER_NAME: server},
        permission_mode="bypassPermissions",
        max_turns=max_turns,
        env=CONFIG.claude_env(),
        thinking={"type": "adaptive"},  # 网关要求 adaptive(不再支持 thinking.type.enabled)
        effort="medium",
        cli_path=_CLI_PATH,  # 用系统新版 CLI(bundled 太老,--thinking adaptive 不生效)
    )

    parts: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
                        if on_text:
                            on_text(block.text)
                    elif isinstance(block, ToolUseBlock) and on_tool:
                        on_tool(block.name, block.input)
            elif isinstance(msg, ResultMessage):
                if on_usage:
                    on_usage(_extract_usage(msg))
                break
    return "".join(parts)


async def run_auction_brief(
    live: dict,
    on_usage: Callable[[dict], None] | None = None,
    max_turns: int = 2,
) -> str:
    """盘前竞价一段解读(9:25 用)。

    与复盘/持仓不同:**不挂工具**(数据直接塞进 prompt)、effort=low、max_turns=2 ——
    开盘前只剩几分钟,要的是几十秒出结果、成本远低于整篇复盘。返回纯文本(≤6 行)。
    """
    import json as _json

    payload = {
        "phase": live.get("phase"),
        "base_date": live.get("base_date"),
        "ts": live.get("ts"),
        "emotion_phase": live.get("emotion_phase"),
        "themes": live.get("themes", [])[:5],
        # 只喂前 12 只,省 token(已按高开降序)
        "rows": [
            {k: r.get(k) for k in (
                "code", "name", "prev_boards", "gap_pct", "gap_trend", "amount_yi",
                "seal_strength", "ref_price", "last_close", "grade", "theme", "in_candidates",
            )}
            for r in live.get("rows", [])[:12]
        ],
    }
    options = ClaudeAgentOptions(
        model=CONFIG.claude_model,
        system_prompt=AUCTION_BRIEF_PROMPT,
        permission_mode="bypassPermissions",
        max_turns=max_turns,
        env=CONFIG.claude_env(),
        thinking={"type": "adaptive"},
        effort="low",  # 盘前抢时间 + 控成本
        cli_path=_CLI_PATH,
    )
    prompt = (
        "以下是此刻的盘前竞价数据(题材聚合 + 个股榜),请按系统提示的格式给盘前决策:\n\n"
        + _json.dumps(payload, ensure_ascii=False, indent=1)
    )

    parts: list[str] = []
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt=prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                if on_usage:
                    on_usage(_extract_usage(msg))
                break
    return "".join(parts).strip()


def run_review_sync(date: str, question: str | None = None) -> str:
    """同步入口(CLI 用)。逐段打印工具调用与文本。"""
    def _tool(name, inp):
        short = name.split("__")[-1]
        print(f"  · 调用工具 {short}({inp or ''})")

    def _text(t):
        print(t, end="", flush=True)

    return asyncio.run(run_review(date, question, on_text=_text, on_tool=_tool))
