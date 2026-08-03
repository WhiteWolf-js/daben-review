import { Box, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import type { Emotion } from "../api";

const pct = (v: number | null) => (typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—");

function Metric({ label, value, hl, big }: { label: string; value: React.ReactNode; hl?: boolean; big?: boolean }) {
  return (
    <Box sx={{ minWidth: big ? 104 : 92 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography
        variant={big ? "h5" : "h6"}
        color={hl ? "primary" : "text.primary"}
        sx={{ lineHeight: 1.3, fontWeight: big ? 700 : undefined }}
      >
        {value}
      </Typography>
    </Box>
  );
}

/**
 * 情绪面板。compact=true 只出 5 个决策级指标(盘后首屏),完整 11 指标版放折叠区。
 * 挑这 5 个的理由:涨停=面、最高板=高度、炸板率=分歧、赚钱效应=能不能赚、1进2=接力成功率。
 */
export default function EmotionPanel({ e, compact = false }: { e: Emotion; compact?: boolean }) {
  const me = e.money_effect;
  const moneyValue = me == null ? "—" : `${me > 0 ? "+" : ""}${me}%`;

  if (compact) {
    return (
      <Card>
        <CardContent>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" color="primary" label={`情绪:${e.phase_hint}`} sx={{ fontWeight: 700 }} />
            <Typography variant="caption" color="text.secondary">
              {e.market_state_hint}
            </Typography>
          </Stack>
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
            <Metric label="涨停" value={e.zt_count} hl big />
            <Metric label="最高板" value={`${e.max_board}板`} hl big />
            <Metric label="炸板率" value={pct(e.break_rate)} big hl={e.break_rate >= 0.4} />
            <Metric label="赚钱效应" value={moneyValue} hl={(me ?? 0) > 0} big />
            <Metric label="1进2" value={pct(e.promo_1to2)} big />
          </Box>
        </CardContent>
      </Card>
    );
  }

  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 2.5 }}>
      <Metric label="涨停" value={e.zt_count} hl />
      <Metric label="连板(≥2)" value={e.lianban_count} />
      <Metric label="最高板" value={`${e.max_board}板`} hl />
      <Metric label="炸板" value={e.zbgc_count} />
      <Metric label="跌停" value={e.dt_count} />
      <Metric label="封板率" value={pct(e.seal_success_rate)} />
      <Metric label="炸板率" value={pct(e.break_rate)} />
      <Metric label="赚钱效应" value={moneyValue} hl />
      <Metric label="1进2" value={pct(e.promo_1to2)} />
      <Metric label="高位晋级" value={pct(e.promo_high)} />
      <Metric label="总晋级" value={pct(e.promo_overall)} />
    </Box>
  );
}
