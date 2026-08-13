import { Box, Chip, Stack, Tooltip, Typography } from "@mui/material";
import type { Holding, HoldingVerdict } from "../api";

export type BoardRow = { h: Holding; v: HoldingVerdict };

/**
 * 动作配色:清仓最响、减仓次之、持有压到最暗 —— 扫一眼先看到「要动的」。
 * agent 的 verdict 是自由文本,认不出来的一律当持有(不夸大动作)。
 */
const ACTION: Record<string, { fg: string; bg: string }> = {
  清仓: { fg: "#e5484d", bg: "rgba(229,72,77,0.14)" },
  减仓: { fg: "#f5a623", bg: "rgba(245,166,35,0.12)" },
  持有: { fg: "#30a46c", bg: "rgba(48,164,108,0.10)" },
};
const ACT_ORDER = ["清仓", "减仓", "持有"];

export const actOf = (v?: HoldingVerdict) => {
  const a = v?.verdict ?? "";
  return ACT_ORDER.includes(a) ? a : "持有";
};

/** 要动的排前面(清仓→减仓→持有),组内按 agent 给的处置优先级(1=最该先动) */
export const sortRows = (rows: BoardRow[]): BoardRow[] =>
  [...rows].sort((a, b) => {
    const d = ACT_ORDER.indexOf(actOf(a.v)) - ACT_ORDER.indexOf(actOf(b.v));
    return d !== 0 ? d : (a.v.priority ?? 99) - (b.v.priority ?? 99);
  });

const pnlColor = (p: number | null | undefined) =>
  p == null ? "#8b949e" : p >= 0 ? "#e5484d" : "#30a46c";
const fmtPnl = (p: number | null | undefined) =>
  p == null ? "—" : `${p > 0 ? "+" : ""}${p}%`;

/**
 * 明日处置速览 —— **海报与网页面板共用同一份排版**(别写两套)。
 *
 * 设计意图:原来每只票平铺 T+1/波段/止盈/止损 四行散文,4 只票就是 16 行,开盘前根本来不及读。
 * 这里做信息分层:
 * - **要动的(清仓/减仓)出完整行**,只留「动作 + 盈亏 + 触发价」,散文进 tooltip;
 * - **持有的折成一行摘要** —— 不用动的票不该占版面。
 * 触发价是自由文本(agent 写「跌破16.20或早盘不能回封」这种),截断成一行、全文进 tooltip。
 */
export default function HoldingBoard({
  rows,
  scale = 1,
  onPick,
}: {
  rows: BoardRow[];
  scale?: number; // 1=海报尺寸,<1=网页内紧凑
  onPick?: (code: string) => void;
}) {
  const px = (n: number) => Math.round(n * scale);
  const sorted = sortRows(rows);
  const act = sorted.filter((r) => actOf(r.v) !== "持有"); // 要动的
  const hold = sorted.filter((r) => actOf(r.v) === "持有");
  const counts = ACT_ORDER.map((a) => [a, sorted.filter((r) => actOf(r.v) === a).length] as const)
    .filter(([, n]) => n > 0);

  if (sorted.length === 0) return null;

  const COLS = "auto 1fr auto minmax(0,1.4fr) minmax(0,1.4fr)";

  const tip = (r: BoardRow) =>
    [
      `${r.h.code}${r.h.buy_boards ? ` · 买入 ${r.h.buy_boards} 板` : ""}`,
      r.h.buy_price ? `成本 ${r.h.buy_price}${r.h.cur_price != null ? ` → 现价 ${r.h.cur_price}` : ""}` : "",
      r.v.trend_t1 ? `T+1:${r.v.trend_t1}` : "",
      r.v.trend_swing ? `波段:${r.v.trend_swing}` : "",
      r.v.hold_if ? `持有条件:${r.v.hold_if}` : "",
      r.v.take_profit ? `止盈:${r.v.take_profit}` : "",
      r.v.stop_loss ? `止损:${r.v.stop_loss}` : "",
      onPick ? "点击看分时" : "",
    ]
      .filter(Boolean)
      .join("\n");

  const clamp = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } as const;
  // 触发价给两行:它是这张图的正主,海报又没有 tooltip 兜底,截成一行会把价位后半段永久丢掉
  const clamp2 = {
    display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2,
    overflow: "hidden", lineHeight: 1.35,
  } as const;

  return (
    <Box sx={{ border: "1px solid #21262d", borderRadius: 1, overflow: "hidden" }}>
      {/* 汇总:开盘前第一眼只需要知道「几只要动」 */}
      <Stack
        direction="row"
        alignItems="baseline"
        spacing={1}
        sx={{ bgcolor: "#161b22", px: 1.25, py: 0.75, borderBottom: "1px solid #21262d" }}
        flexWrap="wrap"
        useFlexGap
      >
        <Typography sx={{ fontSize: px(15), fontWeight: 800 }}>明日处置</Typography>
        <Typography sx={{ fontSize: px(13), fontWeight: 700, color: act.length ? "#e5484d" : "#30a46c" }}>
          {act.length ? `要动 ${act.length} 只` : "无需调整"}
        </Typography>
        <Typography sx={{ fontSize: px(12), color: "#8b949e" }}>
          {counts.map(([a, n]) => `${a} ${n}`).join(" · ")}
        </Typography>
      </Stack>

      {act.length > 0 && (
        <>
          <Box
            sx={{
              display: "grid", gridTemplateColumns: COLS, gap: px(8) / 8,
              px: 1.25, py: 0.5, fontSize: px(11), color: "#6e7681",
              borderBottom: "1px solid #21262d",
            }}
          >
            <Box>序</Box>
            <Box>标的</Box>
            <Box sx={{ textAlign: "right" }}>盈亏</Box>
            <Box>止盈 / 减仓点</Box>
            <Box>止损 / 离场点</Box>
          </Box>

          {act.map((r) => {
            const a = actOf(r.v);
            const c = ACTION[a];
            return (
              <Tooltip key={r.h.code} title={<Box sx={{ whiteSpace: "pre-line" }}>{tip(r)}</Box>}>
                <Box
                  onClick={onPick ? () => onPick(r.h.code) : undefined}
                  sx={{
                    display: "grid", gridTemplateColumns: COLS, gap: px(8) / 8, alignItems: "center",
                    px: 1.25, py: px(7) / 8, bgcolor: c.bg,
                    borderBottom: "1px solid #21262d", borderLeft: `${px(3)}px solid ${c.fg}`,
                    cursor: onPick ? "pointer" : "default",
                    "&:hover": onPick ? { filter: "brightness(1.25)" } : undefined,
                  }}
                >
                  <Stack direction="row" alignItems="center" spacing={0.5}>
                    {r.v.priority != null && (
                      <Typography sx={{ fontSize: px(12), fontWeight: 800, color: "#8b949e" }}>
                        #{r.v.priority}
                      </Typography>
                    )}
                    <Chip
                      label={a}
                      size="small"
                      sx={{
                        height: px(19), fontSize: px(11), fontWeight: 800,
                        bgcolor: c.fg, color: "#fff", "& .MuiChip-label": { px: 0.75 },
                      }}
                    />
                  </Stack>

                  <Box sx={{ minWidth: 0 }}>
                    <Typography sx={{ fontSize: px(15), fontWeight: 700, ...clamp }}>
                      {r.h.name || r.h.code}
                      {r.h.buy_boards ? (
                        <Box component="span" sx={{ fontSize: px(11), color: "#8b949e", ml: 0.5 }}>
                          {r.h.buy_boards}板
                        </Box>
                      ) : null}
                    </Typography>
                  </Box>

                  <Box sx={{ textAlign: "right" }}>
                    <Typography sx={{ fontSize: px(14), fontWeight: 700, color: pnlColor(r.h.pnl_pct) }}>
                      {fmtPnl(r.h.pnl_pct)}
                    </Typography>
                    {/* 金额只有截图导入(带股数)的票才有;取整 —— 盈亏到毛没意义 */}
                    {r.h.pnl_amount != null && (
                      <Typography sx={{ fontSize: px(10), color: pnlColor(r.h.pnl_pct) }}>
                        {r.h.pnl_amount > 0 ? "+" : ""}
                        {Math.round(r.h.pnl_amount).toLocaleString()}
                      </Typography>
                    )}
                  </Box>

                  <Typography sx={{ fontSize: px(12), color: "#e5484d", ...clamp2 }}>
                    {r.v.take_profit || "—"}
                  </Typography>
                  <Typography sx={{ fontSize: px(12), color: "#30a46c", ...clamp2 }}>
                    {r.v.stop_loss || "—"}
                  </Typography>
                </Box>
              </Tooltip>
            );
          })}
        </>
      )}

      {/* 持有的不用动 → 折成一行,别占版面 */}
      {hold.length > 0 && (
        <Stack
          direction="row"
          alignItems="center"
          spacing={1}
          sx={{ px: 1.25, py: 0.75, flexWrap: "wrap" }}
          useFlexGap
        >
          <Chip
            label={`持有 ${hold.length}`}
            size="small"
            sx={{
              height: px(19), fontSize: px(11), fontWeight: 800,
              bgcolor: ACTION.持有.fg, color: "#fff", "& .MuiChip-label": { px: 0.75 },
            }}
          />
          {hold.map((r) => (
            <Tooltip key={r.h.code} title={<Box sx={{ whiteSpace: "pre-line" }}>{tip(r)}</Box>}>
              <Typography
                onClick={onPick ? () => onPick(r.h.code) : undefined}
                sx={{ fontSize: px(13), cursor: onPick ? "pointer" : "default" }}
              >
                {r.h.name || r.h.code}
                <Box component="span" sx={{ color: pnlColor(r.h.pnl_pct), fontWeight: 700, ml: 0.5 }}>
                  {fmtPnl(r.h.pnl_pct)}
                </Box>
              </Typography>
            </Tooltip>
          ))}
        </Stack>
      )}
    </Box>
  );
}
