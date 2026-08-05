import { useState } from "react";
import { Box, Chip, Collapse, Link, Stack, Tooltip, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import type { PoolItem } from "../api";

const GRADE_COLOR: Record<string, "success" | "info" | "warning" | "error" | "default"> = {
  "A+": "success", A: "success", B: "info", C: "warning", D: "error",
};

const fmtSeal = (s: string) => {
  const t = (s || "").replace(/\D/g, "");
  return t.length >= 4 ? `${t.slice(0, 2)}:${t.slice(2, 4)}` : "—";
};

/**
 * 某风格的**备选票**(agent 选的 rank1 之外的 A 级以上池内票),默认折叠。
 *
 * 为什么需要:「明日候选」读 candidates 表,那张表只存 agent 写进正文的 rank1 ——
 * 池里 rank2-5 常常也全是 A 级(实测 0804 低位连板接力 5 只都是 A 级以上),被藏起来了。
 *
 * 每行挂**板块联动**(题材 N只/M连/最高K板):这是判断"有没有同题材票托底"的直接依据,
 * 孤票(link 为 null)与有梯队的票赔率完全不同 —— 实测 0803 rank1 豪尔赛 A+/score8
 * 却是孤票,而 rank2 中岩大地 A+/score7 背后是「核电 8只/2连」。
 */
export default function PoolAlternatives({
  items,
  onPick,
}: {
  items: PoolItem[];
  onPick: (s: { code: string; name: string }) => void;
}) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;

  return (
    <Box sx={{ mt: 0.5 }}>
      <Link
        component="button"
        underline="none"
        onClick={() => setOpen((v) => !v)}
        sx={{ fontSize: 12, color: "text.secondary", display: "inline-flex", alignItems: "center" }}
      >
        备选 {items.length} 只
        <ExpandMoreIcon
          sx={{ fontSize: 16, transition: "transform .15s", transform: open ? "rotate(180deg)" : "none" }}
        />
      </Link>

      <Collapse in={open} unmountOnExit>
        <Stack spacing={0.75} sx={{ mt: 0.75, pl: 1, borderLeft: "1px dashed rgba(255,255,255,0.12)" }}>
          {items.map((x) => (
            <Stack key={x.code} direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
              <Tooltip title="池内名次:按可打性 → score → 封流比 → 首封 → 代码 确定性排序">
                <Typography variant="caption" sx={{ color: "text.disabled", minWidth: 22 }}>
                  #{x.rank}
                </Typography>
              </Tooltip>
              <Chip label={x.grade} size="small" color={GRADE_COLOR[x.grade] ?? "default"}
                    sx={{ height: 18, fontSize: 11, fontWeight: 700 }} />
              <Link component="button" underline="hover" onClick={() => onPick({ code: x.code, name: x.name })}
                    sx={{ fontSize: 13, fontWeight: 600 }}>
                {x.name}
              </Link>
              <Typography variant="caption" color="text.secondary">
                {x.boards}板 · 封{(x.seal_strength * 100).toFixed(2)}% · 换{x.turnover.toFixed(1)}% ·{" "}
                {fmtSeal(x.last_seal || x.first_seal)}稳住
                {x.break_times > 0 && ` · 炸${x.break_times}次`}
              </Typography>
              {x.w2s && (
                <Tooltip title="弱转强:前日炸板、今日涨停。回测胜率 74%(同板位对照 58%)">
                  <Chip label="弱转强" size="small" color="success" variant="outlined"
                        sx={{ height: 18, fontSize: 10 }} />
                </Tooltip>
              )}
              {/* 板块联动:有同题材梯队 vs 孤票,赔率完全不同 */}
              {x.link ? (
                <Tooltip title={`${x.link.theme}:当日 ${x.link.zt_count} 只涨停、其中 ${x.link.lianban_count} 只连板、最高 ${x.link.max_board} 板${x.link.pct != null ? `,板块涨幅 ${x.link.pct.toFixed(2)}%` : ""}`}>
                  <Chip
                    size="small"
                    variant="outlined"
                    color={x.link.lianban_count >= 2 ? "warning" : "default"}
                    label={`${x.link.theme} ${x.link.zt_count}只/${x.link.lianban_count}连`}
                    sx={{ height: 18, fontSize: 10 }}
                  />
                </Tooltip>
              ) : (
                <Tooltip title="所属题材当日不足 2 只涨停 → 没有同题材联动票托底">
                  <Chip label="孤票" size="small" variant="outlined"
                        sx={{ height: 18, fontSize: 10, color: "text.disabled" }} />
                </Tooltip>
              )}
            </Stack>
          ))}
        </Stack>
      </Collapse>
    </Box>
  );
}
