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
import os
import threading
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
# 看门狗强制退出点(收盘 +5min,给最后一轮留余量)
_HARD_STOP = dt.time(15, 5)


def _in_session(t: dt.time) -> bool:
    return _OPEN <= t <= _AM_CLOSE or _PM_OPEN <= t <= _CLOSE


def _in_rush(t: dt.time) -> bool:
    return any(a <= t < b for a, b in _RUSH)


# 交易日判定的生效时刻。**不能在启动时判** —— 通达信当日日线要开盘有成交才生成,
# 9:20 拉不到,那会儿判会把真交易日误杀。9:35 之后再判,之前照常轮询
# (9:25–9:35 恰好是竞价+开盘的关键窗口,不能为了判日历把它跳过)。
_TRADE_DAY_GUARD_AT = dt.time(9, 35)


def _is_trade_day(date: str, now: dt.time) -> bool | None:
    """今天是不是交易日。返回 None = 还判不出来(时候太早 / 拉取失败),调用方应继续等。

    没有可用的节假日日历:akshare 的 `tool_trade_date_hist_sina` 走 py_mini_racer,
    本机该库已坏(`dlsym: mr_eval_context symbol not found`)。所以用「通达信**当日**日线
    是否已生成」反推 —— 实测盘中 `daily_bars` 就带当天那根,而非交易日永远不会有。
    拉取异常一律返回 None(不当作非交易日),免得网络抖动把监控误杀。
    """
    if now < _TRADE_DAY_GUARD_AT:
        return None
    try:
        return date in ak.daily_bars("000001", 3)["date"].tolist()
    except Exception as e:  # noqa: BLE001
        log.warning("交易日判定失败(按未知处理,继续监控): %s", e)
        return None


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


def _watchdog(stop_at: dt.time = _HARD_STOP) -> None:
    """独立线程:到点无条件结束进程,不管主循环在干什么。

    主循环的 `now > _CLOSE` 判据只在每轮**开头**生效,而 `poll_once` 里的 try/except 只拦
    异常、拦不住「挂起」—— 一旦某个网络调用卡死,就再也回不到那个判据。实测 2026-09-11
    卡住后进程活了 5 天:不退出、不写日志;而 launchd 的 `StartCalendarInterval` 看见
    进程还在就不会重复拉起,于是 9/14、9/15、9/16 三个交易日整天没有盘中监控,直到人工发现。
    所以「停机」这件事不能交给主循环,必须由外部强制执行。

    用 `os._exit` 而不是 `sys.exit`:后者只是在看门狗自己这条线程里抛 SystemExit,
    卡死的主线程照样活着,进程还是不退 —— 那就白写了。
    """
    now = dt.datetime.now()
    wait = (dt.datetime.combine(now.date(), stop_at) - now).total_seconds()
    if wait <= 0:
        return  # 已过点(手动补跑),主循环自己会立刻 break,不用管
    time.sleep(wait)
    log.error("看门狗触发:%s 到点进程仍未退出(主循环疑似卡死),强制结束", stop_at.strftime("%H:%M"))
    # os._exit 不做任何清理,上面那行日志得自己刷出去。只 flush 不要 logging.shutdown():
    # 后者会**关闭**所有 handler,跑单测时 os._exit 被打桩、这行真的执行,会把 pytest
    # 自己的日志与报告机制一起关掉(现象:测试全绿但没有 summary、junit 文件也不生成)。
    for h in logging.getLogger().handlers:
        h.flush()
    os._exit(0)


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
    trade_day: bool | None = None  # 交易日判定结果,判出来一次就不再判

    while True:
        now = dt.datetime.now().time()
        if now > _CLOSE:
            log.info("已收盘,监控结束(当日共推 %d 条)", len(pushed))
            break
        if not _in_session(now):
            time.sleep(30)
            continue
        # 节假日 launchd 也会按周一至五把它拉起来,靠这里自己退出,免得整天空转
        # 并让前端实时条显示成「监控中」。
        if trade_day is None:
            trade_day = _is_trade_day(date, now)
            if trade_day is False:
                log.info("%s 不是交易日(通达信无当日数据),监控退出", date)
                break
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
    once = ap.parse_args().once
    # 看门狗装在 main 而不是 run:它干的是「结束这个进程」,是进程级的事。
    # 装进 run() 会让直接调 run() 的单测也起一条真会 os._exit 的线程 —— 测试里
    # time.sleep 常被打桩,于是它立刻把 pytest 打死(exit=0 但没有 summary,排查半天)。
    if not once:
        log.info("看门狗已装载:%s 强制退出", _HARD_STOP.strftime("%H:%M"))
        threading.Thread(target=_watchdog, name="watchdog", daemon=True).start()
    run(once=once)


if __name__ == "__main__":
    main()
