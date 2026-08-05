"""候选票客观打分:用打板圈成熟因子阈值,给候选个股定 A+/A/B/C/D 分级 + 仓位建议。

设计原则:
- 纯规则、无主观,与「次日验证」(功能②)同口径,可回测。
- 市值弱化:当前上板多为小市值,市值区分度低,不作为打分因子。
- 因子阈值对标公开实证 + 本地隔日溢价回测校准:封流比对溢价严格单调(本地回测,最强因子)、
  封板越早溢价越高(国金研报;本地回测把基准从**首封**改成**最终封板**,后者判别力更强、
  分档单调,r=-0.270 vs -0.207)、换手越低越好(本地回测 + 华安研报「缩量锁筹」,
  纠正了 SkillHub「5-15% 最优」在缩量市不成立)、连板身位晋级率、情绪周期基准仓位(SkillHub 打板3)、
  弱转强(本地回测,与封流比/换手方向相反的独立信号)。
- A+ 档用硬门槛(AND)而非纯凑分:SkillHub 打板3 实测线性加权评分与次日收益近乎无关(r≈0)后
  弃排序转硬门槛分类,国金/华安亦为单因子分层。故加权分只用于 A/B/C/D 初筛,A+ 须过硬门槛;
  各因子权重待用「次日验证」的隔日溢价回归校准,勿长期依赖先验拍值。
"""

from __future__ import annotations

# 情绪周期 → (基准分, 仓位建议)。打板圈通用:冰点空仓、回暖重仓、高潮减仓、退潮空仓。
_PHASE_BASE: dict[str, tuple[int, str]] = {
    "高潮": (0, "2-3成"),   # 全民狂热,追高风险大,减仓落袋
    "发酵": (1, "4-6成"),   # 主升加仓做主线
    "修复": (0, "3-4成"),   # 情绪试探性修复
    "分歧": (0, "2-3成"),
    "冰点": (-1, "≤2成"),   # 观望等拐点
    "退潮": (-2, "≤1成"),   # 空仓保本金,且个股全降级
    "未知": (0, "3成"),
}

_DOWNGRADE = {"A+": "A", "A": "B", "B": "C", "C": "D", "D": "D"}


def _first_seal_minutes(first_seal: str) -> int | None:
    """首封时间 HHMMSS 字符串(如 '092500')→ 当日分钟数;解析失败返回 None。"""
    digits = "".join(ch for ch in str(first_seal) if ch.isdigit())
    if len(digits) < 4:
        return None
    hh, mm = int(digits[:2]), int(digits[2:4])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh * 60 + mm


def grade_candidate(stock: dict, phase_hint: str) -> dict:
    """对一只候选个股打分。

    stock: ladder.stock_profiles 的画像 dict(boards/seal_strength/first_seal/break_times/turnover)。
      可选 `w2s`(bool)= 弱转强(前一交易日在炸板池、今日涨停)。**供不上就不给这份加分**,
      所以老调用方不用改;要吃这个因子的调用方(候选池/回测/次日验证)负责先标好。
    phase_hint: 当日情绪周期(emotion.phase_hint)。
    返回 {grade, position, score, reasons}。
    """
    base, position = _PHASE_BASE.get(phase_hint, (0, "3成"))
    score = base
    reasons: list[str] = []

    boards = int(stock.get("boards", 0) or 0)
    seal = float(stock.get("seal_strength", 0.0) or 0.0)  # 封流比
    breaks = int(stock.get("break_times", 0) or 0)
    turnover = float(stock.get("turnover", 0.0) or 0.0)   # 换手率(%)
    fmin = _first_seal_minutes(stock.get("first_seal", ""))
    # 封板时间基准用**最终封板**(几点才真正稳住),缺失时退回首封。
    # 为什么不用首封:见下方因子注释,last_seal 判别力更强且单调。
    lmin = _first_seal_minutes(stock.get("last_seal", "")) or fmin

    # 封单强度(封流比):本地回测显示对隔日溢价严格单调(1-2%→+2%,2-3%→+3%,≥3%→+5%),按档给分
    if seal >= 0.03:
        score += 3
        reasons.append(f"超强封(封流比{seal:.1%})")
    elif seal >= 0.02:
        score += 2
        reasons.append(f"强封(封流比{seal:.1%})")
    elif seal >= 0.01:
        score += 1
        reasons.append(f"中封(封流比{seal:.1%})")
    elif 0 < seal < 0.01:
        score -= 1
        reasons.append(f"弱封(封流比{seal:.2%})")

    # 封板时间:用**最终封板 last_seal**(几点才真正稳住),不用首封。
    # 本地回测 22 交易日 1508 样本,last_seal 分档全程单调:
    #   ≤9:45   n=372 胜67% 均+3.36%   9:45-10:30 n=308 胜61% 均+1.49%
    #   10:30-11:30 n=202 胜61% 均+1.09%   13:00-14:00 n=326 胜60% 均+0.98%
    #   ≥14:00  n=300 胜44% 均**-0.10%**  ← 唯一负溢价档
    # 相关性 last_seal r=-0.270 强于 first_seal r=-0.207;且 first_seal 分档非单调
    # (13:00-14:00 档 +1.11% 反而高于 10:30-11:30 档 +0.95%)。
    # **不是 break_times 的马甲**:分组控制后两组内部各自单调 —— 未炸板但尾盘才首封的
    # 103 只是全样本最差(胜38% / 均-0.51%),而炸过板但 ≤9:45 就稳住的 94 只反而
    # 胜65% / 均+2.79%。结论:炸板不可怕,拖到尾盘才稳住才可怕。
    # 两个因子高度相关(last≠first 几乎等价于炸过板),**只留 last 一个**,别重复计分。
    if lmin is not None:
        if lmin <= 9 * 60 + 45:
            score += 2
            reasons.append("超早封(≤9:45稳住,隔日溢价最高)")
        elif lmin >= 14 * 60:
            score -= 2
            reasons.append("尾盘才封(≥14:00,隔日溢价转负)")
        # 9:45–14:00 中性:三档都在 59-61% 胜率 / +1.0~1.5%,与全样本无区分

    # 炸板次数:0 次干净;≥3 次盘中分歧极大
    if breaks == 0:
        score += 1
    elif breaks >= 3:
        score -= 2
        reasons.append(f"炸板{breaks}次(分歧大)")

    # 换手率:回测与华安研报一致「越低越好」(缩量锁筹,<5% 溢价最高);高换手筹码涣散。5-15% 中性
    if 0 < turnover < 5:
        score += 1
        reasons.append("缩量锁筹(换手<5%)")
    elif 15 < turnover <= 35:
        score -= 1
        reasons.append(f"换手偏高{turnover:.0f}%")
    elif turnover > 35:
        score -= 1
        reasons.append(f"高换手{turnover:.0f}%(涣散)")

    # 连板身位:低位 1-3 板接力性价比高;4 板晋级率已跌破 20%(承上启下高位起点);5 板+赔率差易断板
    if boards >= 5:
        score -= 2
        reasons.append(f"{boards}板高位(接力风险大)")
    elif boards == 4:
        score -= 1
        reasons.append("4板高位(接力起点,赔率转差)")
    elif 1 <= boards <= 3:
        score += 1

    # 弱转强(前日炸板 → 今日涨停):本地回测 22 个交易日 1508 样本,弱转强 n=27
    # 胜率 74.1% / 均溢价 +3.19%,同板位对照(它们 26/27 是首板)1 板其余 n=1254
    # 胜率 58% / 均 +1.24% —— 差距没被身位吃掉;置换检验 p=0.0136。
    # **这是与现有因子方向相反的独立信号**:弱转强票平均封流比更低(0.82% vs 1.08%)、
    # 换手更高(13.5 vs 7.1),按上面的「强封加分/低换手加分」它们本该被扣分。
    # 给 +2(与「超早封」同档,那条的超额是 +1.3pp、这条 +1.8pp)。
    # ⚠️ n=27 偏薄(占涨停票约 1.8%),样本随 cli backtest 自动积累,过一个月复核一次。
    if stock.get("w2s"):
        score += 2
        reasons.append("弱转强(昨炸板今涨停)")

    if score >= 4:
        grade = "A+"
    elif score >= 2:
        grade = "A"
    elif score >= 0:
        grade = "B"
    elif score >= -2:
        grade = "C"
    else:
        grade = "D"

    # A+ 硬门槛:最高档不靠凑分,须同时满足 超早封 + 强封 + 低位 + 全程不炸,任一硬伤只给 A。
    # 依据:SkillHub 打板3 实测加权评分排序与次日收益 r≈0 后弃排序、转硬门槛分类。
    if grade == "A+":
        hard_ok = (
            lmin is not None and lmin <= 9 * 60 + 45  # 超早封 ≤9:45(按最终封板,与上面因子同基准)
            and seal >= 0.02                          # 强封(封流比≥2%)
            and 1 <= boards <= 3                      # 低位身位
            and breaks == 0                           # 全程不炸
        )
        if not hard_ok:
            grade = "A"
            reasons.append("未过A+硬门槛(需超早封+强封+低位+0炸板),降A")

    # 退潮期全线降级(市面共识:退潮所有推荐降 1-2 级,SkillHub 打板3;此处在 base -2 基础上再降 1 级)
    if phase_hint == "退潮":
        grade = _DOWNGRADE[grade]

    # D 类无论周期都回避
    if grade == "D":
        position = "回避/空仓"

    return {"grade": grade, "position": position, "score": score, "reasons": reasons}
