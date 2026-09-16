import { useState } from "react";
import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  Stack,
  Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ImageIcon from "@mui/icons-material/Image";
import type { UsageCost } from "../api";
import { extractConflict } from "../utils/report";
import { usePosterExport } from "../hooks/usePosterExport";
import PosterView, { POSTER_WIDTH } from "./PosterView";

/**
 * 盘后决策区:只放「明日核心矛盾」+ 生成/导出动作。完整复盘正文交给折叠区的 ReportBody。
 * 状态由父级 useReport 持有(避免两处各自请求、生成后不同步)。
 */
export default function ReportSummary({
  date,
  md,
  createdAt,
  loading,
  usage,
  onGenerate,
}: {
  date: string;
  md: string;
  createdAt: string | null;
  loading: boolean;
  usage: UsageCost | null;
  onGenerate: () => void;
}) {
  const [posterOpen, setPosterOpen] = useState(false);
  const [posterReady, setPosterReady] = useState(false);
  // 截 PosterView 的 DOM 成 PNG(排版与后端 Playwright 出图共用同一组件)
  const { ref: posterRef, exporting, download: downloadPoster } = usePosterExport(`复盘_${date}.png`);

  const conflict = extractConflict(md);

  return (
    <Card>
      <CardContent>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
          <Stack direction="row" alignItems="baseline" spacing={1}>
            <Typography variant="subtitle1" fontWeight={600}>
              明日核心矛盾
            </Typography>
            {createdAt && (
              <Typography variant="caption" color="text.secondary">
                生成于 {createdAt}
              </Typography>
            )}
          </Stack>
          <Stack direction="row" spacing={1}>
            <Button size="small" startIcon={<ImageIcon />} disabled={!md || loading} onClick={() => setPosterOpen(true)}>
              导出图片
            </Button>
            <Button
              size="small"
              variant="contained"
              startIcon={loading ? <CircularProgress size={14} color="inherit" /> : <AutoAwesomeIcon />}
              disabled={loading || !date}
              onClick={onGenerate}
            >
              {md ? "重新生成" : "生成复盘"}
            </Button>
          </Stack>
        </Stack>

        {usage && (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
            本次 {(usage.total_tokens / 1000).toFixed(1)}k tokens · 约 ¥{usage.cost_cny.toFixed(2)}
          </Typography>
        )}

        {loading && !conflict && (
          <Typography variant="body2" color="text.secondary">
            agent 分析中(约 1-2 分钟),完整正文见下方「完整复盘正文」…
          </Typography>
        )}
        {!md && !loading && (
          <Typography variant="body2" color="text.secondary">
            该日期尚未生成复盘,点「生成复盘」(约 1-2 分钟)。
          </Typography>
        )}
        {conflict && (
          <Typography sx={{ fontSize: 14, lineHeight: 1.75, whiteSpace: "pre-wrap" }}>{conflict}</Typography>
        )}
        {md && !conflict && !loading && (
          <Typography variant="body2" color="text.secondary">
            本次复盘未识别到「明日核心矛盾」段,见下方完整正文。
          </Typography>
        )}
      </CardContent>

      {/* 海报预览 + 下载。按原始 1080 宽渲染(不做 transform/zoom 缩放,否则 html-to-image
          会测到缩放后的尺寸导致出图变小),窗口不够宽时由 Dialog 横向滚动 */}
      <Dialog open={posterOpen} onClose={() => setPosterOpen(false)} maxWidth={false}>
        <DialogContent sx={{ p: 2, bgcolor: "#010409", overflow: "auto" }}>
          <Box ref={posterRef} sx={{ width: POSTER_WIDTH }}>
            <PosterView date={date} onReady={setPosterReady} />
          </Box>
        </DialogContent>
        <DialogActions>
          {/* 没就绪不让下载:海报各 section 是「哪个接口先回来先画哪个」,提前截图会出一张
              缺「今日方向 / 明日候选」的残图,而且看不出少了东西(踩过) */}
          {!posterReady && (
            <Typography variant="caption" color="text.secondary" sx={{ mr: "auto", ml: 1 }}>
              数据加载中,完整后可下载…
            </Typography>
          )}
          <Button onClick={() => setPosterOpen(false)}>关闭</Button>
          <Button
            variant="contained"
            onClick={downloadPoster}
            disabled={exporting || !posterReady}
            startIcon={
              exporting || !posterReady ? <CircularProgress size={14} color="inherit" /> : <ImageIcon />
            }
          >
            下载 PNG
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}
