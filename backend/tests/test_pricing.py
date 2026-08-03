"""agent/pricing.compute_cost 单测(纯函数)。单价 Opus 4.8:in$5/out$25/cacheW$6.25/cacheR$0.5 每百万。"""

import pytest

from daban_review.agent import pricing
from daban_review.config import CONFIG


def test_by_token_input_output():
    # 各 100 万 token
    r = pricing.compute_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    assert r["cost_usd"] == 30.0  # 5 + 25
    assert r["input_tokens"] == 1_000_000
    assert r["output_tokens"] == 1_000_000


def test_cache_pricing():
    r = pricing.compute_cost({"cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000})
    assert r["cost_usd"] == 6.75  # 0.5 + 6.25
    assert r["cache_read"] == 1_000_000
    assert r["cache_write"] == 1_000_000


def test_total_tokens_and_cny():
    r = pricing.compute_cost({"input_tokens": 1_000_000})
    assert r["total_tokens"] == 1_000_000
    assert r["cost_usd"] == 5.0
    assert r["cost_cny"] == round(5.0 * CONFIG.usd_cny, 4)


def test_total_cost_usd_takes_precedence():
    # total_cost_usd > 0 时直接用它,忽略按 token 的算法
    r = pricing.compute_cost({"input_tokens": 1_000_000}, total_cost_usd=0.1234)
    assert r["cost_usd"] == 0.1234
    assert r["cost_cny"] == round(0.1234 * CONFIG.usd_cny, 4)
    assert r["input_tokens"] == 1_000_000  # token 明细仍如实返回


def test_total_cost_zero_falls_back_to_token_calc():
    # total_cost_usd = 0(网关不回)→ 回退按 token 算
    r = pricing.compute_cost({"output_tokens": 1_000_000}, total_cost_usd=0)
    assert r["cost_usd"] == 25.0


def test_empty_and_missing_fields():
    r = pricing.compute_cost(None)
    assert r["cost_usd"] == 0.0 and r["total_tokens"] == 0
    r2 = pricing.compute_cost({})
    assert r2["cost_usd"] == 0.0


def test_bad_values_coerced():
    r = pricing.compute_cost({"input_tokens": "x", "output_tokens": None})
    assert r["input_tokens"] == 0 and r["output_tokens"] == 0 and r["cost_usd"] == 0.0


def test_small_realistic_call():
    # 贴近真实:少量输入 + 大量缓存读 + 中量输出
    r = pricing.compute_cost({
        "input_tokens": 5_000, "output_tokens": 3_000,
        "cache_read_input_tokens": 50_000, "cache_creation_input_tokens": 8_000,
    })
    expected = (5_000 * 5 + 3_000 * 25 + 50_000 * 0.5 + 8_000 * 6.25) / 1_000_000
    assert r["cost_usd"] == round(expected, 4)
