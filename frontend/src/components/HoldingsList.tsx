import { useCallback, useEffect, useState } from "react";
import {
  Box,
  Card,
  CardContent,
  Chip,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import ShowChartIcon from "@mui/icons-material/ShowChart";
import {
  deleteHolding,
  getHoldingAnalysis,
  getHoldings,
  type Holding,
  type HoldingVerdict,
} from "../api";

const POLL_MS = 30_000; // 盘中每 30s 刷新价与盈亏

const VERDICT_COLOR: Record<string, "success" | "warning" | "error" | "default"> = {
  持有: "success",
  减仓: "warning",
  清仓: "error",
};

/**
 * 持仓实时(盘中首屏):盈亏 + 已存 agent 结论的止盈/止损价位提醒。
 *
 * **盘中不跑 agent**(一次 1-2 分钟不现实),只读盘后已生成的 verdict;
 * 要重新诊断去盘后视图的「持仓 agent 诊断」。
 */
export default function HoldingsList({
  onPick,
  reload = 0,
}: {
  onPick?: (s: { code: string; name: string; boards: number }) => void;
  reload?: number;
}) {
  const [rows, setRows] = useState<Holding[]>([]);
  const [verdicts, setVerdicts] = useState<Record<string, HoldingVerdict>>({});

  const load = useCallback(() => {
    getHoldings()
      .then((hs) => {
        setRows(hs);
        // 把每只已存的 agent 结论拉来,盘中直接看止盈/止损价位
        hs.forEach((h) =>
          getHoldingAnalysis(h.code)
            .then((a) => a?.verdict && setVerdicts((v) => ({ ...v, [h.code]: a.verdict })))
            .catch(() => {}),
        );
      })
      .catch(() => setRows([]));
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load, reload]);

  const remove = (code: string) => deleteHolding(code).then(load);

  if (rows.length === 0) {
    return (
      <Card>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
            持仓实时
          </Typography>
          <Typography variant="body2" color="text.secondary">
            还没有持仓。在下方「添加持仓」录入你打板买入的票,这里会盯盈亏与止盈/止损价位。
          </Typography>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent>
        <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="subtitle1" fontWeight={600}>
            持仓实时
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {rows.length} 只 · 每 30s 刷新 · 买卖点来自盘后 agent 诊断
          </Typography>
        </Stack>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ py: 0.5 }}>名称</TableCell>
              <TableCell align="center" sx={{ py: 0.5 }}>买入板</TableCell>
              <TableCell align="right" sx={{ py: 0.5 }}>成本</TableCell>
              <TableCell align="right" sx={{ py: 0.5 }}>现价</TableCell>
              <TableCell align="right" sx={{ py: 0.5 }}>盈亏</TableCell>
              <TableCell sx={{ py: 0.5 }}>止盈 / 止损</TableCell>
              <TableCell align="center" sx={{ py: 0.5 }} />
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((h) => {
              const v = verdicts[h.code];
              return (
                <TableRow key={h.code} hover>
                  <TableCell sx={{ py: 0.5 }}>
                    <Stack direction="row" alignItems="center" spacing={0.5}>
                      <Box
                        component="span"
                        sx={{ cursor: onPick ? "pointer" : "default", fontWeight: 600 }}
                        onClick={() => onPick?.({ code: h.code, name: h.name || h.code, boards: h.buy_boards })}
                      >
                        {h.name || h.code}
                      </Box>
                      {v?.verdict && (
                        <Chip
                          label={v.verdict}
                          size="small"
                          color={VERDICT_COLOR[v.verdict] ?? "default"}
                          sx={{ height: 18, fontSize: 11 }}
                        />
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell align="center" sx={{ py: 0.5 }}>{h.buy_boards || "—"}</TableCell>
                  <TableCell align="right" sx={{ py: 0.5 }}>{h.buy_price}</TableCell>
                  <TableCell align="right" sx={{ py: 0.5 }}>{h.cur_price ?? "—"}</TableCell>
                  <TableCell
                    align="right"
                    sx={{
                      py: 0.5,
                      fontWeight: 700,
                      color: h.pnl_pct == null ? "text.secondary" : h.pnl_pct >= 0 ? "error.main" : "success.main",
                    }}
                  >
                    {h.pnl_pct == null ? "—" : `${h.pnl_pct > 0 ? "+" : ""}${h.pnl_pct}%`}
                    {/* 截图导入带股数的才有金额;手动录入没填股数就只显示百分比 */}
                    {h.pnl_amount != null && (
                      <Box sx={{ fontWeight: 400, fontSize: 11 }}>
                        {h.pnl_amount > 0 ? "+" : ""}
                        {h.pnl_amount.toLocaleString()}
                      </Box>
                    )}
                  </TableCell>
                  <TableCell sx={{ py: 0.5, fontSize: 12 }}>
                    {v?.take_profit || v?.stop_loss ? (
                      <Stack spacing={0.25}>
                        {v.take_profit && <Box sx={{ color: "error.main" }}>盈:{v.take_profit}</Box>}
                        {v.stop_loss && <Box sx={{ color: "success.main" }}>损:{v.stop_loss}</Box>}
                      </Stack>
                    ) : (
                      <Typography variant="caption" color="text.disabled">
                        盘后跑诊断后显示
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell align="center" sx={{ py: 0.5, whiteSpace: "nowrap" }}>
                    {onPick && (
                      <Tooltip title="看分时">
                        <IconButton
                          size="small"
                          onClick={() => onPick({ code: h.code, name: h.name || h.code, boards: h.buy_boards })}
                        >
                          <ShowChartIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    )}
                    <Tooltip title="删除持仓">
                      <IconButton size="small" onClick={() => remove(h.code)}>
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
