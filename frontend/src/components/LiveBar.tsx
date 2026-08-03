import { useEffect, useState } from "react";
import {
  Box,
  Card,
  CardContent,
  Chip,
  Collapse,
  IconButton,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { getLive, type LiveState } from "../api";

const POLL_MS = 20_000;

// 事件类型 → MUI 颜色
const EVENT_COLOR: Record<string, "error" | "warning" | "info"> = {
  leader_break: "error",
  zhaban_tide: "warning",
  index_plunge: "info",
};

function Metric({ label, value, hl }: { label: string; value: React.ReactNode; hl?: boolean }) {
  return (
    <Box sx={{ minWidth: 64 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="subtitle1" fontWeight={600} color={hl ? "primary" : "text.primary"} sx={{ lineHeight: 1.2 }}>
        {value}
      </Typography>
    </Box>
  );
}

/** 指数近15min涨跌:A股习惯红涨绿跌 */
function IndexDelta({ name, v }: { name: string; v: number | null }) {
  if (v == null) return null;
  const color = v > 0 ? "error.main" : v < 0 ? "success.main" : "text.secondary";
  return (
    <Box sx={{ minWidth: 78 }}>
      <Typography variant="caption" color="text.secondary">
        {name} 15min
      </Typography>
      <Typography variant="subtitle1" fontWeight={600} sx={{ lineHeight: 1.2, color }}>
        {v > 0 ? "+" : ""}
        {v}%
      </Typography>
    </Box>
  );
}

export default function LiveBar({ defaultEventsOpen = false }: { defaultEventsOpen?: boolean }) {
  const [live, setLive] = useState<LiveState | null>(null);
  const [open, setOpen] = useState(defaultEventsOpen); // 盘中视图默认展开事件流(拐点是最该看的)

  useEffect(() => {
    let alive = true;
    const tick = () => getLive().then((d) => alive && setLive(d)).catch(() => {});
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const running = live?.running ?? false;
  const s = live?.snapshot ?? null;
  const events = live?.events ?? [];
  const pct = (v: number) => `${(v * 100).toFixed(0)}%`;

  return (
    <Card sx={{ mb: 2, opacity: running ? 1 : 0.55 }}>
      <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography variant="subtitle1" fontWeight={700}>
            盘中实时
          </Typography>
          <Chip
            size="small"
            color={running ? "success" : "default"}
            variant={running ? "filled" : "outlined"}
            label={running ? `运行中 · ${s?.ts ?? ""}` : "监控未运行"}
          />

          {running && s ? (
            <>
              <Box sx={{ flexGrow: 1, display: "flex", flexWrap: "wrap", gap: 2 }}>
                <Metric label="涨停" value={s.zt_count} hl />
                <Metric label="炸板" value={s.zbgc_count} />
                <Metric label="炸板率" value={pct(s.break_rate)} hl={s.break_rate >= 0.4} />
                <Metric label="最高板" value={`${s.max_board}板`} hl />
                <Metric label="连板" value={s.lianban_count} />
                {Object.entries(s.index).map(([name, v]) => (
                  <IndexDelta key={name} name={name} v={v} />
                ))}
              </Box>
              <Tooltip title={events.length ? "展开今日事件流" : "今日暂无事件"}>
                <span>
                  <IconButton size="small" onClick={() => setOpen((o) => !o)} disabled={!events.length}>
                    <Stack direction="row" alignItems="center">
                      <Chip size="small" variant="outlined" label={`事件 ${events.length}`} sx={{ mr: 0.5 }} />
                      {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                    </Stack>
                  </IconButton>
                </span>
              </Tooltip>
            </>
          ) : (
            <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1 }}>
              盘中监控未运行 —— 交易时段启动:<code>python -m daban_review.monitor.watcher</code>
            </Typography>
          )}
        </Stack>

        <Collapse in={open && events.length > 0}>
          <Stack spacing={0.75} sx={{ mt: 1.5, pt: 1.5, borderTop: "1px solid rgba(255,255,255,0.08)" }}>
            {events.map((ev, i) => (
              <Stack key={i} direction="row" spacing={1} alignItems="baseline">
                <Typography variant="caption" color="text.secondary" sx={{ minWidth: 40 }}>
                  {ev.ts}
                </Typography>
                <Chip size="small" color={EVENT_COLOR[ev.type] ?? "default"} label={ev.title} sx={{ maxWidth: "100%" }} />
                <Typography variant="caption" color="text.secondary">
                  {ev.detail}
                </Typography>
              </Stack>
            ))}
          </Stack>
        </Collapse>
      </CardContent>
    </Card>
  );
}
