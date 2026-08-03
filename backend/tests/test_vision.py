"""持仓截图识别的解析层单测(纯字符串处理,不发网络请求)。

模型输出不可控(有时裹 ```json、有时前面加一句话、数字带千分位/%),这些容错都在
vision.parse_rows 里,故重点测它;发请求那层(extract_holdings)靠端到端脚本实测。
"""

from __future__ import annotations

import pytest

from daban_review.agent.vision import _norm_code, _num, parse_rows


class TestNormCode:
    def test_plain_6_digits(self):
        assert _norm_code("000533") == "000533"

    def test_strips_exchange_prefix(self):
        assert _norm_code("SZ000533") == "000533"
        assert _norm_code("600000.SH") == "600000"

    def test_rejects_too_long(self):
        assert _norm_code("1234567") == ""

    def test_rejects_short_digits_instead_of_padding(self):
        """短数字不补零:模型实测会把持仓数量/序号塞进 code(如 "1"),补零会变成
        000001(平安银行)这种合法但错误的代码。返回空串才能走名称反查/手填。"""
        for v in ("1", "533", "12345"):
            assert _norm_code(v) == ""

    def test_empty_and_none(self):
        assert _norm_code(None) == ""
        assert _norm_code("--") == ""


class TestNum:
    def test_thousands_separator(self):
        assert _num("12,000", int) == 12000

    def test_percent_and_sign(self):
        assert _num("+6.59%") == 6.59
        assert _num("-4.18%") == -4.18

    def test_placeholders_to_none(self):
        for v in (None, "", "--", "—", "-"):
            assert _num(v) is None

    def test_garbage_to_none(self):
        assert _num("abc") is None

    def test_bool_not_treated_as_number(self):
        assert _num(True) is None


class TestParseRows:
    RAW = """[{"name":"顺钠股份","code":"000533","shares":8000,
              "cost_price":9.86,"cur_price":10.51,"pnl_pct":6.59}]"""

    def test_plain_json_array(self):
        rows = parse_rows(self.RAW)
        assert len(rows) == 1
        r = rows[0]
        assert (r["name"], r["code"], r["shares"]) == ("顺钠股份", "000533", 8000)
        assert (r["cost_price"], r["cur_price"], r["pnl_pct"]) == (9.86, 10.51, 6.59)

    def test_wrapped_in_json_fence(self):
        assert len(parse_rows(f"```json\n{self.RAW}\n```")) == 1

    def test_wrapped_in_plain_fence(self):
        assert len(parse_rows(f"```\n{self.RAW}\n```")) == 1

    def test_leading_chatter_before_array(self):
        assert len(parse_rows(f"好的,识别结果如下:\n{self.RAW}\n以上。")) == 1

    def test_object_wrapper_unwrapped(self):
        assert len(parse_rows('{"holdings": %s}' % self.RAW)) == 1

    def test_dirty_numbers_cleaned(self):
        rows = parse_rows('[{"name":"新亚制程","code":"SZ002388","shares":"12,000",'
                          '"cost_price":"4.36","cur_price":"4.80","pnl_pct":"+10.09%"}]')
        r = rows[0]
        assert r["code"] == "002388" and r["shares"] == 12000 and r["pnl_pct"] == 10.09

    def test_bogus_short_code_becomes_empty(self):
        """模型把序号当代码时不要留下错代码,清空交给名称反查。"""
        rows = parse_rows('[{"name":"兴业股份","code":"1","cost_price":11.859}]')
        assert rows[0]["code"] == "" and rows[0]["name"] == "兴业股份"

    def test_missing_fields_become_none_not_error(self):
        rows = parse_rows('[{"name":"某票","code":"000001"}]')
        assert rows[0]["cost_price"] is None and rows[0]["shares"] == 0

    def test_row_without_code_kept_for_manual_fill(self):
        """代码认不出的行仍要保留(前端让用户补),只有名称代码全无才丢。"""
        rows = parse_rows('[{"name":"看不清代码的票","code":null,"cost_price":10}]')
        assert len(rows) == 1 and rows[0]["code"] == ""

    def test_row_with_neither_name_nor_code_dropped(self):
        assert parse_rows('[{"cost_price":10,"shares":100}]') == []

    def test_non_dict_items_skipped(self):
        assert parse_rows('["总市值 286,430", 123, null, {"name":"A","code":"000001"}]') == [
            {"name": "A", "code": "000001", "shares": 0,
             "cost_price": None, "cur_price": None, "pnl_pct": None}
        ]

    def test_broken_json_returns_empty(self):
        assert parse_rows("这张图看不清,无法识别") == []
        assert parse_rows("[{不是合法 json,,,}]") == []

    def test_empty_input(self):
        assert parse_rows("") == []
        assert parse_rows(None) == []


class TestExtractGuards:
    def test_rejects_unsupported_media_type(self):
        from daban_review.agent.vision import extract_holdings

        with pytest.raises(ValueError, match="不支持的图片类型"):
            extract_holdings("Zm9v", "image/tiff")


class TestCodeByName:
    """按名称反查代码(截图只有名称没代码时用)。注入进程缓存,不走网络。"""

    @pytest.fixture(autouse=True)
    def _fake_name_table(self, monkeypatch):
        import datetime as dt

        from daban_review.data import akshare_client as ak

        table = {"兴业股份": "603928", "吉华集团": "603980", "皇台酒业": "000995", "ST明诚": "600136"}
        monkeypatch.setattr(ak, "_name_map_cache", (dt.date.today().strftime("%Y%m%d"), table))
        return table

    def test_exact_hit(self):
        from daban_review.data.akshare_client import code_by_name

        assert code_by_name("兴业股份") == "603928"

    def test_nul_padded_table_key_still_hits(self, monkeypatch):
        """通达信名称字段定长 8 字节,短名用 \\x00 右填充(「好想你」→「好想你\\x00\\x00」)。

        实测这让所有 3 字及更短的股票永远查不到。名录侧已在 _clean_name 清掉,
        这里再验一遍:即便库里存的是脏名字,归一化匹配也要能命中。
        """
        import datetime as dt

        from daban_review.data import akshare_client as ak

        monkeypatch.setattr(
            ak, "_name_map_cache",
            (dt.date.today().strftime("%Y%m%d"), {"好想你\x00\x00": "002582"}),
        )
        assert ak.code_by_name("好想你") == "002582"

    def test_clean_name_strips_nul_and_fullwidth_space(self):
        from daban_review.data.akshare_client import _clean_name

        assert _clean_name("好想你\x00\x00") == "好想你"
        assert _clean_name(" 兴业　股份 ") == "兴业股份"

    def test_strips_spaces(self):
        from daban_review.data.akshare_client import code_by_name

        assert code_by_name(" 吉华集团 ") == "603980"

    def test_st_prefix_fallback(self):
        """识别出「*ST明诚」而名称表里是「ST明诚」时,剥掉标记再试一次。"""
        from daban_review.data.akshare_client import code_by_name

        assert code_by_name("*ST明诚") == "600136"

    def test_miss_returns_empty(self):
        from daban_review.data.akshare_client import code_by_name

        assert code_by_name("不存在的票") == ""

    def test_empty_name(self):
        from daban_review.data.akshare_client import code_by_name

        assert code_by_name("") == "" and code_by_name(None) == ""
