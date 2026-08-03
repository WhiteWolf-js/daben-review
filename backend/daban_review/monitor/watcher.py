"""盘中情绪监控常驻循环:交易时段轮询,命中情绪拐点事件即飞书通知。

    PYTHONPATH=. python -m daban_review.monitor.watcher          # 常驻监控
    PYTHONPATH=. python -m daban_review.monitor.watcher --once   # 跑一轮打印(自检,不通知)

同步轮询(单线程即够,无并发需求)。数据源全部复用 data 层;判据见 signals.py。
活跃时段(9:25–10:00 / 14:30–15:00)加密到 30s,其余按 MONITOR_INTERVAL(默认 60s)。
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import time

from ..config import CONFIG
from ..data import akshare_client as ak
from ..data import store
from ..data.fetch import _normalize
from . import signals
from .notify import send_lark

log = logging.getLogger(__name__)

# 交易时段边界
_OPEN = dt.time(9, 25)
_AM_CLOSE = dt.time(11, 30)
_PM_OPEN = dt.time(13, 0)
_CLOSE = dt.time(15, 0)
# 情绪最活跃、加密轮询的时段
_RUSH = [(dt.time(9, 25), dt.time(10, 0)), (dt.time(14, 30), dt.time(15, 0))]


def _in_session(t: dt.time) -> bool:
    return _OPEN <= t <= _AM_CLOSE or _PM_OPEN <= t <= _CLOSE


def _in_rush(t: dt.time) -> bool:
    return any(a <= t < b for a, b in _RUSH)


def poll_once(date: str) -> tuple[dict, dict]:
    """拉一轮实时数据 → (快照, 指数近N分钟跌幅)。单项失败不阻断整轮。"""
    ts = dt.datetime.now().strftime("%H:%M")

    limitup = _normalize("limitup", ak.zt_pool(date))  # 归一成英文列

    try:
        zbgc = len(ak.zt_zbgc(date))
    except Exception as e:  # noqa: BLE001
        log.warning("炸板池拉取失败: %s", e)
        zbgc = 0
    try:
        hot5 = [h["code"] for h in ak.hot_rank_top(5)]
    except Exception as e:  # noqa: BLE001
        log.warning("人气榜拉取失败: %s", e)
        hot5 = []

    snap = signals.build_snapshot(ts, limitup, zbgc, hot5)

    index_state: dict[str, float | None] = {}
    for code, name in ak.INDEX_CODES.items():
        try:
            index_state[name] = signals.index_drop_pct(ak.index_intraday_min(code, date))
        except Exception as e:  # noqa: BLE001
            log.warning("指数 %s 拉取失败: %s", name, e)
            index_state[name] = None
    return snap, index_state


def run(once: bool = False) -> None:
    date = dt.date.today().strftime("%Y%m%d")

    if once:
        snap, idx = poll_once(date)
        events = signals.detect_events(None, snap, idx, set())
        store.save_live(date, snap, idx, events)  # 写一轮供前端/接口验证
        print("快照:", {"ts": snap["ts"], "涨停": snap["zt_count"], "炸板": snap["zbgc_count"],
                        "最高板": snap["max_board"], "连板": snap["lianban_count"], "人气前5": snap["hot_top5"]})
        print("指数近15min跌幅:", idx)
        print("事件:", events or "(无,首轮无炸板对比)")
        print(f"已写库 live_snapshot/live_events(date={date})")
        return

    notify_on = bool(CONFIG.feishu_app_id and CONFIG.feishu_target)
    log.info("盘中监控启动 %s(飞书推送 %s)", date, "已配置" if notify_on else "未配置——只打日志")
    pushed: set[str] = set()
    prev: dict | None = None

    while True:
        now = dt.datetime.now().time()
        if now > _CLOSE:
            log.info("已收盘,监控结束(当日共推 %d 条)", len(pushed))
            break
        if not _in_session(now):
            time.sleep(30)
            continue
        try:
            snap, idx = poll_once(date)
            events = signals.detect_events(prev, snap, idx, pushed)
            for ev in events:
                pushed.add(ev["key"])
                log.info("命中事件: %s", ev["title"])
                if notify_on:
                    send_lark(f"{ev['title']}\n{ev['detail']}")
            store.save_live(date, snap, idx, events)  # 每轮写库,供前端只读
            prev = snap
        except Exception as e:  # noqa: BLE001 单轮失败不该让常驻循环崩掉
            log.error("轮询失败(跳过本轮): %s", e)
        time.sleep(30 if _in_rush(now) else CONFIG.monitor_interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="daban_review.monitor.watcher")
    ap.add_argument("--once", action="store_true", help="跑一轮打印(自检,不通知)")
    run(once=ap.parse_args().once)


if __name__ == "__main__":
    main()
