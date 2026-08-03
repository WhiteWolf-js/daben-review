"""in-process MCP 工具:把当日情绪骨架/梯队/板块热度(行业+题材)/竞价/热门票K线暴露给 agent。

设计:各类截面指标在起 agent 前预算好,由闭包捕获(避免 agent 每次调工具都重拉数据)。
盘中分钟级分时不进 agent(改前端人工点击);日 K 线形态/量价进 agent,用于风格与周期感知。
"""

from __future__ import annotations

import json

from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool

SERVER_NAME = "daban"


def _ok(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


def make_server(
    date: str,
    emotion: dict,
    ladder: dict,
    sector: dict,
    auction: list,
    hot_klines: list,
    candidate_pool: dict | None = None,
):
    """构造当日 in-process MCP server;各指标已预算好,闭包捕获。

    签名须与 runner.run_review 的调用一致:(date, emotion, ladder, sector, auction, hot_klines,
    candidate_pool)。sector 为 {"industry": [...], "theme": [...]}(行业维度 + 题材维度);
    candidate_pool 为 metrics.build_candidate_pool 的输出(四风格可选池,agent 只能在池内选)。
    """

    @sdk_tool(
        "get_market_emotion",
        "获取当日市场情绪骨架:涨停/连板家数、最高板、晋级率、炸板率、赚钱效应、"
        "情绪周期与市场状态的规则初判。分析盘面应先调此工具。",
        {"type": "object", "properties": {}},
    )
    async def get_market_emotion(args):
        return _ok({"date": date, **emotion})

    @sdk_tool(
        "get_limitup_ladder",
        "获取当日连板天梯:按连板数分档的涨停个股,含封单强度(封板资金/流通市值)、"
        "首末封时间、炸板次数、换手率、所属行业。用于看梯队结构和挑重点票。",
        {"type": "object", "properties": {}},
    )
    async def get_limitup_ladder(args):
        return _ok({"date": date, "ladder": {str(k): v for k, v in ladder.items()}})

    @sdk_tool(
        "get_sector_heat",
        "获取当日板块热度,含两个维度:industry(行业,稳定分类)与 theme(题材=同花顺涨停原因,"
        "多属性、当日炒作主线,如存储芯片/人形机器人/先进封装)。用于判断资金主攻方向、"
        "题材主线、以及属性对立与联动。一只票可同属多个题材(多属性载体)。",
        {"type": "object", "properties": {}},
    )
    async def get_sector_heat(args):
        return _ok({"date": date, "sector": sector})

    @sdk_tool(
        "get_auction",
        "获取当日盘前竞价高开抢筹榜:连板与首板重点票的竞价高开幅度、成交额,"
        "用于判断次日情绪承接与资金抢筹强度。",
        {"type": "object", "properties": {}},
    )
    async def get_auction(args):
        return _ok({"date": date, "auction": auction})

    @sdk_tool(
        "get_hot_klines",
        "获取市场热度前 20 只票(人气榜,含涨停/炸板/高位分歧票)的近 12 日 K 线量价特征:"
        "每日 pct(涨跌%)/amp(振幅%)/vr(量比=当日量/近5日均量,代理换手活跃度)/pos(收盘位置)/"
        "tag(缩量涨停/放量涨停/一字/冲高回落…),外加 vol_trend(量能梯度)与当日换手率。"
        "用于感知【当前资金审美】(强势票共性形态=风格指纹)与【量价周期】"
        "(主升期中军放量接力 / 高潮天量分歧 / 冰点缩量一字或断板)。判断市场风格时调用。",
        {"type": "object", "properties": {}},
    )
    async def get_hot_klines(args):
        return _ok({"date": date, "hot_klines": hot_klines})

    @sdk_tool(
        "get_candidate_pool",
        "获取【四风格候选池】——系统已用客观因子(封流比/首封时间/炸板/换手/身位 + 情绪周期基准)"
        "对全梯队打分并按确定性规则排好序,每种风格给出 rank1..N 的可选标的,含 score/grade/"
        "position/reasons 与 price(当日涨停价,用于推算次日触发价)。"
        "输出候选票【只能从本池内选】,默认取每风格 rank1;要越级选 rank2+ 必须写明理由。"
        "给候选前必须调用此工具。",
        {"type": "object", "properties": {}},
    )
    async def get_candidate_pool(args):
        return _ok({"date": date, **(candidate_pool or {"pool": {}})})

    server = create_sdk_mcp_server(
        name=SERVER_NAME,
        version="1.0.0",
        tools=[get_market_emotion, get_limitup_ladder, get_sector_heat, get_auction,
               get_hot_klines, get_candidate_pool],
    )
    tool_names = [
        f"mcp__{SERVER_NAME}__get_market_emotion",
        f"mcp__{SERVER_NAME}__get_limitup_ladder",
        f"mcp__{SERVER_NAME}__get_sector_heat",
        f"mcp__{SERVER_NAME}__get_auction",
        f"mcp__{SERVER_NAME}__get_hot_klines",
        f"mcp__{SERVER_NAME}__get_candidate_pool",
    ]
    return server, tool_names
