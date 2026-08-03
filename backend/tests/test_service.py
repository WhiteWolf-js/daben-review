"""daban_review.app.service._extract_candidates 的容错解析测试(纯字符串/JSON,无网络)。

注:导入 service 会连带 import agent.runner(claude_agent_sdk),但均无 import 期网络副作用;
若该链路缺依赖导致导入失败,则跳过本文件而非硬失败。
"""

from __future__ import annotations

import pytest

service = pytest.importorskip(
    "daban_review.app.service",
    reason="service 依赖链(claude_agent_sdk 等)不可导入,跳过",
)
_extract_candidates = service._extract_candidates


def test_normal_json_block():
    md = (
        "复盘正文……\n\n"
        "```json\n"
        '[{"code":"600000","name":"浦发银行","style":"首板打板",'
        '"trigger":"竞价高开","giveup":"低开破位","reason":"主线首板",'
        '"pool_rank":1,"price_ref":"12.30×1.10=13.53"}]\n'
        "```\n"
    )
    out = _extract_candidates(md)
    assert len(out) == 1
    c = out[0]
    assert c == {
        "style": "首板打板",
        "code": "600000",
        "name": "浦发银行",
        "trigger": "竞价高开",
        "giveup": "低开破位",
        "reason": "主线首板",
        "pool_rank": 1,
        "price_ref": "12.30×1.10=13.53",
    }


def test_no_json_block_returns_empty():
    assert _extract_candidates("这里没有任何代码块") == []


def test_broken_json_returns_empty():
    md = "```json\n[not valid json,,,]\n```"
    assert _extract_candidates(md) == []


def test_json_not_a_list_returns_empty():
    # 顶层是 dict 而非 list
    md = '```json\n{"code":"600000"}\n```'
    assert _extract_candidates(md) == []


def test_item_missing_code_is_skipped():
    md = '```json\n[{"name":"无代码"},{"code":"000001","name":"有代码"}]\n```'
    out = _extract_candidates(md)
    assert len(out) == 1
    assert out[0]["code"] == "000001"
    assert out[0]["name"] == "有代码"


def test_non_dict_items_skipped():
    md = '```json\n["str", 123, null, {"code":"000333"}]\n```'
    out = _extract_candidates(md)
    assert len(out) == 1
    assert out[0]["code"] == "000333"


def test_multiple_blocks_takes_last():
    md = (
        '```json\n[{"code":"111111"}]\n```\n'
        "中间还有别的内容\n"
        '```json\n[{"code":"222222"}]\n```\n'
    )
    out = _extract_candidates(md)
    assert len(out) == 1
    assert out[0]["code"] == "222222"


def test_missing_optional_fields_defaults_to_empty_strings():
    md = '```json\n[{"code":"000002"}]\n```'
    out = _extract_candidates(md)
    assert out == [{
        "style": "", "code": "000002", "name": "",
        "trigger": "", "giveup": "", "reason": "",
        "pool_rank": None, "price_ref": "",  # 候选池字段缺失时不报错,交由 in_pool 校验兜底
    }]


def test_pool_rank_non_numeric_becomes_none():
    md = '```json\n[{"code":"000002","pool_rank":"一"}]\n```'
    assert _extract_candidates(md)[0]["pool_rank"] is None


def test_code_is_stripped_and_stringified():
    # code 为数字 / 带空白 → 转字符串并去空白
    md = '```json\n[{"code":600000},{"code":"  600519  "}]\n```'
    out = _extract_candidates(md)
    assert [c["code"] for c in out] == ["600000", "600519"]


def test_empty_code_string_skipped():
    md = '```json\n[{"code":"   "},{"code":"000001"}]\n```'
    out = _extract_candidates(md)
    assert [c["code"] for c in out] == ["000001"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
