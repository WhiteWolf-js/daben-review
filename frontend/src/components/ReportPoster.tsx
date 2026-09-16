import { useEffect, useState } from "react";
import { Box, Typography } from "@mui/material";
import { getReport } from "../api";
import { stripJson } from "../utils/report";
import ReportStructured from "./ReportStructured";

/** 与持仓/复盘海报同宽:正文是长文,窄一点手机上一屏能读完一行 */
export const REPORT_WIDTH = 1080;

const fmtDate = (d: string) =>
  d.length === 8 ? `${Number(d.slice(4, 6))}月${Number(d.slice(6))}日` : d;

/**
 * 完整复盘长图(1080 宽,深色)。正文排版复用 `ReportStructured` —— 与网页「完整复盘正文」
 * 面板、以及 ReportBody 的「长图」导出按钮同一份实现,改一处三处一致。
 *
 * 与复盘/竞价/天梯/持仓海报同一套 data-poster-root / data-poster-ready 约定,
 * 供后端 Playwright 等待就绪。**这是唯一一种高度不定的海报**:后端 `_KIND_SCALE`
 * 给它降到 1.5 倍,2 倍会到几十 MB 推不过飞书。
 */
export default function ReportPoster({ date }: { date: string }) {
  const [md, setMd] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!date) return;
    setReady(false);
    getReport(date)
      .then((r) => setMd(stripJson(r.markdown || "")))
      .catch(() => setMd(""))
      .finally(() => setReady(true)); // 失败也置位,避免后端无限等待
  }, [date]);

  return (
    <Box
      data-poster-root="1"
      data-poster-ready={ready ? "1" : "0"}
      sx={{
        width: REPORT_WIDTH, bgcolor: "#0d1117", color: "#e6edf3", px: 4, py: 3,
        boxSizing: "border-box", fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
      }}
    >
      <Typography sx={{ fontSize: 30, fontWeight: 800, textAlign: "center" }}>
        <span style={{ color: "#e5484d" }}>{fmtDate(date)}</span> 完整复盘
      </Typography>
      <Typography sx={{ fontSize: 13, color: "#8b949e", textAlign: "center", mt: 0.5, mb: 2 }}>
        五段结构:数据基础 · 方向强弱 · 个股画像 · 核心矛盾 · 明日候选
      </Typography>

      {md.trim() ? (
        <ReportStructured md={md} />
      ) : (
        <Typography sx={{ fontSize: 15, color: "#8b949e", textAlign: "center", mt: 3 }}>
          {date} 还没有复盘正文(先在网页端生成,或等盘后 15:30 自动跑)。
        </Typography>
      )}

      <Typography sx={{ fontSize: 11, color: "#484f58", mt: 2, textAlign: "center" }}>
        Claude agent 基于 L1 截面数据推理 · 归因为推断不保证对 · 仅供个人复盘参考
      </Typography>
    </Box>
  );
}
