"""M1 验证 CLI:拉取并打印指定交易日的情绪骨架与连板天梯,人工对照东财/问财。

用法:
    python -m daban_review.cli review 20260721
    python -m daban_review.cli emotion 20260721
    python -m daban_review.cli ladder 20260721
    python -m daban_review.cli backtest        # 用库内历史校准评分因子(不拉当日、不花 token)
不带日期默认今天。
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging

from .data.fetch import fetch_day
from .metrics import build_ladder, compute_emotion


def _today() -> str:
    return dt.date.today().strftime("%Y%m%d")


def _print_emotion(m: dict) -> None:
    print("\n=== 情绪面板 ===")
    rows = [
        ("涨停家数", m["zt_count"]),
        ("连板家数(≥2)", m["lianban_count"]),
        ("最高连板", m["max_board"]),
        ("炸板家数", m["zbgc_count"]),
        ("跌停家数", m["dt_count"]),
        ("封板成功率", f"{m['seal_success_rate']:.1%}"),
        ("炸板率", f"{m['break_rate']:.1%}"),
        ("赚钱效应(昨涨停今均涨)", m["money_effect"]),
        ("1进2晋级率", _fmt_rate(m.get("promo_1to2"))),
        ("高位晋级率(≥2板)", _fmt_rate(m.get("promo_high"))),
        ("总晋级率", _fmt_rate(m.get("promo_overall"))),
        ("连板高度分布", m["height_dist"]),
        ("情绪周期(粗判)", m["phase_hint"]),
        ("市场状态(粗判)", m["market_state_hint"]),
    ]
    for k, v in rows:
        print(f"  {k:<22}: {v}")


def _fmt_rate(v) -> str:
    return f"{v:.1%}" if isinstance(v, (int, float)) else "—"


def _print_ladder(ladder: dict) -> None:
    print("\n=== 连板天梯 ===")
    for board, stocks in ladder.items():
        tag = f"{board}板" if board >= 1 else "首板"
        names = "、".join(
            f"{s['name']}({s['seal_strength']:.2%})" for s in stocks[:12]
        )
        more = f" …+{len(stocks) - 12}" if len(stocks) > 12 else ""
        print(f"  [{tag}] x{len(stocks)}: {names}{more}")
    print("  (括号内为封单强度 = 封板资金/流通市值)")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="daban_review")
    p.add_argument("cmd", choices=["review", "emotion", "ladder", "fetch", "analyze", "backtest"])
    p.add_argument("date", nargs="?", default=_today(), help="YYYYMMDD,默认今天")
    args = p.parse_args()

    if args.cmd == "backtest":
        from .metrics.backtest import collect, format_report  # 延迟导入
        print("回测中(读库 + mootdx 日线,不拉当日、不花 token)…\n")
        print(format_report(collect()))
        return

    if args.cmd == "analyze":
        from .agent.runner import run_review_sync  # 延迟导入,避免拖慢纯数据命令
        print(f"agent 分析 {args.date} 中(自主调工具,稍候)…\n")
        run_review_sync(args.date)
        print()
        return

    print(f"拉取 {args.date} …(串行降频,稍候)")
    pools = fetch_day(args.date, persist=True)
    print("各池行数:", {k: len(v) for k, v in pools.items()})

    if args.cmd in ("review", "emotion"):
        _print_emotion(compute_emotion(pools))
    if args.cmd in ("review", "ladder"):
        _print_ladder(build_ladder(pools["limitup"]))


if __name__ == "__main__":
    main()
