"""飞书机器人指令层:文本 → 动作。

**纯逻辑,不发消息、不连 ws**:`handle_command` 只返回 {kind, ...},由 bot.py 负责发送。
能离线单测,也能 `bot.py --once "候选"` 不依赖飞书自检。

设计原则(踩过的坑):**模糊输入绝不默认走 agent**。早期把不认识的文本兜给 agent,
结果「发一下今日复盘给我」「分析一下盘前竞价」两条本可读库直接答的问题各烧 ¥8。
现在:关键词包容匹配 → 命中指令(零成本);要 agent 必须显式写「问 xxx」;
都不匹配就回指令列表。
"""

from __future__ import annotations

import datetime as dt
import re

# 自由提问必须的显式前缀 —— 防误触烧钱
ASK_PREFIXES = ("问", "提问", "ask")

HELP = """打板复盘机器人 · 指令

【图】
复盘        今日复盘海报(可加日期:复盘 20260723)
天梯图      连板天梯(按板级 + 断板划线 + 行业分布)
竞价图      盘前竞价决策图

【盘面】
竞价        盘前竞价:题材方向 + 高开榜 + 盘前解读
情绪        实时/收盘:涨停·连板·炸板率·赚钱效应
题材        题材热度 + 板块涨幅强度
天梯        连板天梯(按板级 + 封单强度)

【交易】
候选        作战清单(评级 / 进 / 弃)
持仓        盈亏 + 止盈止损价位
命中率      候选按评级的滚动胜率与均溢价

【其他】
成本        今日 AI 花费
帮助        看这条

问 <问题>   ← 让 agent 深度分析(约 ¥8、1-2 分钟)
            例:问 小哈今天走哪个属性

上面指令都是读库,零成本;只有「问」会花钱。"""

# 动作 key → 别名(精确匹配优先,其次按这些词做包容匹配)
_ROUTES: dict[str, tuple[str, ...]] = {
    # 带「图」的先声明:「天梯图」含「天梯」,靠声明序保证图优先命中
    "ladder_image": ("天梯图", "梯队图", "连板图"),
    "auction_image": ("竞价图", "盘前图", "竞价海报"),
    "review": ("复盘", "海报", "复盘图", "review", "poster"),
    "auction": ("竞价", "盘前", "抢筹", "auction"),
    "candidates": ("候选", "作战", "作战清单", "打板清单", "cand", "clist"),
    "emotion": ("情绪", "实时", "温度", "live", "emotion"),
    "theme": ("题材", "板块", "主线", "theme"),
    "ladder": ("天梯", "梯队", "连板梯队", "ladder"),
    "holdings": ("持仓", "仓位", "hold", "holdings"),
    "stats": ("命中率", "胜率", "回测", "stats"),
    "cost": ("成本", "花费", "token", "cost"),
    "help": ("帮助", "help", "菜单", "指令", "?", "？"),
}

_DATE_RE = re.compile(r"\b(20\d{6})\b")


def parse(text: str) -> tuple[str, str | None, str]:
    """解析文本 → (动作 key, 日期或 None, 提问内容)。

    优先级:①「问 xxx」显式提问 ②精确匹配指令 ③关键词包容匹配 ④unknown(回指令列表)。
    包容匹配让「发一下今日复盘给我」也能命中 review,不必背精确指令。
    """
    t = (text or "").strip()
    if not t:
        return "unknown", None, ""

    # ① 显式提问前缀
    for p in ASK_PREFIXES:
        if t.lower().startswith(p):
            q = t[len(p):].strip(" :：,,、")
            return ("ask", _pick_date(q), q) if q else ("ask_empty", None, "")

    date = _pick_date(t)
    body = _DATE_RE.sub("", t).strip().lower()

    # ② 精确匹配
    for key, aliases in _ROUTES.items():
        if body in aliases:
            return key, date, ""

    # ③ 关键词包容(「竞价图」要先于「竞价」命中,故按 _ROUTES 声明序遍历)
    for key, aliases in _ROUTES.items():
        if any(a in body for a in aliases if len(a) >= 2):
            return key, date, ""

    return "unknown", date, ""


def _pick_date(text: str) -> str | None:
    m = _DATE_RE.search(text or "")
    return m.group(1) if m else None


def resolve_date(date: str | None = None, *, today: str | None = None) -> str:
    """定日期:显式给了就用;否则用「最近一个已生成复盘的交易日」。

    盘前问「候选」时今天还没复盘,必须退到上一交易日,否则拿到空。
    """
    if date:
        return date
    from ..app import service

    today = today or dt.date.today().strftime("%Y%m%d")
    if service.get_report(today):
        return today
    for d in service.list_dates():  # 已按倒序
        if d < today and service.get_report(d):
            return d
    return today


def _pct(v, digits: int = 0) -> str:
    """0.13 → 13%;None → —"""
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def fmt_seal(first_seal) -> str:
    """首封时间 'HHMMSS' → 'HH:MM';解析不了返回空串。"""
    digits = "".join(ch for ch in str(first_seal or "") if ch.isdigit())
    return f"{digits[:2]}:{digits[2:4]}" if len(digits) >= 4 else ""


# ---- 各指令渲染(手机上要能一眼看完,别堆长表)----

def fmt_emotion(date: str) -> str:
    """优先用盘中实时快照(watcher 写的);未运行则回落当日收盘情绪。"""
    from ..app import service

    live = service.get_live()
    s = live.get("snapshot") if live.get("running") else None
    if s:
        lines = [
            f"📈 盘中实时 {s.get('ts', '')}",
            f"涨停 {s['zt_count']} · 连板 {s['lianban_count']} · 最高 {s['max_board']}板",
            f"炸板 {s['zbgc_count']} · 炸板率 {_pct(s['break_rate'])}",
        ]
        idx = " ".join(f"{k}{v:+.2f}%" for k, v in (s.get("index") or {}).items() if v is not None)
        if idx:
            lines.append(f"指数近15min {idx}")
        evs = live.get("events") or []
        if evs:
            lines.append(f"⚠️ 今日事件 {len(evs)} 条,最新:{evs[0]['title']}")
        return "\n".join(lines)

    e = service.get_emotion(date)
    if not e.get("zt_count"):
        return f"{date} 无涨停池数据(盘中监控也未运行)。"
    me = e.get("money_effect")
    return "\n".join([
        f"📊 {date} 收盘情绪 · {e['phase_hint']}",
        f"涨停 {e['zt_count']} · 连板 {e['lianban_count']} · 最高 {e['max_board']}板",
        f"炸板率 {_pct(e['break_rate'])} · 封板率 {_pct(e['seal_success_rate'])}",
        f"赚钱效应 {'—' if me is None else f'{me:+.2f}%'} · 1进2 {_pct(e.get('promo_1to2'))}",
        e.get("market_state_hint", ""),
    ]).strip()


def fmt_candidates(date: str) -> str:
    from ..app import service

    rows = service.get_candidates(date)
    if not rows:
        return f"{date} 没有候选(该日未生成复盘,或 agent 判断四风格都不参与)。"
    out = [f"🎯 {date} 作战清单({len(rows)} 只)"]
    for c in rows:
        head = f"{c['grade'] or '—'} {c['name']}"
        if c.get("position"):
            head += f" · {c['position']}"
        if c.get("pool_rank"):
            head += f" · 池#{c['pool_rank']}"
        if not c.get("in_pool", True):
            head += " · ⚠️池外"
        out += ["", head]
        if c.get("style"):
            out.append(f"[{c['style']}]")
        if c.get("trigger"):
            out.append(f"进:{c['trigger']}")
        if c.get("giveup"):
            out.append(f"弃:{c['giveup']}")
    return "\n".join(out)


def fmt_auction() -> str:
    """盘前竞价决策台 + 已落库的 agent 盘前解读(都是读库,零成本)。"""
    from ..app import service

    d = service.get_auction_live()
    phase = {"pre_cancel": "9:15–9:20 可撤单·仅参考", "bidding": "竞价中·不可撤",
             "opened": "已定格", "closed": "当日开盘结果"}.get(d.get("phase", ""), "")
    out = [f"🔔 盘前竞价 · {phase} {d.get('ts', '')}"]
    if d.get("base_date"):
        out.append(f"基于 {d['base_date']} 涨停池 · {d.get('emotion_phase', '')}")
    if d.get("note"):
        out.append(d["note"])

    themes = d.get("themes") or []
    if themes:
        out.append("\n方向(题材竞价强弱):")
        for t in themes[:5]:
            out.append(f"· {t['theme']} {t['members']}只 均高开{t['avg_gap']:+.2f}% "
                       f"最高{t['max_board']}板 {t['amount_yi']}亿")
    rows = d.get("rows") or []
    if rows:
        out.append("\n高开榜 Top8:")
        for r in rows[:8]:
            star = "★" if r.get("in_candidates") else " "
            out.append(f"{star}{r['grade']:<2} {r['name']} {r['gap_pct']:+.2f}% "
                       f"{r['prev_boards']}板 {r['amount_yi']}亿")
    if not themes and not rows:
        out.append("暂无竞价数据(9:20 前撮合价未定,或非交易时段)。")

    brief = (service.get_auction_brief(dt.date.today().strftime("%Y%m%d")) or {}).get("brief")
    if brief:
        out.append(f"\n🤖 盘前解读:\n{brief}")
    return "\n".join(out)


def fmt_theme(date: str) -> str:
    from ..app import service

    rows = service.get_theme_heat(date)
    if not rows:
        return f"{date} 无题材数据。"
    out = [f"🔥 {date} 题材热度(板块涨幅)"]
    for t in rows[:8]:
        strength = "—" if t.get("pct") is None else f"{t['pct']:+.2f}%"
        out.append(f"· {t['theme']} 涨停{t['zt_count']} 连板{t['lianban_count']} "
                   f"最高{t['max_board']}板 | 板块{strength}")
    out.append("\n(板块涨幅来自同花顺涨停板块榜,只出当日 top20,冷门题材显示「—」)")
    return "\n".join(out)


def fmt_ladder(date: str) -> str:
    """与「天梯图」同一数据源(含断板票)—— 断板=高度被打掉,是天梯最关键的信息,文本版不能缺。"""
    from ..app import service

    d = service.get_ladder_board(date)
    if not d.get("rows"):
        return f"{date} 无涨停池数据。"
    out = [f"🪜 {date} 连板天梯 · 涨停{d['sealed']} 断板{d['broken']} 最高{d['max_board']}板"]
    for row in d["rows"]:
        parts = []
        for s in row["stocks"][:6]:
            if s["broken"]:
                parts.append(f"✗{s['name']}({s['pct']:+.2f}%)")  # 断板 + 当日涨跌幅
            else:
                # 时间=最终封板;炸过又回封的加 ↺,封板质量打折
                t = fmt_seal(s.get("last_seal") or s.get("first_seal")) or "—"
                tag = "一字" if s["is_yizi"] else t + ("↺" if (s.get("break_times") or 0) > 0 else "")
                parts.append(f"{s['name']}[{tag}]")
        more = f" …+{len(row['stocks']) - 6}" if len(row["stocks"]) > 6 else ""
        out.append(f"[{row['boards']}板] x{len(row['stocks'])}:" + "、".join(parts) + more)
    out.append("\n[]内=最终封板时间(↺=炸板后回封);✗=昨日连板今日断板(后跟当日涨跌幅)。要图发「天梯图」。")
    return "\n".join(out)


def fmt_holdings() -> str:
    from ..app import service

    rows = service.list_holdings()
    if not rows:
        return "当前没有持仓。在网页端「盘中 → 添加持仓」录入后,这里就能看盈亏与买卖点。"
    out = [f"💼 持仓 {len(rows)} 只"]
    for h in rows:
        pnl = "—" if h.get("pnl_pct") is None else f"{h['pnl_pct']:+.2f}%"
        out += ["", f"{h['name'] or h['code']} {pnl}"
                    f"(成本 {h['buy_price']} → 现价 {h.get('cur_price') or '—'})"]
        v = (service.get_holding_analysis(h["code"]) or {}).get("verdict") or {}
        if v.get("verdict"):
            out.append(f"结论:{v['verdict']}")
        if v.get("take_profit"):
            out.append(f"止盈:{v['take_profit']}")
        if v.get("stop_loss"):
            out.append(f"止损:{v['stop_loss']}")
        if not v:
            out.append("(盘后跑一次 agent 诊断才有买卖点)")
    return "\n".join(out)


def fmt_stats() -> str:
    from ..app import service

    s = service.get_candidates_stats()
    ov = s.get("overall") or {}
    if not ov.get("n"):
        return "还没有已验证的候选(次日收盘后才能算隔日溢价)。"
    out = [f"📐 候选滚动命中率(n={ov['n']})",
           f"总体 胜率{_pct(ov['win_rate'])} · 均开盘溢价{ov['avg_open_prem'] * 100:+.2f}%", ""]
    for g in ("A+", "A", "B", "C", "D"):
        st = (s.get("by_grade") or {}).get(g)
        if st:
            out.append(f"{g:<2} n={st['n']:<3} 胜率{_pct(st['win_rate'])} "
                       f"均溢价{st['avg_open_prem'] * 100:+.2f}%")
    return "\n".join(out)


def fmt_cost() -> str:
    from ..app import service

    u = service.get_usage_today()
    if not u.get("count"):
        return "今天还没调用过 AI,零花费。"
    return (f"💰 今日 AI 花费 ¥{u['cost_cny']:.2f}(${u['cost_usd']:.2f})\n"
            f"{u['count']} 次 · {u['total_tokens'] / 1000:.0f}k tokens")


def handle_command(text: str) -> dict:
    """文本 → 动作。返回:
    {kind:"text", content}
    {kind:"image", date, which:"review"|"auction"}
    {kind:"ask", question, date}
    """
    key, date, question = parse(text)

    if key == "help" or key == "unknown":
        prefix = "" if key == "help" else "没认出这条指令(不会自动调 AI 免得花钱)。\n\n"
        return {"kind": "text", "content": prefix + HELP}
    if key == "ask_empty":
        return {"kind": "text", "content": "「问」后面要跟问题,例:问 小哈今天走哪个属性"}
    if key == "cost":
        return {"kind": "text", "content": fmt_cost()}
    if key == "stats":
        return {"kind": "text", "content": fmt_stats()}
    if key == "holdings":
        return {"kind": "text", "content": fmt_holdings()}
    if key == "auction":
        return {"kind": "text", "content": fmt_auction()}
    if key == "auction_image":
        return {"kind": "image", "date": resolve_date(date), "which": "auction"}
    if key == "ladder_image":
        return {"kind": "image", "date": resolve_date(date), "which": "ladder"}

    d = resolve_date(date)
    if key == "review":
        return {"kind": "image", "date": d, "which": "review"}
    if key == "candidates":
        return {"kind": "text", "content": fmt_candidates(d)}
    if key == "emotion":
        return {"kind": "text", "content": fmt_emotion(d)}
    if key == "theme":
        return {"kind": "text", "content": fmt_theme(d)}
    if key == "ladder":
        return {"kind": "text", "content": fmt_ladder(d)}
    return {"kind": "ask", "question": question, "date": d}
