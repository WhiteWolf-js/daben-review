"""复盘海报出图:Playwright 打开前端海报页(?poster=日期)截图成 PNG。

排版不在后端重写——直接截前端 PosterView 组件渲染的页面,与手动导出共用同一套样式。
依赖:①`pip install playwright`(不必 `playwright install`,用 channel="chrome" 复用系统 Chrome)
     ②前端已 `npm run build`(main.py 把 frontend/dist 挂在 / 上供访问)

任何一环缺失都返回 None 并记日志,不抛异常——盘后定时任务里出图失败不该影响已存库的复盘。
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import CONFIG, DATA_DIR

log = logging.getLogger(__name__)

POSTER_DIR = DATA_DIR / "posters"
_READY = '[data-poster-root="1"][data-poster-ready="1"]'


_KIND_NAME = {"review": "复盘", "auction": "盘前竞价", "ladder": "连板天梯", "holding": "持仓处置", "album": "图集"}
# 天梯图首板档要排 8 列,比复盘/竞价海报宽(与 LadderPoster.LADDER_WIDTH 对齐)
# 持仓处置图 1080 宽(HoldingPoster.HOLDING_WIDTH),默认 1200 视口够用,不必单列
# 图集卡片 1080 宽(AlbumPoster.ALBUM_W),1200 视口够用
_KIND_VIEWPORT = {"ladder": 1400}


def poster_path(date: str, kind: str = "review") -> Path:
    return POSTER_DIR / f"{_KIND_NAME.get(kind, '盘前竞价')}_{date}.png"


def render_poster(
    date: str,
    out_path: str | Path | None = None,
    kind: str = "review",
    brief: str = "",
) -> str | None:
    """把海报截成 PNG,返回文件路径;失败返回 None。

    kind="review" 截复盘海报(?poster=date);kind="auction" 截盘前竞价海报
    (?poster=date&kind=auction&brief=agent解读);kind="ladder" 截连板天梯图;
    kind="holding" 截持仓处置速览图。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("未安装 playwright,无法出图(pip install playwright)")
        return None

    out = Path(out_path) if out_path else poster_path(date, kind)
    out.parent.mkdir(parents=True, exist_ok=True)
    url = f"{CONFIG.poster_base_url}/?poster={date}"
    if kind == "auction":
        from urllib.parse import quote

        url += f"&kind=auction&brief={quote(brief)}"
    elif kind in ("ladder", "holding"):
        url += f"&kind={kind}"

    try:
        with sync_playwright() as p:
            # channel="chrome" 复用系统已装 Chrome,省去下载 chromium
            browser = p.chromium.launch(channel="chrome")
            try:
                width = _KIND_VIEWPORT.get(kind, 1200)  # 视口窄于海报会触发换行/裁切
                page = browser.new_page(viewport={"width": width, "height": 1400}, device_scale_factor=2)
                page.goto(url, timeout=CONFIG.poster_timeout_ms)
                # 等数据拉齐(PosterView 在全部请求 settle 后置 data-poster-ready=1)
                page.wait_for_selector(_READY, timeout=CONFIG.poster_timeout_ms)
                page.locator('[data-poster-root="1"]').screenshot(path=str(out))
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001 出图失败不该冒泡到定时任务
        log.error("海报出图失败(%s): %s", url, e)
        return None

    log.info("海报已生成: %s", out)
    return str(out)


def render_album(date: str, out_dir: str | Path | None = None) -> list[str]:
    """抖音图集:遍历 ``[data-poster-card]`` 逐张截图,返回 PNG 路径列表。

    输出 ``图集_<date>_1.png .. _N.png``(每张 1080×1440 @2x = 2160×2880,3:4 竖屏)。
    前端 ``?poster=<date>&kind=album`` 渲染 AlbumPoster,每张卡片打 data-poster-card。
    与 render_poster 不同:这里截多个 card 元素而非单个 root,返回路径列表。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("未安装 playwright,无法出图(pip install playwright)")
        return []

    out_d = Path(out_dir) if out_dir else POSTER_DIR
    out_d.mkdir(parents=True, exist_ok=True)
    url = f"{CONFIG.poster_base_url}/?poster={date}&kind=album"
    paths: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            try:
                # 视口宽 ≥ 1080(卡片宽);高 1600 留足单卡渲染(卡片 1440 高)
                page = browser.new_page(
                    viewport={"width": 1200, "height": 1600}, device_scale_factor=2
                )
                page.goto(url, timeout=CONFIG.poster_timeout_ms)
                page.wait_for_selector(_READY, timeout=CONFIG.poster_timeout_ms)
                cards = page.locator('[data-poster-card]')
                n = cards.count()
                if n == 0:
                    log.error("图集未找到卡片(data-poster-card):%s", url)
                    return []
                for i in range(n):
                    out = out_d / f"图集_{date}_{i + 1}.png"
                    cards.nth(i).screenshot(path=str(out))
                    paths.append(str(out))
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        log.error("图集出图失败(%s): %s", url, e)
        return []

    log.info("图集已生成 %d 张: %s", len(paths), paths)
    return paths


def render_and_push(date: str, kind: str = "review") -> dict:
    """出图并推飞书(盘后定时任务与手动接口共用)。返回 {path, pushed}。

    kind="review" 复盘海报;kind="ladder" 连板天梯图;kind="auction" 盘前竞价(走 render_auction_and_push)。
    """
    from ..monitor.notify import send_lark_image

    path = render_poster(date, kind=kind)
    if not path:
        return {"path": None, "pushed": False}
    return {"path": path, "pushed": send_lark_image(path)}


def render_auction_and_push(date: str, with_brief: bool = True, push: bool = True) -> dict:
    """盘前竞价:(可选)agent 解读 → 出图 → 推飞书。返回 {path, pushed, brief, cost}。

    解读失败不阻断出图(图本身已有方向/标的/评级);推送未配凭证时只落图。
    """
    import asyncio

    from ..monitor.notify import send_lark_image
    from . import service

    brief, cost = "", None
    if with_brief:
        try:
            from ..agent import pricing
            from ..agent.runner import run_auction_brief

            live = service.get_auction_live()
            usage: dict = {}
            brief = asyncio.run(run_auction_brief(live, on_usage=usage.update))
            service.save_auction_brief(date, brief)  # 存一份供前端盘前视图读(不然只进了海报就扔)
            if usage:
                cost = pricing.compute_cost(usage.get("usage"), usage.get("total_cost_usd"))
                service.record_usage(date, "auction", cost)
        except Exception as e:  # noqa: BLE001 解读失败仍出图
            log.error("盘前解读失败(仍出图): %s", e)

    path = render_poster(date, kind="auction", brief=brief)
    if not path:
        return {"path": None, "pushed": False, "brief": brief, "cost": cost}
    pushed = send_lark_image(path) if push else False
    return {"path": path, "pushed": pushed, "brief": brief, "cost": cost}
