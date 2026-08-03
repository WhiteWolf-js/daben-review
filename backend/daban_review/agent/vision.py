"""持仓截图识别:券商 App 的持仓截图 → 结构化持仓行。

**为什么不走 claude-agent-sdk**:识别是单轮视觉任务,不需要工具循环/流式,直接 POST
Messages API 更短更可控(也不必新增 anthropic 依赖,requests 随 akshare 已在)。
走的仍是 config 里同一个内部网关(已实测支持 vision)。

识别只负责「截图里有什么」;截图里没有的(买入板数、买入日、是否已在持仓)由 service 层补,
见 app/service.ocr_holdings。
"""

from __future__ import annotations

import json
import logging
import re

import requests

from ..config import CONFIG

log = logging.getLogger(__name__)

TIMEOUT = 120
MAX_TOKENS = 2048
ALLOWED_MEDIA = ("image/png", "image/jpeg", "image/webp", "image/gif")

PROMPT = """这是一张券商/交易 App 的**持仓截图**。逐行提取持仓个股,输出 JSON 数组。

每项字段(缺失或看不清一律给 null,不要猜):
- name: 股票名称
- code: A股代码,**只有截图里真的显示了 6 位数字代码才填**(带 SH/SZ/BJ 前后缀的去掉前后缀)。
  很多券商持仓页只显示名称不显示代码 —— 这种情况 code 一律给 null。
  **绝对不要**拿持仓数量、可用数量、行序号、账户号、涨跌幅等别的数字来充当 code。
- shares: 持仓股数(整数;若显示"持仓/可用"两行,取**持仓**那个)
- cost_price: 成本价(浮点)
- cur_price: 现价/市价(浮点)
- pnl_pct: 盈亏比例,单位%(亏损为负数,如 -4.18)

规则:
1. 只输出 JSON 数组本身,不要 markdown 说明、不要代码块外的任何文字。
2. 只提取**个股持仓行**。总资产/总市值/当日盈亏/可用资金这类汇总信息不是持仓行,不要输出。
3. 不要凭空补行:截图里有几只就是几只。看不出代码的行也要输出(code 给 null),由用户自己补。
4. 数字按截图原样,不要做单位换算(如 1.2万 写成 12000 是允许的换算,千分位逗号要去掉)。
"""


def _endpoint() -> str:
    base = (CONFIG.anthropic_base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("未配置 ANTHROPIC_BASE_URL,无法识别持仓截图")
    return base + ("" if base.endswith("/v1") else "/v1") + "/messages"


def _num(v, cast=float):
    """脏值 → 数字。去千分位逗号/百分号/正负号前缀空格;失败给 None。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return cast(v)
    s = str(v).strip().replace(",", "").replace("%", "").replace("+", "")
    if not s or s in {"-", "--", "—"}:
        return None
    try:
        return cast(float(s))
    except (TypeError, ValueError):
        return None


def _norm_code(v) -> str:
    """代码规范化:去 SH/SZ/BJ 等前后缀与空白,**只认恰好 6 位数字**,否则给空串。

    故意不做「短数字左侧补零」:券商截图里代码一律是完整 6 位,而模型偶尔会把持仓数量、
    行序号之类的数字塞进 code 字段(实测出现过 code="1")。补零会把它变成 000001(平安银行)
    这种看起来合法的错代码;返回空串则会走 service 的「按名称反查」,查不到再让用户手填,
    都比存一个错代码安全。
    """
    s = re.sub(r"[^0-9]", "", str(v or ""))
    return s if len(s) == 6 else ""


def parse_rows(text: str) -> list[dict]:
    """把模型输出解析成持仓行。容错同 service._extract_candidates:先找 ```json 块,再退化整体解析。

    额外做字段清洗(数字脏值、代码补零),code 认不出的行仍保留(前端让用户手填)。
    """
    blocks = re.findall(r"```(?:json)?\s*(.*?)```", text or "", re.DOTALL)
    payload = blocks[-1].strip() if blocks else (text or "").strip()
    # 模型偶尔在数组前后带一句话 → 截取第一个 [ 到最后一个 ]
    if not payload.startswith("["):
        i, j = payload.find("["), payload.rfind("]")
        payload = payload[i : j + 1] if 0 <= i < j else payload
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        log.warning("持仓截图识别结果无法解析为 JSON:%s", (text or "")[:200])
        return []
    if isinstance(data, dict):  # 偶发被包一层 {"holdings": [...]}
        for k in ("holdings", "rows", "data", "list"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    if not isinstance(data, list):
        return []

    out: list[dict] = []
    for it in data:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        code = _norm_code(it.get("code"))
        if not name and not code:  # 名称代码全无 → 不是持仓行
            continue
        out.append({
            "name": name,
            "code": code,
            "shares": _num(it.get("shares"), int) or 0,
            "cost_price": _num(it.get("cost_price")),
            "cur_price": _num(it.get("cur_price")),
            "pnl_pct": _num(it.get("pnl_pct")),
        })
    return out


def extract_holdings(image_b64: str, media_type: str = "image/png") -> tuple[list[dict], dict]:
    """识别持仓截图。返回 (rows, usage);usage 为 Messages API 的用量,交给 pricing 计价。

    media_type 不在白名单时抛 ValueError;网关非 200 抛 RuntimeError(带状态码,便于前端提示)。
    """
    if media_type not in ALLOWED_MEDIA:
        raise ValueError(f"不支持的图片类型:{media_type}")

    body = {
        "model": CONFIG.vision_model,
        "max_tokens": MAX_TOKENS,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": PROMPT},
            ],
        }],
    }
    r = requests.post(
        _endpoint(),
        headers={
            "x-api-key": CONFIG.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        log.error("持仓截图识别失败 HTTP %s:%s", r.status_code, r.text[:300])
        raise RuntimeError(f"识别服务返回 {r.status_code}")

    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    rows = parse_rows(text)
    log.info("持仓截图识别:%d 行(model=%s)", len(rows), CONFIG.vision_model)
    return rows, data.get("usage") or {}
