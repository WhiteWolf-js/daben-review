import { useEffect, useState } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import { getAuctionLive, type AuctionLive } from "../api";
import { POSTER_WIDTH } from "./PosterView";

const GRADE_COLOR: Record<string, string> = {
  "A+": "#30a46c",
  A: "#30a46c",
  B: "#3b82f6",
  C: "#f5a623",
  D: "#e5484d",
};

const PHASE_TEXT: Record<string, string> = {
  pre_cancel: "9:15–9:20 可撤单 · 仅参考",
  bidding: "竞价中 · 不可撤单",
  opened: "竞价已定格",
  closed: "当日开盘",
};

/** 高开配色:3–5% 最佳接力区(绿)、>7% 溢价过高(橙)、<2% 偏弱(灰) */
const gapColor = (g: number) => (g >= 3 && g <= 5 ? "#30a46c" : g > 7 ? "#f5a623" : g < 2 ? "#8b949e" : "#e5484d");
const trendMark = (t: string) => (t === "up" ? "↑" : t === "down" ? "↓" : "");

/**
 * 盘前竞价决策海报(1080 宽,深色):方向(题材竞价强弱)+ 可打标的(高开/量能/趋势/评级)+ agent 解读。
 *
 * 与复盘海报同一套 data-poster-root / data-poster-ready 约定,供后端 Playwright 截图等待就绪。
 * brief 由后端 ?brief= 传入(agent 盘前一段解读),缺失则不显示该段。
 */
export default function AuctionPoster({ brief = "" }: { brief?: string }) {
  const [data, setData] = useState<AuctionLive | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    getAuctionLive()
      .then(setData)
      .catch(() => {})
      .finally(() => setReady(true)); // 拉取失败也置位,避免后端无限等待
  }, []);

  const phase = data?.phase ?? "closed";
  const top = (data?.rows ?? []).slice(0, 6);

  return (
    <Box
      data-poster-root="1"
      data-poster-ready={ready ? "1" : "0"}
      sx={{
        width: POSTER_WIDTH,
        bgcolor: "#0d1117",
        color: "#e6edf3",
        px: 5,
        py: 4,
        boxSizing: "border-box",
        fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
      }}
    >
      <Stack direction="row" alignItems="baseline" justifyContent="space-between">
        <Typography sx={{ fontSize: 30, fontWeight: 800 }}>
          盘前竞价 · <span style={{ color: "#e5484d" }}>抢筹决策</span>
        </Typography>
        <Typography sx={{ fontSize: 16, color: "#f5a623", fontWeight: 700 }}>
          {PHASE_TEXT[phase]} {data?.ts ?? ""}
        </Typography>
      </Stack>
      <Typography sx={{ fontSize: 14, color: "#8b949e", mt: 0.5 }}>
        池 = {data?.base_date ?? "—"} 涨停池(连板全取 + 首板封流比前15){data?.emotion_phase ? ` · 昨日情绪:${data.emotion_phase}` : ""}
      </Typography>

      {/* 方向:题材竞价强弱 */}
      {(data?.themes ?? []).length > 0 && (
        <Box sx={{ mt: 3 }}>
          <Typography sx={{ fontSize: 18, fontWeight: 700, color: "#e5484d", mb: 1.25 }}>
            方向(一群票齐高开才算方向)
          </Typography>
          <Stack spacing={1}>
            {(data?.themes ?? []).slice(0, 4).map((t, i) => (
              <Stack key={t.theme} direction="row" alignItems="center" spacing={1.5}>
                <Typography sx={{ fontSize: 17, color: "#8b949e", width: 24 }}>{i + 1}</Typography>
                <Typography sx={{ fontSize: 19, fontWeight: 700, minWidth: 190 }}>{t.theme}</Typography>
                <Typography sx={{ fontSize: 17, fontWeight: 700, color: gapColor(t.avg_gap), minWidth: 90 }}>
                  均{t.avg_gap > 0 ? "+" : ""}
                  {t.avg_gap}%
                </Typography>
                <Typography sx={{ fontSize: 15, color: "#8b949e" }}>
                  {t.members}只 · 最高{t.max_board}板 · {t.amount_yi}亿
                </Typography>
                <Typography sx={{ fontSize: 15 }}>
                  {t.stocks.slice(0, 3).map((s) => s.name).join("、")}
                </Typography>
              </Stack>
            ))}
          </Stack>
        </Box>
      )}

      {/* 标的:个股竞价 */}
      {top.length > 0 && (
        <Box sx={{ mt: 3 }}>
          <Typography sx={{ fontSize: 18, fontWeight: 700, color: "#e5484d", mb: 1.25 }}>可打标的</Typography>
          <Stack spacing={1.25}>
            {top.map((r) => (
              <Box
                key={r.code}
                sx={{ borderLeft: "4px solid", borderColor: GRADE_COLOR[r.grade] ?? "#30363d", pl: 1.5 }}
              >
                <Stack direction="row" alignItems="center" spacing={1.25}>
                  <Chip
                    label={r.grade}
                    size="small"
                    sx={{ bgcolor: GRADE_COLOR[r.grade] ?? "#30363d", color: "#fff", fontWeight: 800, fontSize: 14, height: 24 }}
                  />
                  <Typography sx={{ fontSize: 20, fontWeight: 700 }}>
                    {r.in_candidates ? "★ " : ""}
                    {r.name}
                  </Typography>
                  <Typography sx={{ fontSize: 19, fontWeight: 800, color: gapColor(r.gap_pct) }}>
                    {r.gap_pct > 0 ? "+" : ""}
                    {r.gap_pct}% {trendMark(r.gap_trend)}
                  </Typography>
                  <Typography sx={{ fontSize: 15, color: "#f5a623" }}>昨{r.prev_boards}板</Typography>
                  <Typography sx={{ fontSize: 15, color: r.amount_yi < 0.5 ? "#8b949e" : "#c9d1d9" }}>
                    竞价{r.amount_yi}亿
                  </Typography>
                  <Typography sx={{ fontSize: 15, color: "#8b949e" }}>
                    封流比{(r.seal_strength * 100).toFixed(1)}%
                  </Typography>
                </Stack>
                <Typography sx={{ fontSize: 14, color: "#8b949e", mt: 0.25 }}>
                  {[r.theme.join("·"), ...r.notes.slice(0, 3)].filter(Boolean).join(" | ")}
                </Typography>
              </Box>
            ))}
          </Stack>
        </Box>
      )}

      {/* agent 盘前解读 */}
      {brief && (
        <Box sx={{ mt: 3 }}>
          <Typography sx={{ fontSize: 18, fontWeight: 700, color: "#e5484d", mb: 1.25 }}>agent 盘前解读</Typography>
          <Typography sx={{ fontSize: 16, lineHeight: 1.7, whiteSpace: "pre-wrap", color: "#c9d1d9" }}>
            {brief}
          </Typography>
        </Box>
      )}

      <Typography sx={{ fontSize: 12, color: "#484f58", mt: 3, textAlign: "center" }}>
        高开 3–5% 最佳接力区 · &gt;7% 溢价过高 · 竞价额&lt;0.5亿为无量假强 · ↑↓=9:20 起变化方向 · ★=昨晚候选
      </Typography>
    </Box>
  );
}
