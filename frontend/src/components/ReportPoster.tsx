import { useEffect, useState } from "react";
import { Box, Typography } from "@mui/material";
import { getReport } from "../api";
import { REPORT_PARTS, reportPartTitles, sliceReportPart, stripJson } from "../utils/report";
import ReportStructured from "./ReportStructured";

/** 与摘要/持仓海报同宽 */
export const REPORT_WIDTH = 1080;

const fmtDate = (d: string) =>
  d.length === 8 ? `${Number(d.slice(4, 6))}月${Number(d.slice(6))}日` : d;

/**
 * 完整复盘长图(1080 宽,深色)。正文排版复用 `ReportStructured` —— 与网页「完整复盘正文」
 * 面板、以及 ReportBody 的「长图」导出按钮同一份实现,改一处三处一致。
 *
 * **默认拆两张出**(`?part=1|2`):整篇是 1:2.7 的细长图,飞书聊天气泡按高度压进去后
 * 宽度只剩 21%,字全糊;拆成两张各约 1:1.4 才和摘要海报一样清楚。不传 part 仍渲染整篇
 * (网页上手动看/导出用,页面能滚就不受气泡限制)。
 *
 * 与其它海报同一套 data-poster-root / data-poster-ready 约定,供后端 Playwright 等待就绪。
 */
export default function ReportPoster({ date, part = 0 }: { date: string; part?: number }) {
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

  const shown = part ? sliceReportPart(md, part) : md;
  // 副标题:整篇用固定五段说明,分张时用该张实际含的段标题(agent 改段名也对得上)
  const subtitle = part
    ? reportPartTitles(md, part).join(" · ")
    : "五段结构:数据基础 · 方向强弱 · 个股画像 · 核心矛盾 · 明日候选";

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
        {part > 0 && (
          <span style={{ color: "#8b949e", fontSize: 20, fontWeight: 600 }}>
            {" "}
            {part}/{REPORT_PARTS}
          </span>
        )}
      </Typography>
      {subtitle && (
        <Typography sx={{ fontSize: 13, color: "#8b949e", textAlign: "center", mt: 0.5, mb: 2 }}>
          {subtitle}
        </Typography>
      )}

      {shown.trim() ? (
        <ReportStructured md={shown} />
      ) : (
        <Typography sx={{ fontSize: 15, color: "#8b949e", textAlign: "center", mt: 3 }}>
          {date} 还没有复盘正文(先在网页端生成,或等盘后 15:30 自动跑)。
        </Typography>
      )}

      {/* 脚注只挂最后一张:两张都印一遍像各自独立,反而看不出是一篇的上下半 */}
      {(part === 0 || part === REPORT_PARTS) && (
        <Typography sx={{ fontSize: 11, color: "#484f58", mt: 2, textAlign: "center" }}>
          Claude agent 基于 L1 截面数据推理 · 归因为推断不保证对 · 仅供个人复盘参考
        </Typography>
      )}
    </Box>
  );
}
