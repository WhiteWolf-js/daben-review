"""FastAPI 应用:REST(情绪/梯队/报告/序列)+ SSE(生成/追问)+ 盘后定时任务。"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agent.runner import run_review
from ..config import ROOT as CONFIG_ROOT
from . import service

log = logging.getLogger(__name__)
_scheduler = BackgroundScheduler()


def _daily_job() -> None:
    date = dt.date.today().strftime("%Y%m%d")
    log.info("盘后定时任务:强制重拉 + 生成 %s 复盘", date)
    try:
        service.refresh_day(date)  # 先强制拉收盘定格数据(避免用到盘中快照)
        asyncio.run(service.generate(date))
    except Exception as e:  # noqa: BLE001
        log.error("定时生成失败: %s", e)
        return
    # 复盘已存库,再出海报推飞书;此处失败不回滚复盘
    try:
        from . import poster

        r = poster.render_and_push(date)  # 复盘海报
        log.info("盘后复盘海报:path=%s pushed=%s", r["path"], r["pushed"])
        r2 = poster.render_and_push(date, kind="ladder")  # 连板天梯图
        log.info("盘后天梯图:path=%s pushed=%s", r2["path"], r2["pushed"])
    except Exception as e:  # noqa: BLE001
        log.error("盘后海报出图/推送失败: %s", e)


def _auction_job() -> None:
    """9:25:30 竞价定格后:agent 盘前解读 → 出图 → 推飞书(未配凭证则只落图)。"""
    date = dt.date.today().strftime("%Y%m%d")
    log.info("盘前竞价任务:出图 + 解读 %s", date)
    try:
        from . import poster

        r = poster.render_auction_and_push(date)
        log.info("盘前竞价海报:path=%s pushed=%s brief=%d字",
                 r["path"], r["pushed"], len(r.get("brief") or ""))
    except Exception as e:  # noqa: BLE001 盘前失败不该影响后续盘中/盘后任务
        log.error("盘前竞价出图/推送失败: %s", e)


def _warm_name_table() -> None:
    """后台预热全 A 名称表(持仓截图导入时按名称反查代码要用)。

    首次拉取约 10s,放到后台线程里,免得用户上传截图后干等;失败无所谓,真用到时会再拉一次。
    """
    import threading

    def run() -> None:
        try:
            from ..data.akshare_client import stock_name_map

            stock_name_map()
        except Exception as e:  # noqa: BLE001
            log.warning("名称表预热失败(用到时再拉): %s", e)

    threading.Thread(target=run, name="warm-name-table", daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 交易日 15:15 盘后自动生成(收盘后 15 分钟内推天梯图 + 复盘)
    _scheduler.add_job(_daily_job, "cron", day_of_week="mon-fri", hour=15, minute=15,
                       id="daily_review", replace_existing=True)
    # 交易日 9:25:30 竞价定格后出盘前决策图(开盘前几分钟能看到)
    _scheduler.add_job(_auction_job, "cron", day_of_week="mon-fri", hour=9, minute=25, second=30,
                       id="auction_brief", replace_existing=True)
    _scheduler.start()
    log.info("调度器启动:盘前 9:25:30 竞价决策图 + 盘后 15:15 天梯图+复盘")
    _warm_name_table()
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(title="打板情绪复盘", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # 本地开发 + 局域网手机访问:放开来源(无 credentials,* 合法)
    allow_origin_regex=r"http://[\w.\-]+:5173",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- REST ----

@app.get("/api/dates")
def dates():
    return {"dates": service.list_dates()}


@app.get("/api/emotion/{date}")
def emotion(date: str):
    return service.get_emotion(date)


@app.get("/api/ladder/{date}")
def ladder(date: str):
    return service.get_ladder(date)


@app.get("/api/ladder-board/{date}")
def ladder_board_ep(date: str):
    """天梯图数据:各档封住票 + 昨日连板今日断板票 + 行业分布(供天梯海报)。"""
    return service.get_ladder_board(date)


@app.get("/api/candidate-pool/{date}")
def candidate_pool(date: str, grades: str = "A+,A"):
    """四风格候选池的完整备选(默认只 A 级以上)+ 每只的板块联动。纯规则、零 token。

    前端「明日候选」只显示 agent 选的 rank1,这里给出 rank2-5 供展开。
    """
    gs = tuple(g.strip() for g in grades.split(",") if g.strip())
    return service.get_candidate_pool(date, gs or service._POOL_GRADES)


@app.get("/api/intraday-rotation/{date}")
def intraday_rotation(date: str):
    """盘中情绪切换:板块分时均涨幅曲线(大类/行业两个口径)+ 退潮/接棒配对 + 封板时序。

    首次算某一天要拉 200+ 只分时(约 15s),之后走库里缓存。
    """
    return service.get_intraday_rotation(date)


@app.get("/api/abnormal/{date}")
def abnormal(date: str, window: int = 10):
    """N 日累计涨幅异动榜(翻倍/两倍/进入异动区)。历史日走缓存,首次拉几百只日线约 30–90s。"""
    return service.get_abnormal_rank(date, window)


@app.get("/api/emotion-series")
def series(limit: int = 40):
    return {"series": service.emotion_series(limit)}


@app.get("/api/report/{date}")
def report(date: str):
    r = service.get_report(date)
    if not r:
        raise HTTPException(404, "该日期尚未生成复盘,请调 /api/generate 生成")
    return r


@app.get("/api/intraday/{code}/{date}")
def intraday(code: str, date: str):
    return service.get_intraday(code, date)


@app.get("/api/auction/{date}")
def auction(date: str):
    return service.get_auction(date)


@app.get("/api/auction-live")
def auction_live():
    """盘前竞价决策台:题材聚合(定方向)+ 个股竞价榜(高开/量能/趋势/分级)。

    phase: pre_cancel(9:15–9:20 可撤单,仅参考)/ bidding(9:20–9:25)/ opened(已定格)/ closed。
    """
    return service.get_auction_live()


@app.get("/api/auction-brief")
def auction_brief(date: str | None = None):
    """当日盘前 agent 解读(9:25:30 出图时生成并落库);未生成返回 {}。"""
    d = date or dt.date.today().strftime("%Y%m%d")
    return service.get_auction_brief(d) or {}


@app.post("/api/auction-poster")
def make_auction_poster(brief: bool = True, push: bool = False):
    """出盘前竞价决策图(brief=true 附 agent 一段解读;push=true 并推飞书)。"""
    from . import poster

    date = dt.date.today().strftime("%Y%m%d")
    return poster.render_auction_and_push(date, with_brief=brief, push=push)


@app.get("/api/candidates/{date}")
def candidates(date: str):
    return service.get_candidates(date)


@app.get("/api/candidates-stats")
def candidates_stats():
    return service.get_candidates_stats()


@app.get("/api/theme-heat/{date}")
def theme_heat_ep(date: str):
    return service.get_theme_heat(date)


@app.post("/api/refresh/{date}")
def refresh(date: str):
    return service.refresh_day(date)


@app.get("/api/live")
def live():
    """盘中实时监控:快照 + 事件流(watcher 写库;无 watcher 则 running=false)。"""
    return service.get_live()


@app.get("/api/usage-today")
def usage_today():
    """今日 agent 调用成本累计(复盘 + 持仓分析,官方单价估算)。"""
    return service.get_usage_today()


@app.post("/api/poster/{date}")
def make_poster(date: str, push: bool = False):
    """出复盘海报 PNG(Playwright 截前端 ?poster= 页);push=true 时并推飞书。"""
    from . import poster

    r = poster.render_and_push(date) if push else {"path": poster.render_poster(date), "pushed": False}
    if not r["path"]:
        raise HTTPException(500, "海报出图失败,检查 playwright 是否安装、frontend/dist 是否已构建")
    return r


@app.get("/api/poster/{date}")
def get_poster(date: str):
    """取已生成的海报图片文件(未生成返回 404)。"""
    from fastapi.responses import FileResponse

    from . import poster

    p = poster.poster_path(date)
    if not p.exists():
        raise HTTPException(404, "尚未生成该日海报,请先 POST /api/poster/{date}")
    return FileResponse(str(p), media_type="image/png", filename=p.name)


# ---- 持仓 ----

class HoldingBody(BaseModel):
    code: str
    name: str = ""
    buy_date: str = ""
    buy_price: float
    buy_boards: int = 0
    note: str = ""
    shares: int = 0


@app.get("/api/holdings")
def holdings():
    return service.list_holdings()


@app.post("/api/holdings")
def add_holding(body: HoldingBody):
    service.add_holding(body.code, body.name, body.buy_date, body.buy_price, body.buy_boards,
                       body.note, body.shares)
    return {"ok": True}


@app.delete("/api/holdings/{code}")
def del_holding(code: str):
    service.delete_holding(code)
    return {"ok": True}


# 持仓截图导入:识别(不入库,前端勾选)→ 批量入库
_OCR_MAX_B64 = 10 * 1024 * 1024  # base64 长度上限 ≈ 7.5MB 原图,手机截图远低于此


class HoldingOcrBody(BaseModel):
    image_base64: str
    media_type: str = "image/png"
    date: str = ""


class HoldingsBulkBody(BaseModel):
    items: list[HoldingBody]


@app.post("/api/holdings/ocr")
def holdings_ocr(body: HoldingOcrBody):
    """券商持仓截图 → 候选持仓行(含 exists/买入板数/买入日),**不落库**,由前端勾选后再提交。"""
    from ..agent.vision import ALLOWED_MEDIA

    if not body.image_base64:
        raise HTTPException(status_code=400, detail="缺少图片")
    if len(body.image_base64) > _OCR_MAX_B64:
        raise HTTPException(status_code=413, detail="图片过大(请压缩到 7MB 以内)")
    if body.media_type not in ALLOWED_MEDIA:
        raise HTTPException(status_code=415, detail=f"不支持的图片类型:{body.media_type}")
    try:
        return service.ocr_holdings(body.image_base64, body.media_type, body.date)
    except RuntimeError as e:  # 网关报错/未配置 → 502,前端提示可改手动录入
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/holdings/bulk")
def holdings_bulk(body: HoldingsBulkBody):
    n = service.add_holdings_bulk([it.model_dump() for it in body.items])
    return {"added": n}


class HoldingAnalyzeBody(BaseModel):
    date: str
    codes: list[str] = []  # 多选:一次分析多只(agent 能横向比较谁先减、谁还能拿)
    code: str = ""  # 兼容单票老调用;codes 为空时用它


@app.post("/api/holdings/analyze")
def holding_analyze(body: HoldingAnalyzeBody):
    codes = [c for c in (body.codes or ([body.code] if body.code else [])) if c]
    if not codes:
        raise HTTPException(status_code=400, detail="请至少选一只持仓")

    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        usage_holder: dict = {}

        def on_text(t: str):
            queue.put_nowait(t)

        def on_usage(u: dict):
            usage_holder.update(u)

        async def run():
            try:
                await service.analyze_holdings(codes, body.date, on_text=on_text, on_usage=on_usage)
            except Exception as e:  # noqa: BLE001
                queue.put_nowait(f"\n\n[分析出错] {e}")
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(run())
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps({'message': item, 'end': False}, ensure_ascii=False)}\n\n"
        cost = _finalize_usage(body.date, "holding", usage_holder, code=",".join(codes))
        yield f"data: {json.dumps({'end': True, 'usage': cost}, ensure_ascii=False)}\n\n"
        await task

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/holdings/{code}/analysis")
def holding_analysis_get(code: str):
    return service.get_holding_analysis(code) or {}


# ---- SSE ----

class GenBody(BaseModel):
    date: str


class ChatBody(BaseModel):
    date: str
    question: str


def _finalize_usage(date: str, kind: str, usage_holder: dict, code: str = "") -> dict | None:
    """把 runner 回传的原始 usage 算成本 + 落库,返回本次成本 dict(供 end 帧;无用量则 None)。"""
    if not usage_holder:
        return None
    from ..agent import pricing

    cost = pricing.compute_cost(usage_holder.get("usage"), usage_holder.get("total_cost_usd"))
    try:
        service.record_usage(date, kind, cost, code)
    except Exception as e:  # noqa: BLE001 落库失败不该阻断流返回
        log.error("usage 落库失败: %s", e)
    return cost


def _sse_response(date: str, question: str | None, persist: bool) -> StreamingResponse:
    kind = "chat" if question else "review"

    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        parts: list[str] = []
        usage_holder: dict = {}

        def on_text(t: str):
            parts.append(t)
            queue.put_nowait(t)

        def on_usage(u: dict):
            usage_holder.update(u)

        async def run():
            try:
                await run_review(date, question, on_text=on_text, on_usage=on_usage)
            except Exception as e:  # noqa: BLE001
                queue.put_nowait(f"\n\n[分析出错] {e}")
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(run())
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps({'message': item, 'end': False}, ensure_ascii=False)}\n\n"
        cost = _finalize_usage(date, kind, usage_holder)
        yield f"data: {json.dumps({'end': True, 'usage': cost}, ensure_ascii=False)}\n\n"
        await task
        if persist and "".join(parts).strip():
            service.save_report(date, "".join(parts))

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/generate")
def generate(body: GenBody):
    """流式生成当日复盘并存库(前端可看 agent 逐字输出)。"""
    return _sse_response(body.date, None, persist=True)


@app.post("/api/chat")
def chat(body: ChatBody):
    """基于当日数据的对话式追问,流式返回,不存库。"""
    return _sse_response(body.date, body.question, persist=False)


# ---- 前端静态产物(必须在所有 /api 路由之后 mount,否则 / 会盖掉 API)----
# 后端自己 serve dist,海报出图便无需前端 dev server 在跑;dist 不存在时静默跳过。
_DIST = CONFIG_ROOT / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
    log.info("已挂载前端产物: %s", _DIST)
else:
    log.info("未找到 frontend/dist(海报出图需先 npm run build)")
