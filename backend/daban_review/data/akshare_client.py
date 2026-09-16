"""akshare 封装:统一节流 + 重试,规避东财 push2 端点限频。

只在盘后一次性拉取,串行调用,每次成功后 sleep(throttle)。
push2ex 端点(涨停池系列)基本不限频;push2 端点(板块/资金流)限频严重,重试+退避兜底。
"""

import logging
import re
import time

import akshare as ak
import pandas as pd
import requests

from ..config import CONFIG

log = logging.getLogger(__name__)


class AkFetchError(Exception):
    pass


def _call(fn, *args, **kwargs) -> pd.DataFrame:
    """带重试+退避地调用一个 akshare 接口,成功后统一节流。"""
    last = None
    for attempt in range(1, CONFIG.ak_retries + 1):
        try:
            df = fn(*args, **kwargs)
            time.sleep(CONFIG.ak_throttle)  # 成功后节流,别连打
            return df
        except Exception as e:  # noqa: BLE001 — akshare 抛的异常类型不稳定,统一兜住
            last = e
            wait = CONFIG.ak_backoff * attempt
            log.warning("%s 第%d次失败: %s,%.1fs 后重试", fn.__name__, attempt, e, wait)
            time.sleep(wait)
    raise AkFetchError(f"{fn.__name__} 连续 {CONFIG.ak_retries} 次失败: {last}")


# ---- 涨停池系列(push2ex,稳定)----

def zt_pool(date: str) -> pd.DataFrame:
    """涨停池:连板数/封板资金/首末封时间/炸板次数/涨停统计/所属行业。date=YYYYMMDD。"""
    return _call(ak.stock_zt_pool_em, date=date)


def zt_previous(date: str) -> pd.DataFrame:
    """昨日涨停今日表现:含昨日连板数,用于算晋级率/断板。"""
    return _call(ak.stock_zt_pool_previous_em, date=date)


def zt_zbgc(date: str) -> pd.DataFrame:
    """炸板池:炸板次数,用于算炸板率。"""
    return _call(ak.stock_zt_pool_zbgc_em, date=date)


def zt_dtgc(date: str) -> pd.DataFrame:
    """跌停池:连续跌停/封单资金。"""
    return _call(ak.stock_zt_pool_dtgc_em, date=date)


def zt_strong(date: str) -> pd.DataFrame:
    """强势股池:量比/涨停统计/入选理由。"""
    return _call(ak.stock_zt_pool_strong_em, date=date)


# ---- 板块/个股(push2,限频,靠重试兜底)----

def board_industry() -> pd.DataFrame:
    """行业板块实时行情+涨跌。"""
    return _call(ak.stock_board_industry_name_em)


def board_concept() -> pd.DataFrame:
    """概念板块实时行情+涨跌。"""
    return _call(ak.stock_board_concept_name_em)


_THS_BLOCK_TOP_URL = "https://data.10jqka.com.cn/dataapi/limit_up/block_top"


def concept_quotes(date: str) -> dict[str, dict]:
    """同花顺涨停板块榜 → {板块名: {pct, limit_up_num, lianban_num, high, code}}。

    给题材热度补「板块涨跌强度」(同花顺板块模块那一列)。选这个源而非东财概念板块行情:
    ①与涨停原因**同源同名**,匹配率高;②带 date 参数**有历史**(东财板块行情只有实时快照,
    贴到历史日期会错配);③一次请求拿完,不踩东财 push2「连打即断」的限频坑。
    局限:同花顺只给当日涨停最多的 **top20 板块**(翻页无效),故冷门题材匹配不到 → 显示「—」。
    拉取失败返回 {},上层降级为不显示强度。
    """
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.10jqka.com.cn/"}
    params = {"filter": "HS,GEM2STAR", "date": date, "page": 1, "limit": 50, "_": 0}
    try:
        data = requests.get(_THS_BLOCK_TOP_URL, params=params, headers=headers, timeout=10) \
            .json().get("data") or []
    except Exception as e:  # noqa: BLE001 板块强度属增强信息,失败不该影响题材聚合
        log.warning("涨停板块榜拉取失败(%s): %s", date, e)
        return {}

    out: dict[str, dict] = {}
    for b in data:
        name = str(b.get("name") or "").strip()
        if not name:
            continue
        pct = pd.to_numeric(b.get("change"), errors="coerce")
        out[name] = {
            "pct": None if pd.isna(pct) else round(float(pct), 2),
            "limit_up_num": int(pd.to_numeric(b.get("limit_up_num"), errors="coerce") or 0),
            "lianban_num": int(pd.to_numeric(b.get("continuous_plate_num"), errors="coerce") or 0),
            "high": str(b.get("high") or ""),  # 如「8天7板」
            "code": str(b.get("code") or ""),
        }
    return out


_mootdx_client = None


def _mootdx():
    """惰性创建 mootdx 行情客户端(首次自动优选服务器)。"""
    global _mootdx_client
    if _mootdx_client is None:
        from mootdx.quotes import Quotes

        _mootdx_client = Quotes.factory(market="std")
    return _mootdx_client


_name_map_cache: tuple[str, dict[str, str]] | None = None  # (YYYYMMDD, {名称: 代码})

# A 股代码段:沪主板 600/601/603/605、科创 688/689、深主板 000/001/002/003、创业 300/301、
# 北交所 4xx/8xx。mootdx 的股票列表是「全品种」(5 万条,含 ETF 5xxxxx / 可转债 11xxxx / 债券),
# 不过滤会让名称反查有概率撞到非股票品种。
_A_SHARE_PREFIX = ("600", "601", "603", "605", "688", "689", "000", "001", "002", "003",
                   "300", "301", "4", "8")


def _is_a_share(code: str) -> bool:
    return len(code) == 6 and code.startswith(_A_SHARE_PREFIX)


def _clean_name(v) -> str:
    """清洗股票名称:去空白 + **去 NUL 等控制字符**。

    通达信协议的名称字段是定长 8 字节,短名用 \\x00 右填充(GBK 下「好想你」=6 字节 → `好想你\\x00\\x00`)。
    只 strip() 去不掉 \\x00,会导致所有 3 字及更短的名称永远查不到 —— 实测「好想你」就这么漏的。
    """
    return re.sub(r"[\x00-\x1f\s　]", "", str(v or ""))


def stock_name_map(force: bool = False) -> dict[str, str]:
    """全 A 股「名称 → 代码」映射。**三级取用:进程内缓存 → SQLite 名录 → 联网拉取(并落库)**。

    给持仓截图导入用:券商截图常常只有名称没有代码(见 app/service.ocr_holdings)。
    联网拉一次约 10s,故落库(`stock_names` 表)后重启进程也不用重拉,一周过期再刷。
    源:mootdx(通达信公开服务器,不限频、快)主用,失败退 akshare `stock_info_a_code_name`。
    同名股票理论上不存在(A股名称唯一),真撞上则后者覆盖前者——前端仍可手改代码。
    force=True 跳过两层缓存强制重拉(新股上市/更名后想立刻刷新时用)。
    """
    global _name_map_cache
    import datetime as dt

    today = dt.date.today().strftime("%Y%m%d")
    if not force and _name_map_cache and _name_map_cache[0] == today:
        return _name_map_cache[1]

    if not force:  # 库里有且没过期就直接用,毫秒级
        from . import store

        cached = store.load_stock_names()
        if cached:
            log.info("股票名录读库:%d 只", len(cached))
            _name_map_cache = (today, cached)
            return cached

    out: dict[str, str] = {}
    try:
        q = _mootdx()
        for market in (0, 1):  # 0=深市 1=沪市
            df = q.stocks(market=market)
            if df is None or len(df) == 0:
                continue
            for _, r in df.iterrows():
                code = re.sub(r"\D", "", str(r.get("code") or ""))
                name = _clean_name(r.get("name"))
                if name and _is_a_share(code):
                    out[name] = code
    except Exception as e:  # noqa: BLE001 mootdx 抖动 → 退 akshare
        log.warning("mootdx 股票列表失败(%s),改用 akshare", e)

    if not out:
        try:
            df = _call(ak.stock_info_a_code_name)
            for _, r in df.iterrows():
                code = re.sub(r"\D", "", str(r.get("code") or ""))
                name = _clean_name(r.get("name"))
                if name and _is_a_share(code):
                    out[name] = code
        except Exception as e:  # noqa: BLE001 两个源都挂 → 退回库里的旧名录,再不行让用户手填
            log.error("股票名称表拉取失败: %s", e)
            from . import store

            stale = store.load_stock_names(max_age_days=3650)  # 过期也比没有好
            if stale:
                log.warning("改用库里的旧名录:%d 只", len(stale))
                _name_map_cache = (today, stale)
                return stale
            return {}

    from . import store

    store.save_stock_names(out)  # 落库,下次(含重启后)直接读库
    log.info("股票名录:%d 只(已落库)", len(out))
    _name_map_cache = (today, out)
    return out


_MARK_PREFIX = re.compile(r"^(S\*ST|\*ST|ST|N|C|XD|XR|DR)")


def _plain_name(n: str) -> str:
    """名称归一:去空白与 * / ST、N、XD 这类交易标记,便于两边对齐。

    截图与名称表的标记不一定一致(「*ST明诚」vs「ST明诚」),故**两边都归一**后再比,
    只剥前缀不够。
    """
    return _MARK_PREFIX.sub("", _clean_name(n).replace("*", ""))


def code_by_name(name: str) -> str:
    """按股票名称查代码;查不到返回空串。先精确匹配,再用归一化名称匹配。"""
    m = stock_name_map()
    n = _clean_name(name)
    if not m or not n:
        return ""
    if n in m:
        return m[n]
    target = _plain_name(n)
    if not target:
        return ""
    # 全表 ~5000 条,现算归一化索引即可(一次导入只查几行,不值得再加一层缓存)
    for k, v in m.items():
        if _plain_name(k) == target:
            return v
    return ""


def realtime_quotes(codes: list[str]) -> dict[str, dict]:
    """批量实时行情(mootdx `q.quotes`)。集合竞价期间 price=实时撮合价,9:25 后 open 定格。

    返回 {code: {price, open, last_close, vol, amount, bid1, ask1, bid_vol1, ask_vol1}};
    按 40 只分批(pytdx 单次上限约 80,留余量),整体失败返回 {} 不抛——盘前面板不该因行情抖动挂掉。
    """
    out: dict[str, dict] = {}
    uniq = [c for c in dict.fromkeys(str(c).strip() for c in codes) if c]
    for i in range(0, len(uniq), 40):
        batch = uniq[i : i + 40]
        try:
            df = _mootdx().quotes(symbol=batch)
        except Exception as e:  # noqa: BLE001 单批失败跳过,其余照常返回
            log.warning("实时行情拉取失败(%s…): %s", batch[:3], e)
            continue
        if df is None or len(df) == 0:
            continue
        for _, r in df.iterrows():
            code = str(r.get("code", "")).strip()
            if not code:
                continue
            out[code] = {
                "price": float(pd.to_numeric(r.get("price"), errors="coerce") or 0),
                "open": float(pd.to_numeric(r.get("open"), errors="coerce") or 0),
                "last_close": float(pd.to_numeric(r.get("last_close"), errors="coerce") or 0),
                "vol": float(pd.to_numeric(r.get("vol"), errors="coerce") or 0),
                "amount": float(pd.to_numeric(r.get("amount"), errors="coerce") or 0),
                "bid1": float(pd.to_numeric(r.get("bid1"), errors="coerce") or 0),
                "ask1": float(pd.to_numeric(r.get("ask1"), errors="coerce") or 0),
                "bid_vol1": float(pd.to_numeric(r.get("bid_vol1"), errors="coerce") or 0),
                "ask_vol1": float(pd.to_numeric(r.get("ask_vol1"), errors="coerce") or 0),
            }
    return out


# ---- K线数据源:东财 push2his 主用,mootdx 兜底 ----
#
# **为什么从 mootdx 换到东财**:2026-09-11 起公开通达信服务器对数据类接口一律空返 ——
# 实测请求 5 根日线只回 2 字节(头部声称 800 根、一根数据都没有),14 台可达服务器行为完全一致,
# 而 `get_security_count` 这类元数据接口仍正常。mootdx 0.11.7 / tdxpy 0.2.7 都已是最新版且
# 期间没升级过,所以是服务端不再供数,换任何客户端(pytdx…)都没用。症状会被 tdxpy 的
# `raise_exception=False` 吞成「返回空表」,表面看像没数据,实际是 struct 解析越界。
#
# 东财这个接口 curl 实测通、格式干净、带历史。**但它限频比通达信严得多**(本项目排查时
# 密集打了十几次就被掐,之后 0/12 全断,几小时才恢复)——所以调用方必须串行 + 节流,
# 绝不能并发。`abnormal.py` 扫几百只时尤其注意。
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
# f51 时间 / f52 开 / f53 收 / f54 高 / f55 低 / f56 量(手) / f57 额(元),顺序即返回串的顺序
_EM_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57"
# 指数用固定 secid:指数代码与个股会撞(000001 既是上证指数也是平安银行),不能按前缀推
_EM_INDEX_SECID = {"999999": "1.000001", "399006": "0.399006"}


def _em_secid(code: str) -> str:
    """个股代码 → 东财 secid(`市场.代码`)。6 开头为沪市(含 60/68),其余深市。"""
    c = str(code).zfill(6)
    return f"{'1' if c.startswith('6') else '0'}.{c}"


def _em_klines(secid: str, klt: int, limit: int) -> list[str]:
    """拉东财 K线,返回原始 `"时间,开,收,高,低,量,额"` 字符串列表;失败或无数据返回 []。

    fqt=0 不复权 —— 与原 mootdx 口径一致(`abnormal.py` 的 N 日累计涨幅按未复权算,
    改成前复权会让历史涨幅整体漂移)。
    """
    params = {
        "secid": secid, "fields1": "f1,f2,f3", "fields2": _EM_FIELDS2,
        "klt": klt, "fqt": 0, "beg": "0", "end": "20500101", "lmt": limit,
    }
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    try:
        data = requests.get(_EM_KLINE_URL, params=params, headers=headers, timeout=10).json()
    except Exception as e:  # noqa: BLE001 单只失败不该炸掉整批扫描
        log.warning("东财K线失败(%s klt=%s): %s", secid, klt, e)
        return []
    finally:
        time.sleep(CONFIG.ak_throttle)  # 限频很严,成功也要节流
    return ((data or {}).get("data") or {}).get("klines") or []


def _em_frame(klines: list[str]) -> pd.DataFrame:
    """原始 K线串 → DataFrame,列 dt/open/close/high/low/vol/amount(dt 为原始时间字符串)。"""
    rows = [k.split(",") for k in klines]
    rows = [r for r in rows if len(r) >= 7]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["dt", "open", "close", "high", "low", "vol", "amount"])
    for c in ("open", "close", "high", "low", "vol", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def stock_intraday_min(code: str, date: str) -> pd.DataFrame:
    """个股当日 1 分钟线(东财 push2his 主用,mootdx 兜底)。

    返回统一列 time/open/close/high/low/vol;取不到返回空表。
    用于判断一字/带量翘板/炸板节点。
    """
    import datetime as _dt

    d = _dt.datetime.strptime(date, "%Y%m%d").date()
    gap = max((_dt.date.today() - d).days, 0)
    lmt = min(240 * (gap + 2), 2400)  # 每交易日约 240 根 1min,按需回溯
    df = _em_frame(_em_klines(_em_secid(code), klt=1, limit=lmt))
    if not df.empty:
        day = df[df["dt"].str[:10].str.replace("-", "", regex=False) == date]
        if day.empty:
            return pd.DataFrame()
        return pd.DataFrame({
            "time": day["dt"].str[11:16].values,
            "open": day["open"].values, "close": day["close"].values,
            "high": day["high"].values, "low": day["low"].values,
            "vol": day["vol"].fillna(0).values,
        })
    return _mootdx_intraday_min(code, date)


def _mootdx_intraday_min(code: str, date: str) -> pd.DataFrame:
    """分时兜底:mootdx。东财挂了才走这里(2026-09 起通达信空返,大概率也拿不到)。"""
    import datetime as _dt

    d = _dt.datetime.strptime(date, "%Y%m%d").date()
    gap = max((_dt.date.today() - d).days, 0)
    offset = min(240 * (gap + 2), 2400)  # 每交易日约 240 根,按需回溯,上限约 10 天

    last = None
    df = None
    for _ in range(2):
        try:
            df = _mootdx().bars(symbol=code, frequency=8, offset=offset)
            break
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0)
    if df is None:
        raise AkFetchError(f"mootdx 分时失败({code}): {last}")
    if len(df) == 0:
        return pd.DataFrame()

    dts = df["datetime"].astype(str)
    day = df[dts.str[:10].str.replace("-", "", regex=False) == date].copy()
    if day.empty:
        return pd.DataFrame()
    vol = pd.to_numeric(day["vol"], errors="coerce").fillna(0)
    vol[vol < 1e-6] = 0  # 清洗通达信协议偶发的浮点垃圾
    return pd.DataFrame({
        "time": day["datetime"].astype(str).str[11:16].values,
        "open": pd.to_numeric(day["open"], errors="coerce").values,
        "close": pd.to_numeric(day["close"], errors="coerce").values,
        "high": pd.to_numeric(day["high"], errors="coerce").values,
        "low": pd.to_numeric(day["low"], errors="coerce").values,
        "vol": vol.values,
    })


def daily_bars(code: str, n: int = 8) -> pd.DataFrame:
    """日线近 n 根(东财主用,mootdx 兜底),统一列 date/open/close/high/low/vol/amount。

    供K线形态与量价感知。取不到返回空表 —— 调用方(kline/abnormal/pattern_blacklist)
    都按「空表=这只跳过」处理,不要改成抛异常,否则一只拉不到会废掉整批扫描。
    """
    df = _em_frame(_em_klines(_em_secid(code), klt=101, limit=n))
    if not df.empty:
        return pd.DataFrame({
            "date": df["dt"].str[:10].str.replace("-", "", regex=False).values,
            "open": df["open"].values, "close": df["close"].values,
            "high": df["high"].values, "low": df["low"].values,
            "vol": df["vol"].fillna(0).values, "amount": df["amount"].fillna(0).values,
        })

    try:
        mdf = _mootdx().bars(symbol=code, frequency=4, offset=n)
    except Exception as e:  # noqa: BLE001 兜底源也挂 → 空表,别把整批扫描带崩
        log.warning("日线兜底 mootdx 失败(%s): %s", code, e)
        return pd.DataFrame()
    if mdf is None or len(mdf) == 0:
        return pd.DataFrame()
    vol = pd.to_numeric(mdf["vol"], errors="coerce").fillna(0)
    vol[vol < 1e-6] = 0  # 清洗通达信协议偶发的浮点垃圾
    return pd.DataFrame({
        "date": mdf["datetime"].astype(str).str[:10].str.replace("-", "", regex=False).values,
        "open": pd.to_numeric(mdf["open"], errors="coerce").values,
        "close": pd.to_numeric(mdf["close"], errors="coerce").values,
        "high": pd.to_numeric(mdf["high"], errors="coerce").values,
        "low": pd.to_numeric(mdf["low"], errors="coerce").values,
        "vol": vol.values,
        "amount": pd.to_numeric(mdf["amount"], errors="coerce").values,
    })


# 盘中监控用:指数分钟线(mootdx 指数接口 q.index,不是个股 q.bars——个股接口取指数会返回垃圾 datetime)
INDEX_CODES = {"999999": "上证指数", "399006": "创业板指"}


def index_intraday_min(code: str, date: str) -> pd.DataFrame:
    """指数当日 1 分钟线(东财主用,mootdx 兜底)。code:上证=999999 / 创业板指=399006。

    返回统一列 time/close/high/low/vol/amount;取不到返回空表。
    供盘中「指数急杀」判据:近 N 分钟跌幅 + 当日 VWAP 均价(amount/vol)。

    code 用的是**通达信**指数代码,东财那边要换成 secid(见 `_EM_INDEX_SECID`)——
    不能按个股规则从代码前缀推市场,000001 既是上证指数又是平安银行。
    """
    import datetime as _dt

    secid = _EM_INDEX_SECID.get(str(code))
    if secid:
        _d = _dt.datetime.strptime(date, "%Y%m%d").date()
        _lmt = min(240 * (max((_dt.date.today() - _d).days, 0) + 2), 2400)
        edf = _em_frame(_em_klines(secid, klt=1, limit=_lmt))
        if not edf.empty:
            eday = edf[edf["dt"].str[:10].str.replace("-", "", regex=False) == date]
            if eday.empty:
                return pd.DataFrame()
            return pd.DataFrame({
                "time": eday["dt"].str[11:16].values,
                "close": eday["close"].values, "high": eday["high"].values,
                "low": eday["low"].values, "vol": eday["vol"].fillna(0).values,
                "amount": eday["amount"].fillna(0).values,
            })

    d = _dt.datetime.strptime(date, "%Y%m%d").date()
    gap = max((_dt.date.today() - d).days, 0)
    offset = min(240 * (gap + 2), 2400)  # 每交易日约 240 根 1min

    last = None
    df = None
    for _ in range(2):
        try:
            df = _mootdx().index(symbol=code, frequency=8, offset=offset)
            break
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0)
    if df is None:
        raise AkFetchError(f"mootdx 指数分时失败({code}): {last}")
    if len(df) == 0:
        return pd.DataFrame()

    dts = df["datetime"].astype(str)
    day = df[dts.str[:10].str.replace("-", "", regex=False) == date].copy()
    if day.empty:
        return pd.DataFrame()
    vol = pd.to_numeric(day["vol"], errors="coerce").fillna(0)
    vol[vol < 1e-6] = 0  # 清洗通达信协议偶发的浮点垃圾
    return pd.DataFrame({
        "time": day["datetime"].astype(str).str[11:16].values,
        "close": pd.to_numeric(day["close"], errors="coerce").values,
        "high": pd.to_numeric(day["high"], errors="coerce").values,
        "low": pd.to_numeric(day["low"], errors="coerce").values,
        "vol": vol.values,
        "amount": pd.to_numeric(day["amount"], errors="coerce").values,
    })


def auction_metrics(code: str, date: str) -> dict | None:
    """竞价高开幅度:今开 vs 昨收(日线),附今日成交额(亿)。取不到返回 None。"""
    d = daily_bars(code, 8)
    if d.empty:
        return None
    d = d.reset_index(drop=True)
    idx = d.index[d["date"] == date]
    if len(idx) == 0 or idx[0] == 0:
        return None
    i = idx[0]
    prev_close = float(d.iloc[i - 1]["close"])
    open_p = float(d.iloc[i]["open"])
    if not prev_close:
        return None
    return {
        "code": code,
        "open": round(open_p, 2),
        "prev_close": round(prev_close, 2),
        "gap_pct": round((open_p - prev_close) / prev_close * 100, 2),
        "amount_yi": round(float(d.iloc[i]["amount"]) / 1e8, 2),
    }


# ---- 题材(同花顺涨停原因)与市场热度榜 ----

_THS_LIMITUP_URL = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
_THS_FIELD = "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,3475914"
_THEME_SPLIT = re.compile(r"[+＋、,，]")


def ths_limitup_reasons(date: str) -> dict[str, list[str]]:
    """同花顺涨停池的「涨停原因」→ {6位代码: [题材标签...]}(多属性,按 + 拆分)。

    一次分页拉全当日涨停票(每页≤80),失败/空返回 {}。给个股打题材标签、聚合题材热度用。
    """
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.10jqka.com.cn/"}
    out: dict[str, list[str]] = {}
    page = 1
    while page <= 8:  # 兜底上限,单日涨停一般 ≤160 只
        params = {
            "field": _THS_FIELD, "filter": "HS,GEM2STAR",
            "order_field": "330324", "order_type": 0,
            "date": date, "page": page, "limit": 80, "_": 0,
        }
        try:
            info = requests.get(_THS_LIMITUP_URL, params=params, headers=headers, timeout=10) \
                .json().get("data", {}).get("info", []) or []
        except Exception as e:  # noqa: BLE001
            log.warning("同花顺涨停原因拉取失败(%s p%d): %s", date, page, e)
            break
        for k in info:
            code = str(k.get("code", "")).strip()
            if not code:
                continue
            rt = str(k.get("reason_type") or "").strip()
            out[code] = [t.strip() for t in _THEME_SPLIT.split(rt) if t.strip()] if rt else []
        if len(info) < 80:
            break
        page += 1
        time.sleep(0.4)
    return out


def hot_rank_top(n: int = 20) -> list[dict]:
    """东财个股人气榜前 n(实时,无历史)。返回 [{rank, code(6位), name, pct}]。"""
    try:
        df = _call(ak.stock_hot_rank_em)
    except Exception as e:  # noqa: BLE001
        log.warning("热度榜拉取失败: %s", e)
        return []
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.head(n).iterrows():
        raw = str(r.get("代码", ""))
        out.append({
            "rank": int(r.get("当前排名", 0)),
            "code": raw[-6:],  # 去 SZ/SH 前缀
            "name": str(r.get("股票名称", "")),
            "pct": round(float(pd.to_numeric(r.get("涨跌幅"), errors="coerce") or 0), 2),
        })
    return out
