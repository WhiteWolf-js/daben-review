import { Box, Stack, Tooltip, Typography } from "@mui/material";
import type { LadderBoard, LadderCell } from "../api";

/** HHMMSS → HH:MM */
export const fmtSeal = (s?: string) => {
  const t = (s || "").replace(/\D/g, "");
  return t.length >= 4 ? `${t.slice(0, 2)}:${t.slice(2, 4)}` : "";
};

// 炸板 ≥5 次的回封算烂板:主力借涨停价反复出货,和「炸一次又封回去」差着量级
const BAD_SEAL_BREAKS = 5;

/**
 * 一格:上=最终封板时间 / 一字板标 / 断板涨跌幅,中=名称(断板划线),下=行业。
 * ↺N = 炸板 N 次后回封(封板质量打折,≥5 次标红);断板 = 昨日连板今日没封住,高度被打掉。
 */
function Cell({
  s,
  scale,
  onPick,
}: {
  s: LadderCell;
  scale: number; // 1=海报尺寸,<1=网页内紧凑
  onPick?: (s: LadderCell) => void;
}) {
  const up = s.pct >= 0;
  const breaks = s.break_times ?? 0;
  const rebuy = breaks > 0;
  const badSeal = breaks >= BAD_SEAL_BREAKS;
  const px = (n: number) => Math.round(n * scale);
  // 炸一次只标 ↺,炸多次把次数打出来 —— 26 次和 1 次的封板质量不是一回事
  const reMark = rebuy ? `↺${breaks > 1 ? breaks : ""}` : "";

  const body = (
    <Box
      onClick={onPick ? () => onPick(s) : undefined}
      sx={{
        px: 0.5, py: px(6) / 8, textAlign: "center", minWidth: 0,
        cursor: onPick ? "pointer" : "default",
        borderRadius: 0.5,
        "&:hover": onPick ? { bgcolor: "rgba(255,255,255,0.05)" } : undefined,
      }}
    >
      {s.broken ? (
        <Typography sx={{ fontSize: px(13), fontWeight: 700, color: up ? "#e5484d" : "#30a46c", lineHeight: 1.4 }}>
          {up ? "+" : ""}
          {s.pct.toFixed(2)}
        </Typography>
      ) : s.reseal ? (
        // 涨停池没收录、按收盘涨幅兜底判定的回封票:回封时刻拿不到,只报炸板次数
        <Typography
          sx={{ fontSize: px(13), fontWeight: 700, lineHeight: 1.4, color: badSeal ? "#e5484d" : "#f5a623" }}
        >
          回封{reMark}
        </Typography>
      ) : s.is_yizi ? (
        <Box
          component="span"
          sx={{
            display: "inline-block", bgcolor: "#e5484d", color: "#fff", fontSize: px(11),
            fontWeight: 700, px: 0.75, borderRadius: 0.5, lineHeight: 1.6,
          }}
        >
          一字板
        </Box>
      ) : (
        <Typography
          sx={{ fontSize: px(13), lineHeight: 1.4, color: badSeal ? "#e5484d" : rebuy ? "#f5a623" : "#8b949e" }}
        >
          {fmtSeal(s.last_seal || s.first_seal)}
          {reMark}
        </Typography>
      )}

      <Typography
        sx={{
          fontSize: px(17), fontWeight: 700, lineHeight: 1.45, whiteSpace: "nowrap",
          color: s.broken ? "#6e7681" : "#e6edf3",
          textDecoration: s.broken ? "line-through" : "none",
          textDecorationColor: s.broken ? "#e5484d" : undefined,
          textDecorationThickness: s.broken ? "2px" : undefined,
        }}
      >
        {s.name}
      </Typography>
      {/* 所属板块 = 当天真形成板块效应的题材(不是行业:行业是静态分类且会误导,
          美利云恒为「IT服务Ⅱ」而它连板靠「算力租赁」)。
          亮橙=有同题材联动票托底;暗灰=孤票/碎片标签/退回行业 —— 扫一眼就知道哪些票有板块托底。
          长题材名截断,全称与全部信息进 tooltip(格子只有 1/8 宽,放不下 7 字以上)。 */}
      <Typography
        sx={{
          fontSize: px(11), lineHeight: 1.4, whiteSpace: "nowrap",
          overflow: "hidden", textOverflow: "ellipsis",
          color: s.broken ? "#484f58" : s.sector_hot ? "#f5a623" : "#6e7681",
        }}
      >
        {s.sector || s.industry}
      </Typography>
    </Box>
  );

  if (!onPick) return body;
  const tip = [
    // 题材是「今天为什么涨」,行业是静态归类,两个都给
    `${s.code} · ${s.sector}${s.sector_hot ? "(当日板块)" : "(无同题材联动)"} · 行业 ${s.industry}`,
    s.broken
      ? "昨日连板今日断板"
      : s.reseal
        ? "尾盘回封(涨停池未收录,按收盘涨幅判定;封板时刻与封单强度未知)"
        : `封流比${(s.seal_strength * 100).toFixed(2)}%`,
    rebuy ? `炸板${breaks}次${badSeal ? ",封板质量差" : "后回封"}` : "",
    "点击看分时",
  ]
    .filter(Boolean)
    .join(" · ");
  return <Tooltip title={tip}>{body}</Tooltip>;
}

/**
 * 连板天梯网格 —— **海报与网页面板共用同一份排版**(别写两套,改一处就好)。
 *
 * scale 控制字号缩放:海报用 1(1280 宽),网页内用 0.85 更紧凑。
 * onPick 只在网页内传(点个股看分时);海报不传,不出现 hover/Tooltip。
 */
export default function LadderGrid({
  data,
  cols = 8,
  scale = 1,
  onPick,
}: {
  data: LadderBoard;
  cols?: number;
  scale?: number;
  onPick?: (s: LadderCell) => void;
}) {
  return (
    <Box sx={{ border: "1px solid #21262d", borderRadius: 1, overflow: "hidden" }}>
      {data.rows.map((row, ri) => (
        <Stack
          key={row.boards}
          direction="row"
          sx={{ borderTop: ri === 0 ? "none" : "1px solid #21262d", alignItems: "stretch" }}
        >
          <Box
            sx={{
              width: Math.round(96 * scale), flexShrink: 0, bgcolor: "#161b22",
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", borderRight: "1px solid #21262d", py: 1,
            }}
          >
            <Typography sx={{ fontSize: Math.round(20 * scale), fontWeight: 800 }}>
              {row.boards}板
            </Typography>
            {/* 每档都显示只数,不只是多的那几档 */}
            <Typography sx={{ fontSize: Math.round(12 * scale), color: "#8b949e" }}>
              ({row.stocks.length})
            </Typography>
          </Box>
          <Box
            sx={{
              flexGrow: 1, display: "grid",
              gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
              alignContent: "start", py: 0.5,
            }}
          >
            {row.stocks.map((s) => (
              <Cell key={s.code} s={s} scale={scale} onPick={onPick} />
            ))}
          </Box>
        </Stack>
      ))}
    </Box>
  );
}
