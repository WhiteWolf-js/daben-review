import { useEffect, useState } from "react";
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
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import ImageIcon from "@mui/icons-material/Image";
import { getLadderBoard, type LadderBoard, type LadderCell, type Stock } from "../api";
import LadderGrid from "./LadderGrid";
import LadderPoster, { LADDER_WIDTH } from "./LadderPoster";
import LadderThemeMatrix from "./LadderThemeMatrix";
import { usePosterExport } from "../hooks/usePosterExport";

/**
 * 连板天梯(网页面板):与天梯图海报**同一份网格排版**(LadderGrid),
 * 含断板划线与「炸板后回封 ↺」;点个股看分时;右上角可导出天梯图 PNG。
 *
 * 两种切法共用同一份 ladder-board 数据(切换不重新请求):
 *   `board` 按板级分行 —— 看**市场高度结构**(最高板在哪、哪些断板)
 *   `theme` 按题材分行 —— 看**主线有没有接力**(LadderThemeMatrix)
 * 天梯本身不按题材排版:实测连板档内题材几乎全是孤票(某日 4 板 9 只 = 9 个题材),
 * 分组只会把 8 列网格切碎;题材是正交维度,该另开一张表而不是改排序。
 */
export default function LadderView({
  date,
  onPick,
}: {
  date: string;
  onPick: (s: Stock) => void;
}) {
  const [d, setD] = useState<LadderBoard | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"board" | "theme">("board");
  const { ref, exporting, download } = usePosterExport(`连板天梯_${date}.png`);

  useEffect(() => {
    if (!date) return;
    setD(null);
    setLoading(true);
    getLadderBoard(date)
      .then(setD)
      .catch(() => setD(null))
      .finally(() => setLoading(false));
  }, [date]);

  // LadderCell → Stock(分时弹窗只用 code/name,其余给默认值)
  const pick = (c: LadderCell) =>
    onPick({
      code: c.code, name: c.name, boards: 0, pct: c.pct,
      seal_strength: c.seal_strength, first_seal: c.first_seal,
      break_times: c.break_times ?? 0, turnover: 0, zt_stat: "", industry: c.industry,
    } as Stock);

  return (
    <Card>
      <CardContent>
        <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
          <Stack direction="row" alignItems="baseline" spacing={1} flexWrap="wrap" useFlexGap>
            <Typography variant="subtitle1" fontWeight={600}>
              连板天梯
            </Typography>
            {d && (
              <Typography variant="caption" color="text.secondary">
                涨停 {d.sealed} · 断板 {d.broken} · 最高 {d.max_board}板
                {view === "board" && " · 时间=最终封板,↺N=炸板 N 次后回封"}
              </Typography>
            )}
          </Stack>
          <Stack direction="row" alignItems="center" spacing={1}>
            <ToggleButtonGroup
              size="small"
              exclusive
              value={view}
              onChange={(_, v) => v && setView(v)}
              sx={{ "& .MuiToggleButton-root": { py: 0.25, px: 1, fontSize: 12 } }}
            >
              <ToggleButton value="board">按板级</ToggleButton>
              <ToggleButton value="theme">按题材</ToggleButton>
            </ToggleButtonGroup>
            {/* 海报只出板级天梯:题材矩阵行数不定(某日 22 行),固定宽高的海报排不下 */}
            <Button
              size="small"
              startIcon={<ImageIcon />}
              disabled={!d?.rows.length}
              onClick={() => setOpen(true)}
            >
              导出天梯图
            </Button>
          </Stack>
        </Stack>

        {/* 行业分布(仅板级视图:题材视图里再列行业只会和题材行打架) */}
        {view === "board" && d && d.industries.length > 0 && (
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1.25, mb: 1.5 }}>
            {d.industries.map((i) => (
              <Typography key={i.name} variant="caption" sx={{ color: "#58a6ff", fontWeight: 600 }}>
                {i.name}({i.count})
              </Typography>
            ))}
          </Box>
        )}

        {loading && (
          <Box sx={{ display: "flex", justifyContent: "center", py: 3 }}>
            <CircularProgress size={22} />
          </Box>
        )}
        {d && d.rows.length > 0 && (
          // 首板档在窄屏排 8 列会挤,横向滚动比换行好读
          <Box sx={{ overflowX: "auto" }}>
            <Box sx={{ minWidth: 880 }}>
              {view === "board" ? (
                <LadderGrid data={d} scale={0.85} onPick={pick} />
              ) : (
                <LadderThemeMatrix data={d} onPick={pick} />
              )}
            </Box>
          </Box>
        )}
        {d && d.rows.length === 0 && !loading && (
          <Typography variant="body2" color="text.secondary">
            {date} 无涨停池数据。
          </Typography>
        )}
        {view === "board" && (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: "block" }}>
            划线=昨日连板今日断板(后跟当日涨跌幅);↺N=炸板 N 次后回封,橙色打折、**红色(≥5 次)是烂板**;
            「回封」=涨停池未收录、按收盘涨幅判定为涨停,封板时刻未知;点个股看分时。
          </Typography>
        )}
      </CardContent>

      {/* 导出预览:按原始 1280 宽渲染(不缩放,否则 html-to-image 出图会变小),窗口不够宽则滚动 */}
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth={false}>
        <DialogContent sx={{ p: 2, bgcolor: "#010409", overflow: "auto" }}>
          <Box ref={ref} sx={{ width: LADDER_WIDTH }}>
            <LadderPoster date={date} />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>关闭</Button>
          <Button
            variant="contained"
            onClick={download}
            disabled={exporting}
            startIcon={exporting ? <CircularProgress size={14} color="inherit" /> : <ImageIcon />}
          >
            下载 PNG
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}
