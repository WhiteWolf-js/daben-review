"""飞书机器人指令层测试:路由分派 / 日期解析 / 渲染空态。

service 调用一律 monkeypatch,不碰网络也不碰真实库。
"""

from __future__ import annotations

import pytest

from daban_review.monitor import bot_commands as bc


# ---------------------------------------------------------------------------
# parse:文本 → (动作, 日期)
# ---------------------------------------------------------------------------
class TestParse:
    @pytest.mark.parametrize("text,key", [
        ("复盘", "review"), ("海报", "review"), ("review", "review"), ("POSTER", "review"),
        ("候选", "candidates"), ("作战清单", "candidates"), ("cand", "candidates"),
        ("情绪", "emotion"), ("live", "emotion"),
        ("持仓", "holdings"), ("hold", "holdings"),
        ("竞价", "auction"), ("盘前", "auction"),
        ("竞价图", "auction_image"), ("盘前图", "auction_image"),
        ("天梯图", "ladder_image"), ("连板图", "ladder_image"),
        ("复盘长图", "report_image"), ("长图", "report_image"), ("正文图", "report_image"),
        ("题材", "theme"), ("板块", "theme"),
        ("天梯", "ladder"), ("梯队", "ladder"),
        ("命中率", "stats"), ("回测", "stats"),
        ("成本", "cost"), ("花费", "cost"),
        ("帮助", "help"), ("help", "help"), ("菜单", "help"),
    ])
    def test_aliases(self, text, key):
        assert bc.parse(text)[0] == key

    def test_unknown_does_not_fall_to_ask(self):
        """核心防线:模糊输入绝不自动烧 agent(早期这么干,两条问题白花 ¥16)。"""
        assert bc.parse("今天大盘怎么看")[0] == "unknown"

    def test_ask_needs_explicit_prefix(self):
        key, _, q = bc.parse("问 小哈今天走哪个属性")
        assert key == "ask"
        assert q == "小哈今天走哪个属性"

    @pytest.mark.parametrize("text", ["问:小哈强不强", "提问 小哈强不强", "ask 小哈强不强"])
    def test_ask_prefix_variants(self, text):
        assert bc.parse(text)[0] == "ask"

    def test_ask_without_question_is_flagged(self):
        assert bc.parse("问")[0] == "ask_empty"

    def test_natural_language_hits_command_cheaply(self):
        """用户真实说法要被便宜地接住,不该掉进 agent。"""
        assert bc.parse("发一下今日复盘给我")[0] == "review"
        assert bc.parse("分析一下盘前竞价")[0] == "auction"

    def test_image_aliases_win_over_text_ones(self):
        # 「竞价图」含「竞价」、「天梯图」含「天梯」,靠声明序保证图优先
        assert bc.parse("竞价图")[0] == "auction_image"
        assert bc.parse("天梯图")[0] == "ladder_image"
        assert bc.parse("天梯")[0] == "ladder"  # 不带图仍走文本

    def test_long_image_wins_over_review_poster(self):
        """「复盘长图」含「复盘」,声明序必须让长图先命中 —— 这处最容易被后人改坏。"""
        assert bc.parse("复盘长图")[0] == "report_image"
        assert bc.parse("发一张今天的复盘长图")[0] == "report_image"
        assert bc.parse("复盘")[0] == "review"  # 不带长图仍是摘要海报

    def test_date_extracted_and_stripped(self):
        # 日期被摘出后,剩下的词仍要能命中指令
        assert bc.parse("复盘 20260723")[:2] == ("review", "20260723")
        assert bc.parse("20260723 候选")[:2] == ("candidates", "20260723")

    def test_no_date_returns_none(self):
        assert bc.parse("候选")[1] is None

    def test_non_date_digits_ignored(self):
        # 6 位数字(股票代码)不该被当成日期
        assert bc.parse("候选 002677")[1] is None

    def test_whitespace_and_case(self):
        assert bc.parse("  HELP  ")[0] == "help"

    def test_empty_text_is_unknown(self):
        assert bc.parse("")[0] == "unknown"


# ---------------------------------------------------------------------------
# resolve_date:没给日期时退到「最近一个已生成复盘的交易日」
# ---------------------------------------------------------------------------
class TestResolveDate:
    def test_explicit_date_wins(self):
        assert bc.resolve_date("20260101") == "20260101"

    def test_today_when_today_has_report(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_report", lambda d: {"markdown": "x"} if d == "20260728" else None)
        assert bc.resolve_date(None, today="20260728") == "20260728"

    def test_falls_back_to_prev_with_report(self, monkeypatch):
        from daban_review.app import service

        # 今天没复盘,昨天(0727)有 → 用 0727
        monkeypatch.setattr(service, "get_report", lambda d: {"markdown": "x"} if d == "20260727" else None)
        monkeypatch.setattr(service, "list_dates", lambda *a, **k: ["20260728", "20260727", "20260724"])
        assert bc.resolve_date(None, today="20260728") == "20260727"

    def test_no_report_anywhere_returns_today(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_report", lambda d: None)
        monkeypatch.setattr(service, "list_dates", lambda *a, **k: ["20260728", "20260727"])
        assert bc.resolve_date(None, today="20260728") == "20260728"


# ---------------------------------------------------------------------------
# 渲染:有数据 / 空态
# ---------------------------------------------------------------------------
class TestFmtCandidates:
    def test_renders_grade_trigger_giveup(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_candidates", lambda d: [{
            "grade": "A+", "name": "圣阳股份", "position": "2-3成", "pool_rank": 1, "in_pool": True,
            "style": "首板打板", "trigger": "触及18.56快速封板", "giveup": "跌破16.20",
        }])
        out = bc.fmt_candidates("20260727")
        assert "A+ 圣阳股份" in out
        assert "池#1" in out
        assert "进:触及18.56快速封板" in out
        assert "弃:跌破16.20" in out

    def test_marks_out_of_pool(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_candidates", lambda d: [
            {"grade": "B", "name": "某票", "in_pool": False, "style": "首板打板"},
        ])
        assert "池外" in bc.fmt_candidates("20260727")

    def test_empty(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_candidates", lambda d: [])
        assert "没有候选" in bc.fmt_candidates("20260727")


class TestFmtEmotion:
    def test_uses_live_snapshot_when_running(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_live", lambda: {
            "running": True,
            "snapshot": {"ts": "14:30", "zt_count": 93, "zbgc_count": 14, "lianban_count": 8,
                         "max_board": 5, "break_rate": 0.13, "index": {"上证指数": -0.5}},
            "events": [{"title": "龙头炸板"}],
        })
        out = bc.fmt_emotion("20260728")
        assert "盘中实时 14:30" in out
        assert "涨停 93" in out
        assert "炸板率 13%" in out
        assert "龙头炸板" in out  # 有事件要提示

    def test_falls_back_to_close_emotion(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_live", lambda: {"running": False, "snapshot": None, "events": []})
        monkeypatch.setattr(service, "get_emotion", lambda d: {
            "zt_count": 111, "lianban_count": 8, "max_board": 5, "break_rate": 0.10,
            "seal_success_rate": 0.90, "money_effect": 3.25, "promo_1to2": 0.13,
            "phase_hint": "高潮", "market_state_hint": "震荡抱团",
        })
        out = bc.fmt_emotion("20260727")
        assert "收盘情绪 · 高潮" in out
        assert "赚钱效应 +3.25%" in out

    def test_empty_pool(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_live", lambda: {"running": False, "snapshot": None, "events": []})
        monkeypatch.setattr(service, "get_emotion", lambda d: {"zt_count": 0})
        assert "无涨停池数据" in bc.fmt_emotion("20260101")


class TestFmtNewPanels:
    def test_theme_shows_strength_and_dash(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_theme_heat", lambda d: [
            {"theme": "储能", "zt_count": 5, "lianban_count": 1, "max_board": 3, "pct": 3.28},
            {"theme": "央企", "zt_count": 10, "lianban_count": 1, "max_board": 2, "pct": None},
        ])
        out = bc.fmt_theme("20260727")
        assert "储能" in out and "+3.28%" in out
        assert "央企" in out and "—" in out  # 未匹配到板块要显示占位

    def test_report_text_strips_json_block(self, monkeypatch):
        """长图推送失败时的兜底:正文照发,但尾部给系统解析的 ```json 不能进消息。"""
        from daban_review.app import service

        monkeypatch.setattr(service, "get_report", lambda d: {
            "markdown": '## 一、数据基础\n涨停89家\n\n```json\n[{"code":"000001"}]\n```\n',
        })
        out = bc.fmt_report_text("20260916")
        assert "涨停89家" in out
        assert "json" not in out and "000001" not in out

    def test_report_text_empty(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_report", lambda d: None)
        assert "还没有复盘正文" in bc.fmt_report_text("20260101")

    def test_theme_empty(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_theme_heat", lambda d: [])
        assert "无题材数据" in bc.fmt_theme("20260101")

    def test_ladder_groups_by_board_desc_and_marks_broken(self, monkeypatch):
        """文本天梯与「天梯图」同源:高板在前,断板要标 ✗ + 当日涨跌幅。"""
        from daban_review.app import service

        monkeypatch.setattr(service, "get_ladder_board", lambda d: {
            "rows": [
                {"boards": 3, "stocks": [
                    {"name": "乙", "is_yizi": False, "first_seal": "093442", "last_seal": "093442",
                     "break_times": 0, "broken": False, "pct": 10.0},
                    {"name": "回封的", "is_yizi": False, "first_seal": "092500", "last_seal": "133300",
                     "break_times": 1, "broken": False, "pct": 10.0},
                    {"name": "断了", "is_yizi": False, "first_seal": "", "broken": True, "pct": -4.83},
                ]},
                {"boards": 1, "stocks": [
                    {"name": "甲", "is_yizi": True, "first_seal": "092502", "last_seal": "092502",
                     "break_times": 0, "broken": False, "pct": 10.0},
                ]},
            ],
            "sealed": 2, "broken": 1, "max_board": 3, "total": 3, "industries": [],
        })
        out = bc.fmt_ladder("20260727")
        assert out.index("[3板]") < out.index("[1板]")  # 高板在前
        assert "乙[09:34]" in out                        # 首封时间格式化
        assert "甲[一字]" in out                          # 一字板标记
        assert "✗断了(-4.83%)" in out                    # 断板 + 涨跌幅

    def test_ladder_empty(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_ladder_board", lambda d: {"rows": []})
        assert "无涨停池数据" in bc.fmt_ladder("20260101")

    def test_auction_renders_themes_and_brief(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_auction_live", lambda: {
            "phase": "bidding", "base_date": "20260727", "ts": "09:22:00", "emotion_phase": "高潮",
            "themes": [{"theme": "储能", "members": 3, "avg_gap": 4.2, "max_board": 3, "amount_yi": 2.1}],
            "rows": [{"grade": "A+", "name": "圣阳股份", "gap_pct": 4.5, "prev_boards": 1,
                      "amount_yi": 1.2, "in_candidates": True}],
        })
        monkeypatch.setattr(service, "get_auction_brief", lambda d: {"brief": "电力续强"})
        out = bc.fmt_auction()
        assert "竞价中" in out
        assert "储能" in out and "+4.20%" in out
        assert "★" in out  # 昨晚候选要标星
        assert "电力续强" in out

    def test_auction_no_data(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_auction_live",
                            lambda: {"phase": "closed", "themes": [], "rows": []})
        monkeypatch.setattr(service, "get_auction_brief", lambda d: None)
        assert "暂无竞价数据" in bc.fmt_auction()

    def test_stats_lists_grades(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_candidates_stats", lambda: {
            "overall": {"n": 14, "win_rate": 0.57, "avg_open_prem": 0.031},
            "by_grade": {"A+": {"n": 2, "win_rate": 1.0, "avg_open_prem": 0.09}},
        })
        out = bc.fmt_stats()
        assert "n=14" in out and "57%" in out
        assert "A+" in out and "+9.00%" in out


class TestFmtHoldings:
    def test_renders_pnl_and_verdict(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "list_holdings", lambda: [
            {"code": "002677", "name": "浙江美大", "buy_price": 10.0, "cur_price": 10.5, "pnl_pct": 5.0},
        ])
        monkeypatch.setattr(service, "get_holding_analysis", lambda c: {
            "verdict": {"verdict": "持有", "take_profit": "冲高11.5减半", "stop_loss": "跌破9.8走"},
        })
        out = bc.fmt_holdings()
        assert "浙江美大 +5.00%" in out
        assert "结论:持有" in out
        assert "止盈:冲高11.5减半" in out

    def test_no_verdict_hints_to_run_agent(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "list_holdings", lambda: [
            {"code": "1", "name": "甲", "buy_price": 1.0, "cur_price": None, "pnl_pct": None},
        ])
        monkeypatch.setattr(service, "get_holding_analysis", lambda c: None)
        assert "agent 诊断" in bc.fmt_holdings()

    def test_empty(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "list_holdings", lambda: [])
        assert "没有持仓" in bc.fmt_holdings()


# ---------------------------------------------------------------------------
# handle_command:整体分派
# ---------------------------------------------------------------------------
class TestHandleCommand:
    def test_help_needs_no_service_call(self):
        # 帮助纯静态,不该触发任何 service 调用(没 monkeypatch 也能过)
        act = bc.handle_command("帮助")
        assert act["kind"] == "text"
        assert "复盘" in act["content"] and "问 <问题>" in act["content"]

    def test_unknown_returns_help_not_agent(self):
        """没认出来 → 回指令列表 + 说明不自动调 AI,零成本。"""
        act = bc.handle_command("今天大盘怎么看")
        assert act["kind"] == "text"
        assert "没认出" in act["content"]
        assert "免得花钱" in act["content"]

    def test_review_returns_image_with_date(self, monkeypatch):
        monkeypatch.setattr(bc, "resolve_date", lambda d=None, **k: d or "20260727")
        act = bc.handle_command("复盘 20260723")
        assert act == {"kind": "image", "date": "20260723", "which": "review"}

    def test_image_kinds_mark_which(self, monkeypatch):
        monkeypatch.setattr(bc, "resolve_date", lambda d=None, **k: "20260728")
        assert bc.handle_command("竞价图")["which"] == "auction"
        assert bc.handle_command("天梯图")["which"] == "ladder"
        assert bc.handle_command("持仓图")["which"] == "holding"
        assert bc.handle_command("长图")["which"] == "report"

    def test_ask_carries_question_and_date(self, monkeypatch):
        monkeypatch.setattr(bc, "resolve_date", lambda d=None, **k: "20260727")
        act = bc.handle_command("问 小哈今天走哪个属性")
        assert act["kind"] == "ask"
        assert act["question"] == "小哈今天走哪个属性"
        assert act["date"] == "20260727"

    def test_ask_empty_hints_usage(self):
        assert "要跟问题" in bc.handle_command("问")["content"]

    def test_cost_and_stats_no_date_needed(self, monkeypatch):
        from daban_review.app import service

        monkeypatch.setattr(service, "get_usage_today",
                            lambda: {"count": 2, "cost_cny": 16.0, "cost_usd": 2.2, "total_tokens": 500_000})
        assert "¥16.00" in bc.handle_command("成本")["content"]
        monkeypatch.setattr(service, "get_candidates_stats",
                            lambda: {"overall": {"n": 0, "win_rate": 0, "avg_open_prem": 0}, "by_grade": {}})
        assert "还没有已验证" in bc.handle_command("命中率")["content"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
