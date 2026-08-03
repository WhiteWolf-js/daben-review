import { useEffect, useState } from "react";
import { Box, Card, CardContent, Chip, Link, Stack, Tooltip, Typography } from "@mui/material";
import { getCandidates, getCandidatesStats, type Candidate, type CandidatesStats } from "../api";

const pct1 = (v: number) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

// 四风格配色(与情绪面板同一套语义:进攻暖色、防守冷色)
const STYLE_COLOR: Record<string, "success" | "warning" | "error" | "info" | "default"> = {
  低位连板接力: "success",
  首板打板: "info",
  题材情绪龙头: "warning",
  高位龙头接力: "error",
};

// 评级配色:A+/A 强(绿)、B 中性(蓝)、C 弱(橙)、D 回避(红)
const GRADE_COLOR: Record<string, "success" | "info" | "warning" | "error" | "default"> = {
  "A+": "success",
  A: "success",
  B: "info",
  C: "warning",
  D: "error",
};

export default function CandidatePanel({
  date,
  reload,
  onPick,
  title = "明日候选票 · 结构化",
  subtitle,
  emptyHint,
}: {
  date: string;
  reload: number;
  onPick: (s: { code: string; name: string }) => void;
  /** 盘前叫「今日作战清单」、盘后叫「明日候选票」——同一份数据,两个阶段的不同角色 */
  title?: string;
  subtitle?: string;
  /** 无候选时的说明文案;不传则整块不渲染(保持旧行为) */
  emptyHint?: string;
}) {
  const [rows, setRows] = useState<Candidate[]>([]);
  const [stats, setStats] = useState<CandidatesStats | null>(null);

  useEffect(() => {
    if (!date) {
      setRows([]);
      return;
    }
    getCandidates(date)
      .then(setRows)
      .catch(() => setRows([]));
  }, [date, reload]);

  useEffect(() => {
    getCandidatesStats().then(setStats).catch(() => setStats(null));
  }, [date, reload]);

  const ov = stats?.overall;

  if (rows.length === 0) {
    if (!emptyHint) return null;
    return (
      <Card>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
            {title}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {emptyHint}
          </Typography>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent>
        <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mb: 1.5 }}>
          <Stack direction="row" alignItems="baseline" spacing={1} flexWrap="wrap" useFlexGap>
            <Typography variant="subtitle1" fontWeight={600}>
              {title}
            </Typography>
            {subtitle && (
              <Typography variant="caption" color="text.secondary">
                {subtitle}
              </Typography>
            )}
          </Stack>
          {ov && ov.n > 0 && (
            <Tooltip title={`按评级:${Object.entries(stats!.by_grade).map(([g, s]) => `${g} ${(s.win_rate * 100).toFixed(0)}%(${s.n})`).join("  ")}`}>
              <Typography variant="caption" color="text.secondary" sx={{ cursor: "help" }}>
                滚动命中率 {(ov.win_rate * 100).toFixed(0)}% · 均溢价 {pct1(ov.avg_open_prem)} · n={ov.n}
              </Typography>
            </Tooltip>
          )}
        </Stack>
        <Stack spacing={1.5}>
          {rows.map((c, i) => (
            <Box
              key={`${c.code}-${i}`}
              sx={{ borderLeft: "3px solid", borderColor: `${STYLE_COLOR[c.style] ?? "default"}.main`, pl: 1.5 }}
            >
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }} flexWrap="wrap" useFlexGap>
                {c.grade && (
                  <Chip
                    label={c.position ? `${c.grade} · ${c.position}` : c.grade}
                    size="small"
                    color={GRADE_COLOR[c.grade] ?? "default"}
                    sx={{ fontWeight: 700 }}
                  />
                )}
                <Chip label={c.style || "候选"} size="small" color={STYLE_COLOR[c.style] ?? "default"} variant="outlined" />
                <Link
                  component="button"
                  underline="hover"
                  onClick={() => onPick({ code: c.code, name: c.name })}
                  sx={{ fontWeight: 600, fontSize: 14 }}
                >
                  {c.name}
                </Link>
                <Typography variant="caption" color="text.secondary">
                  {c.code}
                </Typography>
                {c.pool_rank != null && (
                  <Tooltip title="候选池内名次:池由封流比/首封/炸板/换手/身位等规则排序,rank1 为池内最优">
                    <Chip
                      label={`池 #${c.pool_rank}`}
                      size="small"
                      variant="outlined"
                      color={c.pool_rank === 1 ? "info" : "default"}
                      sx={{ height: 20, fontSize: 11 }}
                    />
                  </Tooltip>
                )}
                {!c.in_pool && (
                  <Tooltip title="该票不在规则候选池内(agent 越池选票),复现性与可回测性打折">
                    <Chip label="池外" size="small" color="warning" sx={{ height: 20, fontSize: 11 }} />
                  </Tooltip>
                )}
                {c.open_prem != null && (
                  <Chip
                    label={`次日 ${pct1(c.open_prem)}`}
                    size="small"
                    variant="outlined"
                    color={c.open_prem > 0 ? "error" : "success"}
                    sx={{ height: 20, fontSize: 11 }}
                  />
                )}
              </Stack>
              {c.reason && (
                <Typography variant="body2" sx={{ mb: 0.5 }}>
                  {c.reason}
                </Typography>
              )}
              {c.trigger && (
                <Typography variant="caption" sx={{ display: "block", color: "success.main" }}>
                  进:{c.trigger}
                </Typography>
              )}
              {c.giveup && (
                <Typography variant="caption" sx={{ display: "block", color: "error.main" }}>
                  弃:{c.giveup}
                </Typography>
              )}
              {c.reasons && c.reasons.length > 0 && (
                <Typography variant="caption" sx={{ display: "block", color: "text.disabled", mt: 0.25 }}>
                  评级依据:{c.reasons.join(" · ")}
                </Typography>
              )}
            </Box>
          ))}
        </Stack>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: "block" }}>
          由 agent 复盘结构化提取,仅供参考;进/弃为条件判断,非确定性结论。
        </Typography>
      </CardContent>
    </Card>
  );
}
