import { Fragment, useEffect, useState } from "react";
import {
  Box,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Collapse,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { getThemeHeat, type ThemeRow } from "../api";

// 题材热度榜:同花顺涨停原因聚合,反映当日炒作主线(比行业更细,一票多题材)
export default function ThemePanel({
  date,
  reload = 0,
  onPick,
}: {
  date: string;
  reload?: number;
  onPick?: (s: { code: string; name: string; boards: number }) => void;
}) {
  const [rows, setRows] = useState<ThemeRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!date) return;
    setRows(null);
    setExpanded(new Set());
    setLoading(true);
    getThemeHeat(date)
      .then((rs) => {
        setRows(rs);
        setExpanded(new Set(rs.map((r) => r.theme))); // 默认全部展开
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [date, reload]);

  const toggle = (t: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      n.has(t) ? n.delete(t) : n.add(t);
      return n;
    });

  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
          题材热度 · 当日主线
        </Typography>
        {loading && (
          <Box sx={{ display: "flex", justifyContent: "center", py: 3 }}>
            <CircularProgress size={22} />
          </Box>
        )}
        {rows && rows.length > 0 && (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ py: 0.5 }}>题材</TableCell>
                <TableCell align="center" sx={{ py: 0.5 }}>涨停</TableCell>
                <TableCell align="center" sx={{ py: 0.5 }}>连板</TableCell>
                <TableCell align="center" sx={{ py: 0.5 }}>最高</TableCell>
                <TableCell align="right" sx={{ py: 0.5 }}>板块强度</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.slice(0, 12).map((r) => {
                const open = expanded.has(r.theme);
                return (
                  <Fragment key={r.theme}>
                    <TableRow hover sx={{ cursor: "pointer", "& td": { borderBottom: open ? 0 : undefined } }} onClick={() => toggle(r.theme)}>
                      <TableCell sx={{ py: 0.5 }}>
                        <Box sx={{ display: "flex", alignItems: "center", gap: 0.25 }}>
                          {open ? <ExpandLessIcon sx={{ fontSize: 16 }} /> : <ExpandMoreIcon sx={{ fontSize: 16 }} />}
                          {r.theme}
                        </Box>
                      </TableCell>
                      <TableCell align="center" sx={{ py: 0.5, color: "primary.main", fontWeight: 600 }}>
                        {r.zt_count}
                      </TableCell>
                      <TableCell align="center" sx={{ py: 0.5 }}>{r.lianban_count || "—"}</TableCell>
                      <TableCell align="center" sx={{ py: 0.5 }}>{r.max_board}板</TableCell>
                      <TableCell align="right" sx={{ py: 0.5, whiteSpace: "nowrap" }}>
                        {r.pct == null ? (
                          <Typography variant="caption" color="text.disabled">—</Typography>
                        ) : (
                          <Tooltip
                            title={
                              `同花顺板块涨幅 ${r.pct.toFixed(2)}%` +
                              (r.board_zt != null ? ` · 板块涨停 ${r.board_zt}` : "") +
                              (r.board_high ? ` · 最高 ${r.board_high}` : "")
                            }
                          >
                            <Box sx={{ cursor: "help" }}>
                              <Typography
                                component="span"
                                sx={{ fontSize: 13, fontWeight: 700, color: r.pct >= 0 ? "primary.main" : "success.main" }}
                              >
                                {r.pct >= 0 ? "+" : ""}{r.pct.toFixed(2)}%
                              </Typography>
                              {r.board_high && (
                                <Typography component="span" sx={{ fontSize: 11, color: "text.secondary", ml: 0.5 }}>
                                  {r.board_high}
                                </Typography>
                              )}
                            </Box>
                          </Tooltip>
                        )}
                      </TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell colSpan={5} sx={{ py: 0, border: open ? undefined : 0 }}>
                        <Collapse in={open} timeout="auto" unmountOnExit>
                          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, py: 1 }}>
                            {r.stocks.map((st) => (
                              <Chip
                                key={st.code || st.name}
                                size="small"
                                variant="outlined"
                                clickable={!!onPick}
                                onClick={onPick ? (e) => { e.stopPropagation(); onPick(st); } : undefined}
                                color={st.boards >= 2 ? "primary" : "default"}
                                label={`${st.name}${st.boards >= 2 ? ` ${st.boards}板` : ""}`}
                              />
                            ))}
                          </Box>
                        </Collapse>
                      </TableCell>
                    </TableRow>
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
        {rows && rows.length === 0 && !loading && (
          <Typography variant="body2" color="text.secondary">
            暂无题材数据
          </Typography>
        )}
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
          题材=同花顺涨停原因,一票可属多题材(多属性);≥2 只涨停才计入。默认展开,点题材行可收起;**点个股看分时**。
          板块强度=同花顺涨停板块榜的板块涨幅(悬浮看板块涨停数与最高身位);同花顺只出当日 top20 板块,冷门题材显示「—」。
        </Typography>
      </CardContent>
    </Card>
  );
}
