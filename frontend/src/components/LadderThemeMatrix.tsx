import { Box, Stack, Tooltip, Typography } from "@mui/material";
import type { LadderBoard, LadderCell } from "../api";
import { fmtSeal } from "./LadderGrid";

/** 一条题材的纵向梯队 */
export interface ThemeLadderRow {
  theme: string;
  hot: boolean; // 有同题材联动票(来自 cell.sector_hot),亮色
  total: number;
  maxBoard: number; // 含断板票的最高档
  maxAlive: number; // 未断票的最高档;0 = 顶部全断
  topBroken: boolean; // 最高档全是断板票 —— 高度被打掉,最关键的信号
  byBoard: Record<number, LadderCell[]>;
}

// 只有 ≥2 只才算「梯队」;单票题材没有接力可谈,汇总成一行
const MIN_PEERS = 2;

/**
 * 把天梯数据按题材重组成「题材 × 板级」矩阵。
 *
 * **分组键刻意用 `cell.sector`**(天梯格子上显示的那个标签),不重新按 themes 多题材展开:
 * 一是保证同一只票在天梯上标什么、在矩阵里就落哪一行(口径零分歧);
 * 二是多题材展开会让一只票出现在多行,家数与天梯各档票数总和对不上。
 */
export function buildThemeLadder(data: LadderBoard, minPeers = MIN_PEERS) {
  const groups = new Map<string, { hot: boolean; byBoard: Record<number, LadderCell[]> }>();
  for (const row of data.rows) {
    for (const s of row.stocks) {
      const key = s.sector || s.industry || "其他";
      let g = groups.get(key);
      if (!g) {
        g = { hot: false, byBoard: {} };
        groups.set(key, g);
      }
      g.hot = g.hot || s.sector_hot;
      (g.byBoard[row.boards] ||= []).push(s);
    }
  }

  const rows: ThemeLadderRow[] = [];
  const solo: string[] = [];
  for (const [theme, g] of groups) {
    const tiers = Object.keys(g.byBoard).map(Number);
    const total = tiers.reduce((n, b) => n + g.byBoard[b].length, 0);
    if (total < minPeers) {
      solo.push(theme);
      continue;
    }
    const maxBoard = Math.max(...tiers);
    const alive = tiers.filter((b) => g.byBoard[b].some((s) => !s.broken));
    rows.push({
      theme,
      hot: g.hot,
      total,
      maxBoard,
      maxAlive: alive.length ? Math.max(...alive) : 0,
      topBroken: g.byBoard[maxBoard].every((s) => s.broken),
      byBoard: g.byBoard,
    });
  }

  // **身位优先**排序,与候选池主线口径一致:泛业绩标签(中报预增之类)涨停多但零连板,
  // 按家数排会把它顶到第一名,而它不是主线。未断高度 > 含断高度 > 家数 > 名称。
  rows.sort(
    (a, b) =>
      b.maxAlive - a.maxAlive ||
      b.maxBoard - a.maxBoard ||
      b.total - a.total ||
      a.theme.localeCompare(b.theme),
  );
  // 列只保留成梯队题材真正占用的板级,免得为一个空档撑出一整列
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r.byBoard).map(Number)))].sort(
    (a, b) => b - a,
  );
  return { rows, cols, solo: solo.sort() };
}

const BORDER = "1px solid #21262d";

/** 格子里的一只票:名称(断板划线)+ 封板时间 / 断板涨幅 */
function MiniCell({ s, onPick }: { s: LadderCell; onPick?: (s: LadderCell) => void }) {
  const sub = s.broken
    ? `${s.pct >= 0 ? "+" : ""}${s.pct.toFixed(2)}`
    : s.reseal
      ? "回封"
      : s.is_yizi
        ? "一字"
        : fmtSeal(s.last_seal || s.first_seal);

  // 名称与时间**同一行**:竖排会让「首板 11 只」那种格子把整行撑到 11 行高,
  // 矩阵一屏放不下两条题材,反而看不出跨题材对比
  const body = (
    <Box
      onClick={onPick ? () => onPick(s) : undefined}
      sx={{
        px: 0.5,
        display: "flex",
        alignItems: "baseline",
        gap: 0.5,
        borderRadius: 0.5,
        cursor: onPick ? "pointer" : "default",
        "&:hover": onPick ? { bgcolor: "rgba(255,255,255,0.05)" } : undefined,
      }}
    >
      <Typography
        sx={{
          fontSize: 13,
          fontWeight: 700,
          lineHeight: 1.6,
          whiteSpace: "nowrap",
          color: s.broken ? "#6e7681" : "#e6edf3",
          textDecoration: s.broken ? "line-through" : "none",
          textDecorationColor: s.broken ? "#e5484d" : undefined,
          textDecorationThickness: s.broken ? "2px" : undefined,
        }}
      >
        {s.name}
      </Typography>
      <Typography
        sx={{
          fontSize: 10,
          lineHeight: 1.6,
          whiteSpace: "nowrap",
          color: s.broken ? (s.pct >= 0 ? "#8b949e" : "#30a46c") : "#6e7681",
        }}
      >
        {sub}
      </Typography>
    </Box>
  );
  if (!onPick) return body;
  return (
    <Tooltip title={`${s.code} · ${s.broken ? "昨日连板今日断板" : `封流比${(s.seal_strength * 100).toFixed(2)}%`} · 点击看分时`}>
      {body}
    </Tooltip>
  );
}

/**
 * 题材梯队矩阵 —— 行=题材(身位优先)、列=板级(高→低)、格子=票。
 *
 * 回答天梯排版表达不了的那个问题:**这条线有没有接力**。
 * 天梯按板级分行,同题材的票散落在各行,只能靠肉眼找同色题材字;
 * 这里一行看完一条线的完整高度分布:
 *   连续格子 = 有梯队(主线);中间空档 = 断层;顶格划线 = 高度被打掉(标「顶断」)。
 *
 * 数据与 LadderView 共用同一份 ladder-board,不额外请求。
 */
export default function LadderThemeMatrix({
  data,
  onPick,
}: {
  data: LadderBoard;
  onPick?: (s: LadderCell) => void;
}) {
  const { rows, cols, solo } = buildThemeLadder(data);

  if (!rows.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        当日无成梯队题材(全部为单票题材)。
      </Typography>
    );
  }

  const grid = `minmax(150px, 1.4fr) repeat(${cols.length}, minmax(74px, 1fr))`;

  return (
    <Box>
      <Box sx={{ border: BORDER, borderRadius: 1, overflow: "hidden" }}>
        {/* 表头:板级 */}
        <Box sx={{ display: "grid", gridTemplateColumns: grid, bgcolor: "#161b22" }}>
          <Box sx={{ px: 1, py: 0.75, borderRight: BORDER }}>
            <Typography sx={{ fontSize: 12, color: "#8b949e", fontWeight: 600 }}>
              题材 · 家数
            </Typography>
          </Box>
          {cols.map((b) => (
            <Box key={b} sx={{ px: 1, py: 0.75, borderRight: BORDER, textAlign: "center" }}>
              <Typography sx={{ fontSize: 13, fontWeight: 800 }}>{b}板</Typography>
            </Box>
          ))}
        </Box>

        {rows.map((r, ri) => (
          <Box
            key={r.theme}
            sx={{
              display: "grid",
              gridTemplateColumns: grid,
              borderTop: ri === 0 ? "none" : BORDER,
              alignItems: "stretch",
            }}
          >
            <Box
              sx={{
                px: 1,
                py: 0.75,
                borderRight: BORDER,
                bgcolor: "#0d1117",
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
              }}
            >
              <Stack direction="row" alignItems="baseline" spacing={0.75} flexWrap="wrap" useFlexGap>
                <Typography
                  sx={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: r.hot ? "#f5a623" : "#8b949e",
                  }}
                >
                  {r.theme}
                </Typography>
                <Typography sx={{ fontSize: 11, color: "#6e7681" }}>{r.total}只</Typography>
                {/* 顶格全是断板 = 这条线的最高身位今天被打掉,后面的票失去带动 */}
                {r.topBroken && (
                  <Tooltip title={`最高 ${r.maxBoard} 板今日断板,该线高度被打掉`}>
                    <Box
                      component="span"
                      sx={{
                        fontSize: 10,
                        fontWeight: 700,
                        color: "#e5484d",
                        border: "1px solid #e5484d",
                        borderRadius: 0.5,
                        px: 0.4,
                        lineHeight: 1.5,
                      }}
                    >
                      顶断
                    </Box>
                  </Tooltip>
                )}
              </Stack>
            </Box>
            {cols.map((b) => {
              const cell = r.byBoard[b];
              return (
                <Box
                  key={b}
                  sx={{
                    px: 0.25,
                    py: 0.5,
                    borderRight: BORDER,
                    display: "flex",
                    flexDirection: "column",
                    // 空档必须**画出记号**:行高由最厚的格子决定,只靠留白的话
                    // 「本档无票」和「本档 1 只、下面是被撑出来的空白」长得一模一样,
                    // 断层就读不出来了 —— 而断层正是这张表要回答的问题
                    justifyContent: cell?.length ? "flex-start" : "center",
                    alignItems: cell?.length ? "stretch" : "center",
                    bgcolor: cell?.length ? undefined : "rgba(255,255,255,0.02)",
                  }}
                >
                  {cell?.length ? (
                    cell.map((s) => <MiniCell key={s.code} s={s} onPick={onPick} />)
                  ) : (
                    <Typography sx={{ fontSize: 12, color: "#30363d", lineHeight: 1 }}>—</Typography>
                  )}
                </Box>
              );
            })}
          </Box>
        ))}
      </Box>

      {/* 单票题材:没有接力可谈,但要交代总数,否则家数和天梯对不上 */}
      {solo.length > 0 && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
          单票题材 {solo.length} 个(无同题材接力,未入表):{solo.join("、")}
        </Typography>
      )}
      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
        行按**身位优先**排(未断最高板 → 含断最高板 → 家数),不按家数 ——
        泛业绩标签涨停多但零连板,不是主线;橙色题材=有同题材联动,灰色=碎片标签/退回行业;
        划线=昨日连板今日断板;空格=该档无票,中间连续空档即**断层**。
      </Typography>
    </Box>
  );
}
