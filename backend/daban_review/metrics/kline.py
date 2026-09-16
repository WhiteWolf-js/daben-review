"""热门票日 K 线量价特征:供 agent 感知市场审美(强势票共性形态)与量价周期。

特征选择贴合打板量价:
- 量比 vr = 当日量 / 近5日均量:相对放量/缩量(代理换手活跃度,mootdx 日线无换手率字段)。
- 量能梯度 vol_trend:近3日 vs 前3日量能,连续放量/缩量的节奏。
- 形态标记 tag:缩量涨停(锁筹强)/ 放量涨停(分歧)/ 一字 / 冲高回落 —— 直接服务
  「缩量连板 vs 放量连板」的判断。
"""

from __future__ import annotations

import pandas as pd

from ..data.akshare_client import daily_bars

_ZT = 0.095  # 涨停近似阈值(10%板;20%板 pct 更高也覆盖)


def _tag(pct: float, amp: float, vr: float, pos: float) -> str:
    is_zt = pct >= _ZT
    if is_zt and amp <= 0.02:
        return "一字"
    if is_zt and vr < 0.8:
        return "缩量涨停"  # 锁筹强、抛压小
    if is_zt and vr >= 1.5:
        return "放量涨停"  # 分歧/出货压力
    if is_zt:
        return "涨停"
    if amp >= 0.07 and pos < 0.4:
        return "冲高回落"  # 近似炸板/上影
    if pct <= -0.07:
        return "大跌"
    return "普通"


def _bar_features(d: pd.DataFrame, date: str, n_days: int) -> list[dict]:
    d = d.reset_index(drop=True)
    idx = d.index[d["date"] == date]
    end = int(idx[0]) if len(idx) else len(d) - 1  # 截到 date(含);无则用最后一根
    start = max(0, end - n_days + 1)
    bars = []
    for i in range(start, end + 1):
        row = d.iloc[i]
        prev = float(d.iloc[i - 1]["close"]) if i > 0 else float(row["open"])
        c, h, l, v = float(row["close"]), float(row["high"]), float(row["low"]), float(row["vol"])
        vols = [float(d.iloc[j]["vol"]) for j in range(max(0, i - 5), i)]
        avg = sum(vols) / len(vols) if vols else v
        pct = round(c / prev - 1, 4) if prev else 0.0
        amp = round((h - l) / prev, 4) if prev else 0.0
        vr = round(v / avg, 2) if avg else 1.0
        pos = round((c - l) / (h - l), 2) if h > l else 1.0
        bars.append({"d": str(row["date"])[4:], "pct": pct, "amp": amp, "vr": vr, "pos": pos, "tag": _tag(pct, amp, vr, pos)})
    return bars


def _vol_trend(d: pd.DataFrame, date: str) -> str:
    """量能梯度:近3日均量 vs 前3日均量,判断连续放量/缩量节奏。"""
    d = d.reset_index(drop=True)
    idx = d.index[d["date"] == date]
    end = int(idx[0]) if len(idx) else len(d) - 1
    if end < 5:
        return "样本不足"
    recent = [float(d.iloc[j]["vol"]) for j in range(end - 2, end + 1)]
    prev = [float(d.iloc[j]["vol"]) for j in range(end - 5, end - 2)]
    r = (sum(recent) / 3) / (sum(prev) / 3) if sum(prev) else 1.0
    if r >= 1.3:
        return f"连续放量(近3日量能×{r:.1f})"
    if r <= 0.7:
        return f"持续缩量(近3日量能×{r:.1f})"
    return f"量能平稳(×{r:.1f})"


def build_hot_klines(stocks: list[dict], date: str, n_days: int = 12) -> list[dict]:
    """给热门票打包近 n_days 日 K 线量价特征。

    stocks: [{code, name, boards, turnover}](turnover 为当日涨停池换手率,非涨停票为 None)。
    每票输出 bars 序列 + vol_trend(量能梯度)。取不到日线的票跳过。
    """
    out = []
    for s in stocks:
        try:
            d = daily_bars(s["code"], n_days + 8)
        except Exception:  # noqa: BLE001
            continue
        if d is None or d.empty:
            continue
        bars = _bar_features(d, date, n_days)
        if not bars:
            continue
        out.append({
            "code": s["code"], "name": s["name"], "boards": s.get("boards", 0),
            "turnover_today": s.get("turnover"),
            "vol_trend": _vol_trend(d, date),
            "bars": bars,
        })
    return out


def volume_ratio(code: str, date: str, df=None) -> float | None:
    """某票某日量比 = 当日量 / 近5日均量(口径同 ``_bar_features`` 里的 vr)。

    抽成单点函数供候选池缩量降权与历史模式扫描复用,口径单一。日线不足6根、
    无当日行或拉取失败返回 None(调用方据此视为「量能不可判」,不当缩量处理)。

    df 可注入预取的日线(批量扫描时复用同一份,避免重复拉 daily_bars);不传则自取8根。
    """
    if df is None:
        try:
            df = daily_bars(code, 8)
        except Exception:  # noqa: BLE001 单票拉取失败不阻断调用方
            return None
    if df is None or df.empty:
        return None
    d = df.reset_index(drop=True)
    idx = d.index[d["date"] == date]
    if not len(idx):
        return None
    i = int(idx[0])
    v = float(d.iloc[i]["vol"])
    vols = [float(d.iloc[j]["vol"]) for j in range(max(0, i - 5), i)]
    if not vols:
        return None
    avg = sum(vols) / len(vols)
    return round(v / avg, 2) if avg else 1.0
