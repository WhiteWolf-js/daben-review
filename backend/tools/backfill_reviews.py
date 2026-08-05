"""批量回补历史复盘:对缺复盘的交易日跑 agent 并**落库**,把候选样本攒起来。

为什么不用 `cli analyze`:那条只流式打印、**不写 review_report/candidates/usage_log**
(踩过:跑完一天发现库里什么都没有)。落库要走 `service.save_report`。

    PYTHONPATH=. python3 tools/backfill_reviews.py --dry-run       # 只列要跑哪些天
    PYTHONPATH=. python3 tools/backfill_reviews.py --limit 1       # 先跑一天量成本
    PYTHONPATH=. python3 tools/backfill_reviews.py                 # 跑完所有缺的
    PYTHONPATH=. python3 tools/backfill_reviews.py --redo          # 连已有复盘的也重跑(会覆盖)

默认**只补缺的**,不动已有复盘 —— 已有的那批是 Opus 产出的,用 Sonnet 重跑会拿质量换一致性,
除非明确 --redo。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
import time

from daban_review.agent import pricing
from daban_review.agent.runner import run_review
from daban_review.app import service
from daban_review.config import CONFIG
from daban_review.data import store


def _dates(redo: bool) -> list[str]:
    conn = store.get_conn()
    lim = sorted(r[0] for r in conn.execute("SELECT DISTINCT date FROM daily_limitup"))
    done = {r[0] for r in conn.execute("SELECT date FROM review_report")}
    conn.close()
    return lim if redo else [d for d in lim if d not in done]


def _record_usage(date: str, raw: dict) -> dict | None:
    """与 main._finalize_usage 同口径:算成本 + 落 usage_log。"""
    if not raw:
        return None
    cost = pricing.compute_cost(raw.get("usage") or {}, raw.get("total_cost_usd"))
    try:
        store.save_usage(date, "review", cost)
    except Exception as e:  # noqa: BLE001 记账失败不该丢掉已生成的复盘
        print(f"    ⚠️ usage 落库失败: {e}")
    return cost


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--redo", action="store_true", help="已有复盘的也重跑(覆盖)")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 天(先量成本用)")
    a = ap.parse_args()

    todo = _dates(a.redo)
    if a.limit:
        todo = todo[: a.limit]
    print(f"模型 {CONFIG.claude_model} | 待跑 {len(todo)} 天: {todo}")
    if a.dry_run or not todo:
        return

    t0, ok, fail, cny = time.time(), 0, 0, 0.0
    for i, d in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {d} 生成中…", flush=True)
        holder: dict = {}
        try:
            t = time.time()
            md = asyncio.run(run_review(d, on_usage=holder.update))
            service.save_report(d, md)
            cost = _record_usage(d, holder)
            c = (cost or {}).get("cost_cny") or 0
            cny += c
            conn = store.get_conn()
            n = conn.execute("SELECT COUNT(*) FROM candidates WHERE date=?", (d,)).fetchone()[0]
            conn.close()
            ok += 1
            print(f"    ✓ {time.time()-t:.0f}s | 正文 {len(md)} 字 | 候选 {n} 条 | ¥{c:.2f}", flush=True)
        except Exception as e:  # noqa: BLE001 单日失败不中断整批
            fail += 1
            print(f"    ✗ 失败: {type(e).__name__}: {e}", flush=True)

    print(f"\n完成 {ok} 天 / 失败 {fail} 天 | 总耗时 {(time.time()-t0)/60:.1f} 分 | 总成本 ¥{cny:.2f}"
          f" | 均 ¥{cny/ok:.2f}/天" if ok else "")


if __name__ == "__main__":
    sys.exit(main())
