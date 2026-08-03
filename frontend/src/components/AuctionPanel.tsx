import { Fragment, useCallback, useEffect, useState } from "react";
import {
  Box,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Collapse,
  Stack,
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
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import StarIcon from "@mui/icons-material/Star";
import { getAuctionLive, type AuctionLive, type AuctionPhase, type GapTrend } from "../api";

const POLL_MS = 6000; // 9:20 后每 6s;其余时段只拉一次

const PHASE_TEXT: Record<AuctionPhase, string> = {
  pre_cancel: "9:15–9:20 可撤单 · 仅参考",
  bidding: "竞价中 · 不可撤单",
  opened: "已定格",
  // 竞价已过(盘中/盘后来看):显示的是今日开盘的高开结果,不是历史数据 —— 写清楚免得以为面板没刷新
  closed: "今日已开盘 · 下列为今日开盘高开",
};
const PHASE_COLOR: Record<AuctionPhase, "default" | "warning" | "error" | "success"> = {
  pre_cancel: "warning",
  bidding: "error",
  opened: "success",
  closed: "default",
};
// A+/A 高亮(绿),C/D 弱(灰)
const GRADE_COLOR: Record<string, "success" | "primary" | "default"> = {
  "A+": "success",
  A: "success",
  B: "primary",
};

/** 高开幅度配色:最佳接力区 3–5% 绿,>7% 溢价过高橙,<2% 弱灰 */
const gapColor = (g: number) =>
  g >= 3 && g <= 5 ? "success.main" : g > 7 ? "warning.main" : g < 2 ? "text.secondary" : "error.main";

function Trend({ t }: { t: GapTrend }) {
  if (t === "up")
    return (
      <Tooltip title="9:20 起抬升:抢筹在加">
        <ArrowUpwardIcon sx={{ fontSize: 14, color: "error.main", verticalAlign: "middle" }} />
      </Tooltip>
    );
  if (t === "down")
    return (
      <Tooltip title="9:20 起回落:有人砸,防高开低走">
        <ArrowDownwardIcon sx={{ fontSize: 14, color: "success.main", verticalAlign: "middle" }} />
      </Tooltip>
    );
  return null;
}

export default function AuctionPanel({
  onPick,
}: {
  onPick?: (s: { code: string; name: string; boards: number }) => void;
}) {
  const [data, setData] = useState<AuctionLive | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [stocksOpen, setStocksOpen] = useState(false); // 个股榜默认收起,首屏先定方向

  const load = useCallback(
    (first: boolean) => {
      if (first) setLoading(true);
      getAuctionLive()
        .then((d) => {
          setData(d);
          if (first) setExpanded(new Set(d.themes.slice(0, 3).map((t) => t.theme))); // 默认展开前3强方向
        })
        .catch(() => setData(null))
        .finally(() => first && setLoading(false));
    },
    [],
  );

  useEffect(() => {
    load(true);
  }, [load]);

  // 竞价时段(9:20–9:30)才轮询,其余时段静态
  const live = data?.phase === "bidding" || data?.phase === "opened";
  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => load(false), POLL_MS);
    return () => clearInterval(id);
  }, [live, load]);

  const toggle = (t: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      n.has(t) ? n.delete(t) : n.add(t);
      return n;
    });

  const phase = data?.phase ?? "closed";
  const dim = phase === "pre_cancel"; // 可撤单时段整体淡显

  return (
    <Card sx={{ opacity: dim ? 0.72 : 1 }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
          <Typography variant="subtitle1" fontWeight={600}>
            盘前竞价 · 抢筹决策
          </Typography>
          <Chip size="small" color={PHASE_COLOR[phase]} label={`${PHASE_TEXT[phase]}${data?.ts ? ` ${data.ts}` : ""}`} />
          {data?.base_date && (
            // 两个日期分开说:选票池是「昨日」涨停票,报价是「今日」实时 —— 只写「基于 20260728」
            // 会被读成整个面板的数据都是那天的(实际 gap/成交额都是当日实时值)
            <Tooltip title="面板选票范围 = 上一交易日的连板与首板强票;高开幅度、成交额取今日实时行情">
              <Typography variant="caption" color="text.secondary">
                选票池 {data.base_date}(上一交易日) · 报价今日实时 · 情绪{data.emotion_phase}
              </Typography>
            </Tooltip>
          )}
          {loading && <CircularProgress size={16} />}
        </Stack>

        {data?.note && (
          <Typography variant="body2" color="text.secondary">
            {data.note}
          </Typography>
        )}

        {/* 上:题材聚合(定方向)——一群票齐高开才是方向,单票高开是个股行为 */}
        {data && data.themes.length > 0 && (
          <>
            <Typography variant="caption" color="primary" fontWeight={600} sx={{ display: "block", mb: 0.5 }}>
              方向(题材竞价强弱)
            </Typography>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ py: 0.5 }}>题材</TableCell>
                  <TableCell align="center" sx={{ py: 0.5 }}>只数</TableCell>
                  <TableCell align="right" sx={{ py: 0.5 }}>均高开</TableCell>
                  <TableCell align="center" sx={{ py: 0.5 }}>最高板</TableCell>
                  <TableCell align="right" sx={{ py: 0.5 }}>竞价额</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.themes.map((t) => {
                  const open = expanded.has(t.theme);
                  return (
                    <Fragment key={t.theme}>
                      <TableRow hover sx={{ cursor: "pointer" }} onClick={() => toggle(t.theme)}>
                        <TableCell sx={{ py: 0.5 }}>
                          <Box sx={{ display: "flex", alignItems: "center", gap: 0.25 }}>
                            {open ? <ExpandLessIcon sx={{ fontSize: 16 }} /> : <ExpandMoreIcon sx={{ fontSize: 16 }} />}
                            {t.theme}
                          </Box>
                        </TableCell>
                        <TableCell align="center" sx={{ py: 0.5 }}>{t.members}</TableCell>
                        <TableCell align="right" sx={{ py: 0.5, fontWeight: 600, color: gapColor(t.avg_gap) }}>
                          {t.avg_gap > 0 ? "+" : ""}
                          {t.avg_gap}%
                        </TableCell>
                        <TableCell align="center" sx={{ py: 0.5 }}>{t.max_board}板</TableCell>
                        <TableCell align="right" sx={{ py: 0.5 }}>{t.amount_yi}亿</TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell colSpan={5} sx={{ py: 0, border: open ? undefined : 0 }}>
                          <Collapse in={open} timeout="auto" unmountOnExit>
                            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, py: 1 }}>
                              {t.stocks.map((s) => (
                                <Chip
                                  key={s.code}
                                  size="small"
                                  variant="outlined"
                                  clickable={!!onPick}
                                  onClick={
                                    onPick
                                      ? (e) => {
                                          e.stopPropagation();
                                          onPick({ code: s.code, name: s.name, boards: s.prev_boards });
                                        }
                                      : undefined
                                  }
                                  color={GRADE_COLOR[s.grade] ?? "default"}
                                  icon={s.in_candidates ? <StarIcon sx={{ fontSize: 13 }} /> : undefined}
                                  label={`${s.name} ${s.gap_pct > 0 ? "+" : ""}${s.gap_pct}%`}
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
          </>
        )}

        {/* 下:个股竞价榜(选标的)。默认折叠——首屏先定方向,要挑标的才展开 */}
        {data && data.rows.length > 0 && (
          <>
            <Stack
              direction="row"
              alignItems="center"
              spacing={0.5}
              onClick={() => setStocksOpen((o) => !o)}
              sx={{ cursor: "pointer", userSelect: "none", mt: 1.5, mb: 0.5 }}
            >
              {stocksOpen ? <ExpandLessIcon sx={{ fontSize: 16 }} /> : <ExpandMoreIcon sx={{ fontSize: 16 }} />}
              <Typography variant="caption" color="primary" fontWeight={600}>
                个股竞价榜 {data.rows.length} 只(点行看分时)
              </Typography>
            </Stack>
            <Collapse in={stocksOpen} timeout="auto">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ py: 0.5 }}>名称</TableCell>
                  <TableCell align="center" sx={{ py: 0.5 }}>昨板</TableCell>
                  <TableCell align="right" sx={{ py: 0.5 }}>高开</TableCell>
                  <TableCell align="right" sx={{ py: 0.5 }}>竞价额</TableCell>
                  <TableCell align="right" sx={{ py: 0.5 }}>封流比</TableCell>
                  <TableCell align="center" sx={{ py: 0.5 }}>买/卖</TableCell>
                  <TableCell align="center" sx={{ py: 0.5 }}>评级</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.rows.slice(0, 25).map((r) => (
                  <Tooltip
                    key={r.code}
                    placement="left"
                    title={
                      <Box sx={{ fontSize: 11 }}>
                        {r.theme.join(" · ") || "无题材标签"}
                        {r.notes.map((n, i) => (
                          <Box key={i}>· {n}</Box>
                        ))}
                      </Box>
                    }
                  >
                    <TableRow
                      hover
                      sx={{ cursor: onPick ? "pointer" : "default" }}
                      onClick={() => onPick?.({ code: r.code, name: r.name, boards: r.prev_boards })}
                    >
                      <TableCell sx={{ py: 0.5 }}>
                        {r.in_candidates && <StarIcon sx={{ fontSize: 12, color: "warning.main", mr: 0.25 }} />}
                        {r.name}
                      </TableCell>
                      <TableCell align="center" sx={{ py: 0.5 }}>{r.prev_boards}</TableCell>
                      <TableCell align="right" sx={{ py: 0.5, fontWeight: 600, color: gapColor(r.gap_pct) }}>
                        {r.gap_pct > 0 ? "+" : ""}
                        {r.gap_pct}% <Trend t={r.gap_trend} />
                      </TableCell>
                      <TableCell align="right" sx={{ py: 0.5, color: r.amount_yi < 0.5 ? "text.secondary" : undefined }}>
                        {r.amount_yi}
                      </TableCell>
                      <TableCell align="right" sx={{ py: 0.5 }}>{(r.seal_strength * 100).toFixed(2)}%</TableCell>
                      <TableCell align="center" sx={{ py: 0.5 }}>{r.bid_ask_ratio ?? "—"}</TableCell>
                      <TableCell align="center" sx={{ py: 0.5 }}>
                        <Chip size="small" label={r.grade} color={GRADE_COLOR[r.grade] ?? "default"} sx={{ height: 18, fontSize: 11 }} />
                      </TableCell>
                    </TableRow>
                  </Tooltip>
                ))}
              </TableBody>
            </Table>
            </Collapse>
          </>
        )}

        {data && data.rows.length === 0 && !data.note && !loading && (
          <Typography variant="body2" color="text.secondary">
            暂无竞价数据(9:20 前撮合价未定,或行情源未返回)
          </Typography>
        )}

        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
          池=上一交易日连板全取+首板封流比前15。高开 3–5% 最佳接力区、&gt;7% 溢价过高、竞价额&lt;0.5亿为"无量假强";
          箭头=9:20 起的变化方向(↑抢筹在加 / ↓有人砸);★=昨晚复盘候选。9:15–9:20 可撤单,数据仅参考。
        </Typography>
      </CardContent>
    </Card>
  );
}
