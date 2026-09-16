import axios from "axios";
import { fetchEventSource } from "@microsoft/fetch-event-source";

// 后端地址跟随访问前端所用的主机名:本机走 localhost,手机走电脑局域网 IP
export const BASE = `http://${window.location.hostname}:8000`;

const http = axios.create({ baseURL: BASE });

export interface Emotion {
  zt_count: number;
  lianban_count: number;
  max_board: number;
  zbgc_count: number;
  dt_count: number;
  seal_success_rate: number;
  break_rate: number;
  money_effect: number | null;
  height_dist: Record<string, number>;
  promo_1to2: number | null;
  promo_high: number | null;
  promo_overall: number | null;
  phase_hint: string;
  market_state_hint: string;
}

export interface Stock {
  code: string;
  name: string;
  boards: number;
  pct: number;
  seal_strength: number;
  first_seal: string;
  break_times: number;
  turnover: number;
  zt_stat: string;
  industry: string;
}

export type Ladder = Record<string, Stock[]>;

export interface SeriesPoint {
  date: string;
  zt_count: number;
  lianban_count: number;
  max_board: number;
  break_rate: number;
  promo_overall: number | null;
  money_effect: number | null;
}

export const getDates = () => http.get<{ dates: string[] }>("/api/dates").then((r) => r.data.dates);
export const getEmotion = (d: string) => http.get<Emotion>(`/api/emotion/${d}`).then((r) => r.data);
export const getLadder = (d: string) => http.get<Ladder>(`/api/ladder/${d}`).then((r) => r.data);

// ---- 天梯图(封住 + 昨日连板今日断板 + 行业分布)----
export interface LadderCell {
  code: string;
  name: string;
  industry: string; // 申万行业(静态分类,只进 tooltip)
  // 格子里显示的「所属板块」= 当天真形成板块效应的题材(≥2只涨停);
  // 依次回退:今日热门题材 → 今日碎片题材 → 昨日题材(断板票) → 行业
  sector: string;
  sector_hot: boolean; // true=能在题材热度里找到(有同题材联动票),前端亮色;false=孤票/碎片,暗一档

  first_seal: string; // HHMMSS,断板票为空
  last_seal?: string; // 最终封板时间(展示用:几点才真正稳住)
  break_times?: number; // >0 = 炸板后回封,封板质量打折
  seal_minutes: number | null; // 按最终封板算,用于排序
  is_yizi: boolean; // ≤9:25 封住且全天未开板 = 真一字板
  seal_strength: number;
  pct: number;
  broken: boolean; // true=昨日连板今日断板,画删除线 + 显示涨跌幅
  // true=涨停池未收录但收盘涨幅已到涨停(反复炸板尾盘回封),封板时刻与封单强度未知
  reseal?: boolean;
}
export interface LadderBoard {
  rows: { boards: number; stocks: LadderCell[] }[];
  industries: { name: string; count: number }[];
  total: number;
  sealed: number;
  broken: number;
  max_board: number;
}
export const getLadderBoard = (d: string) =>
  http.get<LadderBoard>(`/api/ladder-board/${d}`).then((r) => r.data);

// ---- 盘中情绪切换(板块分时均涨幅曲线 + 退潮/接棒配对 + 封板时序)----
export interface RotationLeader {
  code: string;
  name: string;
  pct: number;
  boards: number;
  first_seal: string;
  break_times: number;
}
export interface RotationCurve {
  name: string;
  count: number;
  points: { t: string; pct: number }[]; // 15 分钟桶
  open: number; // 09:35
  peak: number;
  peak_at: string;
  close: number;
  fade: number; // 峰值 − 收盘,越大越是退潮方
  am_pm: number; // 收盘 − 11:30,午后净变化
  shape: string; // 早盘冲高回落 / 盘中接棒 / 尾盘走强 / 冲高回落 / 全天平推 / 全天弱
  leaders: RotationLeader[];
}
export interface Rotation {
  fader: string;
  taker: string;
  fader_peak: number;
  fader_peak_at: string;
  fader_close: number;
  fader_fade: number;
  taker_open: number;
  taker_peak_at: string;
  taker_close: number;
  taker_rise: number;
  evidence: string;
}
export interface IntradayRotation {
  date: string;
  universe: number; // 全口径只数(涨停+炸板+昨日涨停)
  fetched: number; // 实际取到分时的只数
  groups: RotationCurve[]; // 大类口径(8 桶,固定顺序)
  industries: RotationCurve[]; // 行业口径(≥3 只,按收盘强弱)
  rotations: Rotation[]; // 行业层配对
  group_rotations: Rotation[]; // 大类层配对
  seal_timeline: { t: string; sealed: Record<string, number>; broken: Record<string, number> }[];
}
// 首次算某天要拉 200+ 只分时(约 15s),之后后端走缓存
export const getIntradayRotation = (d: string) =>
  http.get<IntradayRotation>(`/api/intraday-rotation/${d}`).then((r) => r.data);
export const getSeries = (limit = 40) =>
  http.get<{ series: SeriesPoint[] }>(`/api/emotion-series?limit=${limit}`).then((r) => r.data.series);
export const getReport = (d: string) =>
  http.get<{ date: string; markdown: string; created_at: string }>(`/api/report/${d}`).then((r) => r.data);

/** 分时弹窗要的当日资金画像;非涨停/非炸板票为 null */
export interface IntradayProfile {
  source: "limitup" | "zbgc"; // zbgc=炸板票,没封住所以无封单数据
  boards: number;
  zt_stat: string;
  seal_strength: number | null; // 封流比 = 封板资金/流通市值
  seal_amount: number | null; // 封板资金(元)
  first_seal: string; // HHMMSS
  last_seal: string;
  break_times: number;
  turnover: number | null; // 换手率 %
  amount: number | null; // 成交额(元)
  float_mv: number | null; // 流通市值(元)
  industry: string;
}
export interface Intraday {
  code: string;
  prev_close: number | null;
  points: { t: string; c: number; v: number }[];
  profile: IntradayProfile | null;
}
export const getIntraday = (code: string, date: string) =>
  http.get<Intraday>(`/api/intraday/${code}/${date}`).then((r) => r.data);

export interface AuctionRow {
  code: string;
  name: string;
  boards: number;
  industry: string;
  open: number;
  prev_close: number;
  gap_pct: number;
  amount_yi: number;
}
export const getAuction = (date: string) =>
  http.get<AuctionRow[]>(`/api/auction/${date}`).then((r) => r.data);

// ---- 盘前竞价决策台(题材在上、票在下)----
/** pre_cancel=9:15–9:20 可撤单仅参考 / bidding=9:20–9:25 / opened=已定格 / closed=当日开盘结果 */
export type AuctionPhase = "pre_cancel" | "bidding" | "opened" | "closed";
/** up=抢筹在加 / down=有人砸 / flat=持平 / none=无历史 */
export type GapTrend = "up" | "down" | "flat" | "none";

export interface AuctionLiveStock {
  code: string;
  name: string;
  prev_boards: number;
  gap_pct: number;
  gap_trend: GapTrend;
  amount_yi: number;
  grade: string;
  in_candidates: boolean;
}
export interface AuctionTheme {
  theme: string;
  members: number;
  avg_gap: number;
  max_board: number;
  amount_yi: number;
  strength: number;
  stocks: AuctionLiveStock[];
}
export interface AuctionLiveRow extends AuctionLiveStock {
  seal_strength: number;
  ref_price: number;
  last_close: number;
  bid_vol: number;
  ask_vol: number;
  bid_ask_ratio: number | null;
  theme: string[];
  notes: string[];
}
export interface AuctionLive {
  phase: AuctionPhase;
  base_date: string | null;
  ts?: string;
  emotion_phase?: string;
  themes: AuctionTheme[];
  rows: AuctionLiveRow[];
  note?: string;
}
export const getAuctionLive = () =>
  http.get<AuctionLive>("/api/auction-live").then((r) => r.data);

/** 盘前 agent 解读(9:25:30 出图时生成并落库);未生成时返回 {} */
export interface AuctionBrief {
  date?: string;
  brief?: string;
  created_at?: string;
}
export const getAuctionBrief = () =>
  http.get<AuctionBrief>("/api/auction-brief").then((r) => r.data);

export interface ThemeRow {
  theme: string;
  zt_count: number;
  lianban_count: number;
  max_board: number;
  stocks: { code: string; name: string; boards: number }[];
  // 板块强度(同花顺涨停板块榜匹配所得,与涨停原因同源、有历史)。同花顺只出 top20 板块,
  // 冷门题材匹配不到时为 null
  pct: number | null; // 板块涨幅 %
  board_high: string | null; // 板块内最高身位,如「8天7板」
  board_zt: number | null; // 同花顺口径板块涨停数
}
export const getThemeHeat = (date: string) =>
  http.get<ThemeRow[]>(`/api/theme-heat/${date}`).then((r) => r.data);

// ---- 异动榜(N日累计涨幅)----
export type AbnormalTier = "triple" | "double" | "entering" | "warm";

export interface AbnormalRow {
  code: string;
  name: string;
  price: number;
  pct_today: number; // 小数,0.1 = 10%
  pct_window: number;
  boards: number;
  industry: string;
  themes: string[];
  tier: AbnormalTier;
  actual_window: number;
}

export interface AbnormalRank {
  date: string;
  window: number;
  fetched: number;
  updated_at: string;
  rows: AbnormalRow[];
}

export const getAbnormal = (date: string, window = 10) =>
  http
    .get<AbnormalRank>(`/api/abnormal/${date}?window=${window}`)
    .then((r) => r.data);

/** 强制重拉当日各池(盘中刷新),返回后再拉各面板数据 */
export const refreshDay = (date: string) =>
  http.post<{ date: string; counts: Record<string, number> }>(`/api/refresh/${date}`).then((r) => r.data);

// ---- 持仓 ----
export interface Holding {
  code: string;
  name: string;
  buy_date: string;
  buy_price: number;
  buy_boards: number;
  note: string;
  cur_price: number | null;
  pnl_pct: number | null;
  shares: number; // 持仓股数(截图导入才有,手动录入为 0)
  market_value: number | null; // 现价×股数,无股数为 null
  pnl_amount: number | null; // (现价−成本)×股数,无股数为 null
}
export interface HoldingVerdict {
  code?: string;
  verdict?: string; // 持有/减仓/清仓
  trend_t1?: string;
  trend_swing?: string;
  hold_if?: string;
  add_at?: string;
  take_profit?: string;
  stop_loss?: string;
  priority?: number; // 多票一起分析时的处置优先级,1=最该先动
}
export interface HoldingAnalysis {
  code: string;
  analysis_date: string;
  markdown: string;
  verdict: HoldingVerdict;
  created_at: string;
}
export const getHoldings = () => http.get<Holding[]>("/api/holdings").then((r) => r.data);
export const addHolding = (h: Partial<Holding>) => http.post("/api/holdings", h).then((r) => r.data);
export const deleteHolding = (code: string) => http.delete(`/api/holdings/${code}`).then((r) => r.data);
export const getHoldingAnalysis = (code: string) =>
  http.get<HoldingAnalysis>(`/api/holdings/${code}/analysis`).then((r) => r.data);

/** 持仓截图识别出的一行(尚未入库,供勾选/编辑) */
export interface OcrHoldingRow {
  name: string;
  code: string; // 截图无代码列时由后端按名称反查;仍为空则需用户手填
  code_from: "image" | "name" | ""; // 代码来源:截图直读 / 名称反查 / 缺失
  shares: number;
  cost_price: number | null;
  cur_price: number | null;
  pnl_pct: number | null;
  exists: boolean; // 已在持仓 → 提交会覆盖成本价
  buy_boards: number; // 后端按当日涨停池自动补
  buy_date: string;
}
export interface OcrUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  cost_cny: number;
}
/** 上传持仓截图做识别(不入库)。image_base64 不含 data: 前缀 */
export const ocrHoldings = (image_base64: string, media_type: string, date: string) =>
  http
    .post<{ rows: OcrHoldingRow[]; usage: OcrUsage }>("/api/holdings/ocr", {
      image_base64,
      media_type,
      date,
    })
    .then((r) => r.data);
/** 批量写入持仓(同 code 覆盖) */
export const addHoldingsBulk = (items: Partial<Holding>[]) =>
  http.post<{ added: number }>("/api/holdings/bulk", { items }).then((r) => r.data);

export interface Candidate {
  style: string;
  code: string;
  name: string;
  trigger: string;
  giveup: string;
  reason: string;
  grade: string; // A+/A/B/C/D,后端规则客观打分
  position: string; // 仓位建议
  score: number | null;
  reasons: string[]; // 打分依据
  next_date: string | null; // 次日验证:交易日
  open_prem: number | null; // 隔日开盘溢价(次日开/当日涨停价−1)
  close_prem: number | null;
  pool_rank: number | null; // 在该风格候选池内的名次(1=池内最优,规则排序)
  price_ref: string; // 触发价算式,如 16.87×1.10=18.56
  in_pool: boolean; // false=agent 选了池外的票(违规,结论可复现性打折)
}
export const getCandidates = (date: string) =>
  http.get<Candidate[]>(`/api/candidates/${date}`).then((r) => r.data);

export interface GradeStat {
  n: number;
  win_rate: number;
  avg_open_prem: number;
}
export interface CandidatesStats {
  by_grade: Record<string, GradeStat>;
  overall: GradeStat;
}
export const getCandidatesStats = () =>
  http.get<CandidatesStats>("/api/candidates-stats").then((r) => r.data);

// ---- 候选池完整备选(纯规则、零 token)。「明日候选」只显示 agent 选的 rank1,这里给 rank2-N ----
/** 该票身位最强的成板块题材 + 联动读数;全是单票碎片时为 null(孤票) */
export interface PoolLink {
  theme: string;
  zt_count: number; // 该题材当日涨停家数
  lianban_count: number; // 其中连板数
  max_board: number; // 题材内最高板
  pct: number | null; // 板块涨幅(同花顺 top20 外为 null)
}
export interface PoolItem {
  code: string;
  name: string;
  boards: number;
  grade: string;
  score: number;
  position: string;
  rank: number; // 池内名次,1 为最优
  price: number; // 当日涨停价,供推算次日触发价
  seal_strength: number;
  turnover: number;
  break_times: number;
  first_seal: string;
  last_seal: string;
  theme_rank: number | null;
  w2s: boolean; // 弱转强(昨炸板今涨停)
  reasons: string[];
  link: PoolLink | null;
}
export interface CandidatePool {
  date: string;
  phase: string;
  pool: Record<string, PoolItem[]>; // 风格 → 备选(默认只 A 级以上)
}
export const getCandidatePool = (date: string) =>
  http.get<CandidatePool>(`/api/candidate-pool/${date}`).then((r) => r.data);

// ---- 盘中实时监控(watcher 写库,前端只读轮询)----
export interface LiveEvent {
  ts: string;
  type: string; // leader_break / zhaban_tide / index_plunge
  title: string;
  detail: string;
}
export interface LiveSnapshot {
  ts: string;
  zt_count: number;
  zbgc_count: number;
  lianban_count: number;
  max_board: number;
  break_rate: number; // 0~1
  hot_top5: { code: string; name: string }[];
  index: Record<string, number | null>; // {上证指数: 近15min%, 创业板指: ...}
}
export interface LiveState {
  date: string;
  running: boolean; // watcher 快照 3 分钟内有更新
  updated_at: string | null;
  snapshot: LiveSnapshot | null;
  events: LiveEvent[];
}
export const getLive = () => http.get<LiveState>("/api/live").then((r) => r.data);

// ---- agent 调用成本 ----
export interface UsageCost {
  input_tokens: number;
  output_tokens: number;
  cache_read: number;
  cache_write: number;
  total_tokens: number;
  cost_usd: number;
  cost_cny: number;
}
export interface UsageToday {
  count: number;
  cost_usd: number;
  cost_cny: number;
  total_tokens: number;
}
export const getUsageToday = () => http.get<UsageToday>("/api/usage-today").then((r) => r.data);

/** 流式:生成复盘(persist)或对话追问。onChunk 逐段累加,onEnd 收尾。 */
export function streamSSE(
  path: "/api/generate" | "/api/chat" | "/api/holdings/analyze",
  body: object,
  onChunk: (t: string) => void,
  onEnd: (usage?: UsageCost | null) => void,
  signal: AbortSignal,
) {
  return fetchEventSource(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true,
    onmessage(ev) {
      if (!ev.data) return;
      const data = JSON.parse(ev.data);
      if (data.end) {
        onEnd(data.usage ?? null);
        return;
      }
      if (data.message) onChunk(data.message);
    },
    onerror(err) {
      throw err; // 抛出即中断,不自动重试
    },
  });
}
