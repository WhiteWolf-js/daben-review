import { useEffect, useState } from "react";
import { Box, Typography } from "@mui/material";
import { getHoldingAnalysis, getHoldings } from "../api";
import HoldingBoard, { type BoardRow } from "./HoldingBoard";

/** 比天梯窄:只有 5 列,1080 够用(和复盘海报同宽,手机看清楚) */
export const HOLDING_WIDTH = 1080;

const fmtDate = (d: string) =>
  d.length === 8 ? `${Number(d.slice(4, 6))}月${Number(d.slice(6))}日` : d;

/**
 * 明日处置速览海报(1080 宽,深色)。排版复用 HoldingBoard —— 与网页面板同一份实现。
 * 与复盘/竞价/天梯海报同一套 data-poster-root / data-poster-ready 约定,供后端 Playwright 等待就绪。
 */
export default function HoldingPoster({ date }: { date: string }) {
  const [rows, setRows] = useState<BoardRow[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setReady(false);
    getHoldings()
      .then(async (hs) => {
        const list = await Promise.all(hs.map((h) => getHoldingAnalysis(h.code).catch(() => null)));
        setRows(hs.map((h, i) => ({ h, v: list[i]?.verdict ?? {} })).filter((r) => r.v.verdict));
      })
      .catch(() => setRows([]))
      .finally(() => setReady(true)); // 失败也置位,避免后端无限等待
  }, [date]);

  return (
    <Box
      data-poster-root="1"
      data-poster-ready={ready ? "1" : "0"}
      sx={{
        width: HOLDING_WIDTH, bgcolor: "#0d1117", color: "#e6edf3", px: 4, py: 3,
        boxSizing: "border-box", fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
      }}
    >
      <Typography sx={{ fontSize: 30, fontWeight: 800, textAlign: "center" }}>
        <span style={{ color: "#e5484d" }}>{fmtDate(date)}</span> 持仓处置速览
      </Typography>
      <Typography sx={{ fontSize: 13, color: "#8b949e", textAlign: "center", mt: 0.5, mb: 2 }}>
        序号=处置优先级(先动谁)· 触发价为条件判断,不满足条件就不动
      </Typography>

      {rows.length > 0 ? (
        <HoldingBoard rows={rows} />
      ) : (
        <Typography sx={{ fontSize: 15, color: "#8b949e", textAlign: "center", mt: 3 }}>
          没有已诊断的持仓 —— 先在盘后视图跑一次持仓诊断。
        </Typography>
      )}

      <Typography sx={{ fontSize: 11, color: "#484f58", mt: 2, textAlign: "center" }}>
        由 agent 盘后诊断结构化提取 · 仅供个人复盘参考,非投资建议
      </Typography>
    </Box>
  );
}
