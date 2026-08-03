"""多选持仓分析:多 code 取数、一篇 markdown 存给每只、verdict 各取自己那项。

用临时库(CONFIG.db_path 指到 tmp_path),不碰真实持仓,也不跑 agent。
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def svc(tmp_path, monkeypatch):
    from daban_review.app import service
    from daban_review.config import CONFIG

    monkeypatch.setattr(CONFIG, "db_path", str(tmp_path / "t.db"))
    service.add_holding("000533", "顺钠股份", "20260728", 11.57, 4, "", 3500)
    service.add_holding("002580", "圣阳股份", "20260728", 15.34, 1, "", 3000)
    service.add_holding("603928", "兴业股份", "20260728", 11.86, 0, "", 3500)
    return service


MD = """## 顺钠股份(000533)
### 诊断
4板高位,换手 28.1%
## 圣阳股份(002580)
### 诊断
首板缩量

```json
[{"code":"000533","verdict":"减仓","take_profit":"12.5","stop_loss":"11.0","priority":1},
 {"code":"002580","verdict":"持有","take_profit":"18.5","stop_loss":"15.0","priority":2}]
```
"""


class TestHoldingInfo:
    def test_multiple_codes_in_given_order(self, svc):
        got = svc._holding_info(["002580", "000533"])
        assert [h["code"] for h in got] == ["002580", "000533"]
        assert got[0]["name"] == "圣阳股份" and got[1]["buy_boards"] == 4

    def test_carries_shares(self, svc):
        assert svc._holding_info(["000533"])[0]["shares"] == 3500

    def test_unknown_codes_skipped(self, svc):
        assert [h["code"] for h in svc._holding_info(["999999", "000533"])] == ["000533"]

    def test_empty_input(self, svc):
        assert svc._holding_info([]) == []
        assert svc._holding_info(["", "  "]) == []


class TestSaveAnalysis:
    def test_saved_for_every_code_with_own_verdict(self, svc):
        """一篇 markdown 存给两只,各自 verdict 从 json 里按 code 取。"""
        svc._save_holding_analysis(["000533", "002580"], "20260728", MD)

        a = svc.get_holding_analysis("000533")
        b = svc.get_holding_analysis("002580")
        assert a["markdown"] == b["markdown"] == MD  # 同一篇
        assert a["verdict"]["verdict"] == "减仓" and a["verdict"]["priority"] == 1
        assert b["verdict"]["verdict"] == "持有" and b["verdict"]["take_profit"] == "18.5"

    def test_code_not_in_json_gets_fallback(self, svc):
        """agent 漏了某只(json 里没有它)时不报错,退回第一项而不是崩。"""
        svc._save_holding_analysis(["603928"], "20260728", MD)
        v = svc.get_holding_analysis("603928")["verdict"]
        assert v.get("code") == "000533"  # 兜底取首项,前端仍能显示

    def test_rerun_overwrites(self, svc):
        svc._save_holding_analysis(["000533"], "20260728", MD)
        svc._save_holding_analysis(["000533"], "20260728", "新的一篇\n```json\n[{\"code\":\"000533\",\"verdict\":\"清仓\"}]\n```")
        assert svc.get_holding_analysis("000533")["verdict"]["verdict"] == "清仓"


class TestExtractVerdict:
    def test_picks_matching_code(self, svc):
        assert svc._extract_holding_verdict(MD, "002580")["verdict"] == "持有"

    def test_broken_json(self, svc):
        assert svc._extract_holding_verdict("```json\n[坏json,,]\n```", "000533") == {}

    def test_no_json_block(self, svc):
        assert svc._extract_holding_verdict("只有正文没有 json", "000533") == {}

    def test_dict_instead_of_list(self, svc):
        md = '```json\n{"code":"000533","verdict":"持有"}\n```'
        assert svc._extract_holding_verdict(md, "000533")["verdict"] == "持有"


class TestApiBody:
    """接口层:codes 多选为主,code 单票兼容。"""

    def test_codes_and_legacy_code(self):
        from daban_review.app.main import HoldingAnalyzeBody

        b = HoldingAnalyzeBody(date="20260728", codes=["000533", "002580"])
        assert b.codes == ["000533", "002580"] and b.code == ""
        legacy = HoldingAnalyzeBody(date="20260728", code="000533")
        assert legacy.codes == [] and legacy.code == "000533"

    def test_empty_selection_rejected(self):
        from fastapi.testclient import TestClient

        from daban_review.app.main import app

        with TestClient(app) as c:
            r = c.post("/api/holdings/analyze", json={"date": "20260728", "codes": []})
        assert r.status_code == 400
        assert "至少" in r.json()["detail"]
