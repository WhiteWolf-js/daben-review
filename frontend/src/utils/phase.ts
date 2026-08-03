/** 交易阶段:决定默认展示哪个视图(打开就是当下该看的)。 */
export type TradePhase = "pre" | "intraday" | "post";

export const PHASE_LABEL: Record<TradePhase, string> = {
  pre: "盘前",
  intraday: "盘中",
  post: "盘后",
};

/**
 * 按本地时钟判当前阶段:<9:30 盘前 / 9:30–15:00 盘中 / ≥15:00 盘后;周末一律盘后。
 *
 * 与后端 service._auction_phase 语义对齐但不共用——后端分 4 段(含 9:15–9:20 可撤单),
 * 前端只需 3 段。想强制某个阶段(调试/截图)可加 ?phase=pre|intraday|post。
 */
export function getTradePhase(now: Date = new Date()): TradePhase {
  const forced = new URLSearchParams(window.location.search).get("phase");
  if (forced === "pre" || forced === "intraday" || forced === "post") return forced;

  const day = now.getDay();
  if (day === 0 || day === 6) return "post"; // 周末:看最近一次复盘

  const mins = now.getHours() * 60 + now.getMinutes();
  if (mins < 9 * 60 + 30) return "pre";
  if (mins < 15 * 60) return "intraday";
  return "post";
}
