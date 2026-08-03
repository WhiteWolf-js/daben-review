"""按 Opus 4.8 官方单价估算一次 agent 调用的成本。

经中转网关时 SDK 的 total_cost_usd 常为 0/None,则按 usage 的 token 数 ×
官方单价自算。金额是「若按官方 API 价值多少钱」的参考,不等于内部网关实际结算。
单价、汇率集中在此 + config.usd_cny,后续调价改一处。
"""

from __future__ import annotations

from ..config import CONFIG

_PER_M = 1_000_000

# Opus 4.8 官方单价(美元 / 每百万 token)
PRICE_INPUT = 5.0
PRICE_OUTPUT = 25.0
PRICE_CACHE_WRITE = 6.25  # 1.25 × input(5 分钟 TTL 写入)
PRICE_CACHE_READ = 0.5    # 0.1 × input


def _int(usage: dict, key: str) -> int:
    try:
        return int(usage.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def compute_cost(usage: dict | None, total_cost_usd: float | None = None) -> dict:
    """算一次调用的 token 明细与金额。

    usage: SDK ResultMessage.usage(含 input_tokens / output_tokens /
    cache_read_input_tokens / cache_creation_input_tokens)。
    total_cost_usd: SDK 给的成本,>0 时直接用,否则按官方单价自算。
    返回 {input_tokens, output_tokens, cache_read, cache_write, total_tokens, cost_usd, cost_cny}。
    """
    usage = usage or {}
    inp = _int(usage, "input_tokens")
    out = _int(usage, "output_tokens")
    cache_read = _int(usage, "cache_read_input_tokens")
    cache_write = _int(usage, "cache_creation_input_tokens")

    if total_cost_usd and total_cost_usd > 0:
        cost_usd = float(total_cost_usd)
    else:
        cost_usd = (
            inp * PRICE_INPUT
            + out * PRICE_OUTPUT
            + cache_read * PRICE_CACHE_READ
            + cache_write * PRICE_CACHE_WRITE
        ) / _PER_M
    cost_usd = round(cost_usd, 4)
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "total_tokens": inp + out + cache_read + cache_write,
        "cost_usd": cost_usd,
        "cost_cny": round(cost_usd * CONFIG.usd_cny, 4),
    }
