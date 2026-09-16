"""交互式飞书机器人:私聊发指令查盘 + 自由提问。

    PYTHONPATH=. python -m daban_review.monitor.bot              # 常驻(WebSocket 长连接)
    PYTHONPATH=. python -m daban_review.monitor.bot --once "候选"  # 离线自检,不连飞书

走 `lark.ws.Client` 长连接(自带断线重连),**不需要公网回调地址**。
飞书侧前置:应用加「机器人」能力 + 事件订阅选「长连接接收」+ 订阅 im.message.receive_v1,并重新发布版本。

指令(读库、零 token):复盘 / 候选 / 情绪 / 持仓 / 帮助;其余文本 → agent 自由提问(1-2 分钟)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import threading

from ..config import CONFIG
from . import bot_commands as bc
from .notify import send_lark, send_lark_image

log = logging.getLogger(__name__)

# agent 同时只跑一个:连发几条会抢 claude CLI 也烧钱
_agent_lock = threading.Lock()
# 出图同时只跑一个:每次都要起一个 Chrome,连点几次会堆进程
_render_lock = threading.Lock()


def _allowed(open_id: str) -> bool:
    """白名单校验。留空时一律拒绝(只记日志)——防止应用被拉进任何会话就能烧 token。"""
    allow = {x.strip() for x in CONFIG.feishu_bot_allow.split(",") if x.strip()}
    if not allow:
        log.warning("FEISHU_BOT_ALLOW 未配置,拒绝回复。把这个 open_id 填进 .env 即可:%s", open_id)
        return False
    return open_id in allow


def _run_render(date: str, chat_id: str, which: str = "review") -> None:
    """出图并发送。**必须在独立线程里跑**:ws 回调运行在 asyncio 事件循环内,
    而 poster 用的是 Playwright 同步 API,在运行中的 loop 里会直接报
    「Sync API inside the asyncio loop」。新线程没有 running loop,才能用。
    """
    from ..app import poster, service

    if not _render_lock.acquire(blocking=False):
        send_lark("上一张图还在出,稍等 🙏", target=chat_id)
        return
    try:
        # 竞价图不带 agent 解读(with_brief 会调 agent 烧钱);已落库的解读走「竞价」文本指令看
        kind = which if which in ("auction", "ladder", "holding", "report") else "review"
        path = poster.render_poster(date, kind=kind)
        if path:
            if send_lark_image(path, target=chat_id):
                return
            # 图推不出去也别让用户空手 —— 最常见原因是应用缺 im:resource:upload 权限
            # (发文字的权限和发图的是两套,文字通不代表图能通)。有文本版的就退回文本。
            log.warning("图片推送失败,退回文本: %s", path)
            fb = {
                "holding": bc.fmt_holdings,
                "ladder": lambda: bc.fmt_ladder(date),
                "report": lambda: bc.fmt_report_text(date),
            }.get(kind)
            send_lark(
                f"{fb()}\n\n(图没推成:应用可能缺 im:resource:upload 权限,已退回文本)"
                if fb
                else f"{date} 图出好了但推送失败(应用可能缺 im:resource:upload 权限)。图在:{path}",
                target=chat_id,
            )
            return
        # 出图失败:分清「没复盘」和「技术故障」,别一律甩锅给没生成
        if which in ("review", "report") and not service.get_report(date):
            send_lark(f"{date} 还没生成复盘,先在网页端生成(或等盘后 15:30 自动跑)。", target=chat_id)
        else:
            send_lark(f"{date} 出图失败了。查 data/logs/bot.log 里的 poster 报错。", target=chat_id)
    except Exception as e:  # noqa: BLE001
        log.exception("出图失败")
        send_lark(f"出图出错了:{type(e).__name__} {e}"[:300], target=chat_id)
    finally:
        _render_lock.release()


def _run_agent(question: str, date: str, chat_id: str) -> None:
    """跑 agent 自由提问(耗时 1-2 分钟)。先回执由调用方发,这里只发结果。"""
    from ..agent import pricing
    from ..agent.runner import run_review
    from ..app import service

    if not _agent_lock.acquire(blocking=False):
        send_lark("上一个问题还在分析中,等它出结果再问 🙏", target=chat_id)
        return
    try:
        usage: dict = {}
        answer = asyncio.run(run_review(date, question=question, on_usage=usage.update))
        send_lark(answer.strip() or "(agent 没有返回内容)", target=chat_id)
        if usage:  # 成本记账,与网页端同一口径
            try:
                cost = pricing.compute_cost(usage.get("usage"), usage.get("total_cost_usd"))
                service.record_usage(date, "chat", cost)
                log.info("追问成本 ¥%.2f", cost.get("cost_cny", 0))
            except Exception as e:  # noqa: BLE001 记账失败不影响已发出的答案
                log.error("成本记账失败: %s", e)
    except Exception as e:  # noqa: BLE001 别让异常静默吞掉,用户在等回复
        log.exception("agent 提问失败")
        send_lark(f"分析出错了:{type(e).__name__} {e}"[:300], target=chat_id)
    finally:
        _agent_lock.release()


def dispatch(text: str, chat_id: str) -> None:
    """执行一条指令并回复。异常一律回一句人话,不静默死掉。"""
    try:
        act = bc.handle_command(text)
    except Exception as e:  # noqa: BLE001
        log.exception("指令解析/渲染失败: %s", text)
        send_lark(f"处理出错了:{type(e).__name__} {e}"[:300], target=chat_id)
        return

    kind = act["kind"]
    if kind == "text":
        send_lark(act["content"], target=chat_id)
    elif kind == "image":
        send_lark("🖼 正在出图,约 10 秒…", target=chat_id)
        threading.Thread(
            target=_run_render, args=(act["date"], chat_id, act.get("which", "review")),
            daemon=True, name="bot-render",
        ).start()
    elif kind == "ask":
        # 回执里标明代价:这是唯一花钱的路径,别让人不知不觉烧
        send_lark(f"🤔 正在基于 {act['date']} 盘面深度分析,约 1-2 分钟、约 ¥8…", target=chat_id)
        threading.Thread(
            target=_run_agent, args=(act["question"], act["date"], chat_id),
            daemon=True, name="bot-agent",
        ).start()


def _on_message(data) -> None:
    """im.message.receive_v1 回调。只处理私聊文本。"""
    try:
        ev = data.event
        msg = ev.message
        open_id = getattr(getattr(ev.sender, "sender_id", None), "open_id", "") or ""
        chat_id = msg.chat_id
        chat_type = getattr(msg, "chat_type", "")
        if msg.message_type != "text":
            send_lark("目前只认文本消息,发「帮助」看指令。", target=chat_id)
            return
        text = json.loads(msg.content or "{}").get("text", "").strip()
        log.info("收到消息 chat_type=%s open_id=%s text=%r", chat_type, open_id, text)

        if not _allowed(open_id):
            return
        if chat_type != "p2p":  # 只私聊(群聊需 @解析 + 群白名单,本期不做)
            log.info("忽略非私聊消息(chat_type=%s)", chat_type)
            return
        dispatch(text, chat_id)
    except Exception:  # noqa: BLE001 回调里抛异常会被 SDK 吞掉,这里必须自己记
        log.exception("处理消息事件失败")


def run() -> None:
    import lark_oapi as lark

    if not (CONFIG.feishu_app_id and CONFIG.feishu_app_secret):
        log.error("缺 FEISHU_APP_ID/SECRET,无法启动机器人")
        return
    if not CONFIG.feishu_bot_allow:
        log.warning("FEISHU_BOT_ALLOW 为空:机器人会收消息但不回复,"
                    "先发一条消息、从日志里拿到 open_id 填进 .env 再重启")

    handler = (
        lark.EventDispatcherHandler.builder("", "")  # 长连接模式不校验 token/encrypt_key
        .register_p2_im_message_receive_v1(_on_message)
        .build()
    )
    client = lark.ws.Client(
        app_id=CONFIG.feishu_app_id,
        app_secret=CONFIG.feishu_app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    log.info("飞书机器人启动(长连接),白名单 %d 个", len(
        [x for x in CONFIG.feishu_bot_allow.split(",") if x.strip()]))
    client.start()  # 阻塞,自带重连


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="daban_review.monitor.bot")
    ap.add_argument("--once", metavar="TEXT", help="离线自检:执行一条指令并打印结果,不连飞书")
    args = ap.parse_args()

    if args.once:
        act = bc.handle_command(args.once)
        print(f"[kind={act['kind']}]")
        if act["kind"] == "text":
            print(act["content"])
        elif act["kind"] == "image":
            # 必须打 which:五种图都走同一个 kind=image,不打出来自检等于没检
            print(f"→ 会出图并推送:date={act['date']} which={act.get('which')}")
        else:
            print(f"→ 会走 agent 提问:date={act['date']} question={act['question']!r}")
        return
    run()


if __name__ == "__main__":
    main()
