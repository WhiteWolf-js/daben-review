import { useEffect, useState } from "react";
import {
  Box,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Link,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import { getAbnormal, type AbnormalRow, type AbnormalTier } from "../api";

// N 日累计涨幅异动榜:窗口内涨停/炸板过的票按累计涨幅排,标翻倍/两倍/进入异动。
// 口径:universe = 最近 N 个交易日涨停池 ∪ 炸板池;mootdx 日线未复权,除权票仅供参考。
const WINDOWS = [5, 10, 20] as const;

const TIER_META: Record<AbnormalTier, { label: string; color: "error" | "warning" | "info" | "default" }> = {
  triple: { label: "🔥 两倍", color: "error" },
  double: { label: "🚀 翻倍", color: "warning" },
  entering: { label: "↑ 进入异动", color: "info" },
  warm: { label: "", color: "default" },
};

const pct = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
const pctColor = (v: number) => (v > 0 ? "error.main" : v < 0 ? "success.main" : "text.primary");

export default function AbnormalPanel({
  date,
  onPick,
}: {
  date: string;
  onPick?: (s: { code: string; name: string; boards: number }) => void;
}) {
  const [window, setWindow] = useState<number>(10);
  const [rows, setRows] = useState<AbnormalRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState("");

  useEffect(() => {
    if (!date) return;
    setRows(null);
    setLoading(true);
    getAbnormal(date, window)
      .then((r) => {
        setRows(r.rows);
        setUpdatedAt(r.updated_at);
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [date, window]);

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1, flexWrap: "wrap", gap: 1 }}>
          <Box>
            <Typography variant="subtitle1" fontWeight={600}>
              异动榜 · {window}日累计涨幅
            </Typography>
            <Typography variant="caption" color="text.secondary">
              涨停/炸板过的票按累计涨幅排,标翻倍/两倍/进入异动 · 日线未除权
            </Typography>
          </Box>
          <ToggleButtonGroup
            size="small"
            value={window}
            exclusive
            onChange={(_, v) => v && setWindow(v)}
          >
            {WINDOWS.map((w) => (
              <ToggleButton key={w} value={w} sx={{ px: 1.25, py: 0.25, fontSize: 12 }}>
                {w}日
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>

        {loading && (
          <Box sx={{ display: "flex", justifyContent: "center", py: 3 }}>
            <CircularProgress size={22} />
          </Box>
        )}

        {rows && rows.length > 0 && (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ py: 0.5 }}>代码/名称</TableCell>
                <TableCell align="right" sx={{ py: 0.5 }}>{window}日累计</TableCell>
                <TableCell align="right" sx={{ py: 0.5 }}>今日</TableCell>
                <TableCell align="center" sx={{ py: 0.5 }}>连板</TableCell>
                <TableCell sx={{ py: 0.5 }}>板块</TableCell>
                <TableCell align="center" sx={{ py: 0.5 }}>标签</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => {
                const tier = TIER_META[r.tier];
                const clickable = !!onPick;
                return (
                  <TableRow
                    key={r.code}
                    hover={clickable}
                    sx={{ cursor: clickable ? "pointer" : "default" }}
                    onClick={() => onPick?.({ code: r.code, name: r.name, boards: r.boards })}
                  >
                    <TableCell sx={{ py: 0.5 }}>
                      <Box sx={{ display: "flex", flexDirection: "column" }}>
                        <Typography variant="body2" component="span" fontWeight={600}>
                          {r.name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {r.code}
                          {r.actual_window < window && ` · 实${r.actual_window}日`}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell align="right" sx={{ py: 0.5, fontWeight: 700, color: pctColor(r.pct_window), whiteSpace: "nowrap" }}>
                      {pct(r.pct_window)}
                    </TableCell>
                    <TableCell align="right" sx={{ py: 0.5, color: pctColor(r.pct_today), whiteSpace: "nowrap" }}>
                      {pct(r.pct_today)}
                    </TableCell>
                    <TableCell align="center" sx={{ py: 0.5 }}>
                      {r.boards >= 1 ? `${r.boards}板` : "—"}
                    </TableCell>
                    <TableCell sx={{ py: 0.5 }}>
                      <Tooltip
                        title={
                          r.themes.length
                            ? `题材: ${r.themes.join(" / ")}`
                            : r.industry || "无"
                        }
                      >
                        <Typography variant="caption" sx={{ cursor: "help" }}>
                          {r.themes[0] || r.industry || "—"}
                        </Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell align="center" sx={{ py: 0.5 }}>
                      {tier.label && (
                        <Chip size="small" color={tier.color} label={tier.label} sx={{ height: 20, fontSize: 11 }} />
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}

        {rows && rows.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
            该日无数据(可能涨停池未入库,或窗口内无涨停记录)。
          </Typography>
        )}

        {updatedAt && (
          <Typography variant="caption" color="text.disabled" sx={{ display: "block", mt: 1 }}>
            生成于 {updatedAt} · 数据来自 mootdx 日线,仅供参考
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}
