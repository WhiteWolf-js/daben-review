import { useEffect, useState } from "react";
import { Box, Typography } from "@mui/material";
import { getLadderBoard, type LadderBoard } from "../api";
import LadderGrid from "./LadderGrid";

/** 天梯图比复盘海报宽:首板档要排 8 列 */
export const LADDER_WIDTH = 1280;

const fmtDate = (d: string) =>
  d.length === 8 ? `${Number(d.slice(4, 6))}月${Number(d.slice(6))}日` : d;

/** 标题 + 行业分布 + 脚注,供海报与网页面板共用(网页面板不需要固定宽) */
export function LadderHeader({ date, d }: { date: string; d: LadderBoard | null }) {
  return (
    <>
      <Typography sx={{ fontSize: 30, fontWeight: 800, textAlign: "center" }}>
        <span style={{ color: "#e5484d" }}>{fmtDate(date)}</span> 连板天梯
      </Typography>
      {d && (
        <Typography sx={{ fontSize: 13, color: "#8b949e", textAlign: "center", mt: 0.5 }}>
          涨停 {d.sealed} · 断板 {d.broken} · 最高 {d.max_board}板 ·
          时间=最终封板,↺=炸板后回封,划线=昨日连板今日断板
        </Typography>
      )}
      {d && d.industries.length > 0 && (
        <Box sx={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 1.5, mt: 1.5 }}>
          {d.industries.map((i) => (
            <Typography key={i.name} sx={{ fontSize: 15, fontWeight: 600, color: "#58a6ff" }}>
              {i.name}({i.count})
            </Typography>
          ))}
        </Box>
      )}
    </>
  );
}

/**
 * 连板天梯海报(1280 宽,深色)。网格排版复用 LadderGrid —— 与网页面板同一份实现。
 * 与复盘/竞价海报同一套 data-poster-root / data-poster-ready 约定,供后端 Playwright 等待就绪。
 */
export default function LadderPoster({ date }: { date: string }) {
  const [d, setD] = useState<LadderBoard | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!date) return;
    setReady(false);
    getLadderBoard(date)
      .then(setD)
      .catch(() => {})
      .finally(() => setReady(true)); // 失败也置位,避免后端无限等待
  }, [date]);

  return (
    <Box
      data-poster-root="1"
      data-poster-ready={ready ? "1" : "0"}
      sx={{
        width: LADDER_WIDTH, bgcolor: "#0d1117", color: "#e6edf3", px: 4, py: 3,
        boxSizing: "border-box", fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
      }}
    >
      <LadderHeader date={date} d={d} />
      <Box sx={{ mt: 2 }}>{d && d.rows.length > 0 && <LadderGrid data={d} />}</Box>
      {(!d || d.rows.length === 0) && (
        <Typography sx={{ fontSize: 15, color: "#8b949e", textAlign: "center", mt: 3 }}>
          {date} 无涨停池数据。
        </Typography>
      )}
      <Typography sx={{ fontSize: 11, color: "#484f58", mt: 2, textAlign: "center" }}>
        数据 akshare 涨停池 + 昨日涨停今日表现 · 仅供个人复盘参考
      </Typography>
    </Box>
  );
}
