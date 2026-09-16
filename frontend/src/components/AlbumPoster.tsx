import { useEffect, useState } from "react";
import { Box, Stack, Typography } from "@mui/material";
import { getEmotion, type Emotion } from "../api";

/**
 * 抖音图集海报(竖屏 3:4)。
 *
 * 与飞书推送的复盘海报(PosterView,横宽 1080)不同——这套是抖音图集专用,
 * 每张 1080×1440,深色,右下角带「谢尔比天梯」水印 + 页码。复用现有 API,
 * 不新增后端接口。后端 poster.py 用 kind="album" 遍历 [data-poster-card] 截图。
 *
 * 先只做第 1 张(情绪封面);后续板块(方向/天梯/候选/矛盾)往 cards 数组加。
 */

/** 图集卡片固定尺寸 3:4。后端 device_scale_factor=2 → 输出 2160×2880。 */
export const ALBUM_W = 1080;
export const ALBUM_H = 1440;

const fmtDate = (d: string) =>
  d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : d;

function BigStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Box sx={{ flex: 1, textAlign: "center" }}>
      <Typography sx={{ fontSize: 60, fontWeight: 800, lineHeight: 1, color: color ?? "#e6edf3" }}>
        {value}
      </Typography>
      <Typography sx={{ fontSize: 22, color: "#8b949e", mt: 1.5 }}>{label}</Typography>
    </Box>
  );
}

/** 右下角水印:抖音 ID + 页码。所有图集卡片共用。 */
function Watermark({ page, total }: { page: number; total: number }) {
  return (
    <Box sx={{ position: "absolute", right: 28, bottom: 20, textAlign: "right" }}>
      <Typography sx={{ fontSize: 18, fontWeight: 700, color: "#58a6ff", letterSpacing: 1 }}>
        谢尔比天梯
      </Typography>
      <Typography sx={{ fontSize: 13, color: "#484f58", mt: 0.25 }}>
        {page} / {total}
      </Typography>
    </Box>
  );
}

/** 第 1 张:情绪封面(日期 + phase_hint 主视觉 + 五大数字)。 */
function CoverCard({ date, emotion }: { date: string; emotion: Emotion | null }) {
  const me = emotion?.money_effect;
  const meColor = (me ?? 0) > 0 ? "#e5484d" : "#30a46c";
  return (
    <Box
      data-poster-card="cover"
      sx={{
        width: ALBUM_W,
        height: ALBUM_H,
        bgcolor: "#0d1117",
        color: "#e6edf3",
        display: "flex",
        flexDirection: "column",
        boxSizing: "border-box",
        fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* 顶部标题 */}
      <Box sx={{ px: 7, pt: 7 }}>
        <Typography sx={{ fontSize: 48, fontWeight: 800, letterSpacing: 2 }}>打板复盘</Typography>
        <Typography sx={{ fontSize: 30, color: "#8b949e", mt: 0.5 }}>{fmtDate(date)}</Typography>
      </Box>

      {/* 主视觉:情绪温度 + phase_hint 巨字 */}
      <Box sx={{ textAlign: "center", mt: 7 }}>
        <Typography sx={{ fontSize: 26, color: "#8b949e", letterSpacing: 10 }}>
          情 绪 温 度
        </Typography>
        <Typography
          sx={{ fontSize: 128, fontWeight: 900, color: "#f5a623", mt: 3, letterSpacing: 16 }}
        >
          {emotion?.phase_hint ?? "—"}
        </Typography>
        {emotion?.market_state_hint && (
          <Typography
            sx={{ fontSize: 22, color: "#c9d1d9", mt: 3, px: 10, lineHeight: 1.6 }}
          >
            {emotion.market_state_hint}
          </Typography>
        )}
      </Box>

      {/* 五大数字:3 + 2 两行,贴底 */}
      {emotion && (
        <Stack direction="row" sx={{ px: 7, mt: "auto", mb: 2 }}>
          <BigStat label="涨停" value={String(emotion.zt_count)} color="#e5484d" />
          <BigStat label="连板" value={String(emotion.lianban_count)} />
          <BigStat label="最高板" value={`${emotion.max_board}板`} />
        </Stack>
      )}
      {emotion && (
        <Stack direction="row" sx={{ px: 7, mb: 9 }}>
          <BigStat
            label="炸板率"
            value={`${(emotion.break_rate * 100).toFixed(0)}%`}
            color={emotion.break_rate >= 0.4 ? "#e5484d" : undefined}
          />
          <BigStat
            label="赚钱效应"
            value={me == null ? "—" : `${me > 0 ? "+" : ""}${me}%`}
            color={meColor}
          />
        </Stack>
      )}

      <Watermark page={1} total={5} />
    </Box>
  );
}

/**
 * 图集根容器:纵向排列所有卡片,每张 1080×1440。
 * data-poster-root/data-poster-ready 供后端 Playwright 等待就绪;
 * 后端遍历 [data-poster-card] 逐张截图。
 */
export default function AlbumPoster({ date }: { date: string }) {
  const [emotion, setEmotion] = useState<Emotion | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!date) return;
    setReady(false);
    Promise.allSettled([getEmotion(date).then(setEmotion)]).then(() => setReady(true));
  }, [date]);

  return (
    <Box
      data-poster-root="1"
      data-poster-ready={ready ? "1" : "0"}
      sx={{ display: "flex", flexDirection: "column", bgcolor: "#0d1117" }}
    >
      <CoverCard date={date} emotion={emotion} />
      {/* TODO: 方向 / 天梯 / 候选 / 矛盾 卡片,样式确认后逐张加 */}
    </Box>
  );
}
