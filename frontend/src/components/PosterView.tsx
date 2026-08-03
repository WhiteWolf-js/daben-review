import { useEffect, useState, type ReactNode } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import {
  getCandidates,
  getEmotion,
  getLadder,
  getReport,
  getThemeHeat,
  type Candidate,
  type Emotion,
  type ThemeRow,
} from "../api";
import { extractConflict } from "../utils/report";

/** 海报固定宽度(px)。前端导出与后端 Playwright 截图共用此排版,勿改成响应式。 */
export const POSTER_WIDTH = 1080;

const fmtDate = (d: string) => (d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : d);

// 评级配色:与 CandidatePanel 同一套语义(A+/A 强、B 中性、C 弱、D 回避)
const GRADE_COLOR: Record<string, string> = {
  "A+": "#30a46c",
  A: "#30a46c",
  B: "#3b82f6",
  C: "#f5a623",
  D: "#e5484d",
};

const GRADE_ORDER = ["A+", "A", "B", "C", "D"];

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Box sx={{ flex: 1, textAlign: "center" }}>
      <Typography sx={{ fontSize: 40, fontWeight: 800, lineHeight: 1.1, color: color ?? "#e6edf3" }}>
        {value}
      </Typography>
      <Typography sx={{ fontSize: 15, color: "#8b949e", mt: 0.5 }}>{label}</Typography>
    </Box>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box sx={{ mt: 3 }}>
      <Typography sx={{ fontSize: 18, fontWeight: 700, color: "#e5484d", mb: 1.25 }}>{title}</Typography>
      {children}
    </Box>
  );
}

/**
 * 复盘海报(1080 宽,深色):关键数字 + 今日方向 + 明日候选 + 核心矛盾。
 *
 * 数据全部复用现有 API,不新增后端接口。全部请求 settle 后在根节点打
 * data-poster-ready="1",供后端 Playwright 等待渲染就绪(失败也置位,避免无限等待)。
 */
export default function PosterView({ date }: { date: string }) {
  const [emotion, setEmotion] = useState<Emotion | null>(null);
  const [cands, setCands] = useState<Candidate[]>([]);
  const [themes, setThemes] = useState<ThemeRow[]>([]);
  const [conflict, setConflict] = useState("");
  const [boards, setBoards] = useState<Record<string, number>>({});
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!date) return;
    setReady(false);
    Promise.allSettled([
      getEmotion(date).then(setEmotion),
      getCandidates(date).then(setCands),
      getThemeHeat(date).then((t) => setThemes(t.slice(0, 3))),
      getReport(date).then((r) => setConflict(extractConflict(r.markdown))),
      getLadder(date).then((l) => {
        const map: Record<string, number> = {};
        Object.values(l).forEach((arr) => arr.forEach((s) => (map[s.code] = s.boards)));
        setBoards(map);
      }),
    ]).then(() => setReady(true)); // 单项失败不阻塞就绪:海报缺一块也要能出图
  }, [date]);

  const sorted = [...cands].sort(
    (a, b) => GRADE_ORDER.indexOf(a.grade || "D") - GRADE_ORDER.indexOf(b.grade || "D"),
  );

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
      {/* 头部 */}
      <Stack direction="row" alignItems="baseline" justifyContent="space-between">
        <Typography sx={{ fontSize: 30, fontWeight: 800 }}>
          打板复盘 · <span style={{ color: "#e5484d" }}>{fmtDate(date)}</span>
        </Typography>
        {emotion && (
          <Typography sx={{ fontSize: 17, color: "#f5a623", fontWeight: 700 }}>
            情绪:{emotion.phase_hint}
          </Typography>
        )}
      </Stack>
      {emotion?.market_state_hint && (
        <Typography sx={{ fontSize: 14, color: "#8b949e", mt: 0.5 }}>{emotion.market_state_hint}</Typography>
      )}

      {/* 情绪数字条 */}
      {emotion && (
        <Stack
          direction="row"
          sx={{ mt: 2.5, py: 2, borderTop: "1px solid #21262d", borderBottom: "1px solid #21262d" }}
        >
          <Stat label="涨停" value={String(emotion.zt_count)} color="#e5484d" />
          <Stat label="连板" value={String(emotion.lianban_count)} />
          <Stat label="最高板" value={`${emotion.max_board}板`} />
          <Stat
            label="炸板率"
            value={`${(emotion.break_rate * 100).toFixed(0)}%`}
            color={emotion.break_rate >= 0.4 ? "#e5484d" : undefined}
          />
          <Stat
            label="赚钱效应"
            value={emotion.money_effect == null ? "—" : `${emotion.money_effect > 0 ? "+" : ""}${emotion.money_effect}%`}
            color={(emotion.money_effect ?? 0) > 0 ? "#e5484d" : "#30a46c"}
          />
        </Stack>
      )}

      {/* 今日方向 */}
      {themes.length > 0 && (
        <Section title="今日方向(含板块涨幅)">
          <Stack spacing={1}>
            {themes.map((t, i) => (
              <Stack key={t.theme} direction="row" alignItems="center" spacing={1.5}>
                <Typography sx={{ fontSize: 17, color: "#8b949e", width: 24 }}>{i + 1}</Typography>
                <Typography sx={{ fontSize: 19, fontWeight: 700, minWidth: 168 }}>{t.theme}</Typography>
                {/* 板块强度(同花顺涨停板块榜涨幅);未匹配到板块留占位,保持各行对齐 */}
                <Typography
                  sx={{
                    fontSize: 17,
                    fontWeight: 800,
                    width: 76,
                    textAlign: "right",
                    color: t.pct == null ? "#484f58" : t.pct >= 0 ? "#e5484d" : "#30a46c",
                  }}
                >
                  {t.pct == null ? "—" : `${t.pct >= 0 ? "+" : ""}${t.pct.toFixed(2)}%`}
                </Typography>
                <Typography sx={{ fontSize: 15, color: "#8b949e", whiteSpace: "nowrap" }}>
                  涨停 {t.zt_count} · 连板 {t.lianban_count} · 最高 {t.max_board}板
                </Typography>
                <Typography sx={{ fontSize: 15, color: "#e6edf3", overflow: "hidden", whiteSpace: "nowrap" }}>
                  {t.stocks.slice(0, 3).map((s) => s.name).join("、")}
                </Typography>
              </Stack>
            ))}
          </Stack>
        </Section>
      )}

      {/* 明日候选 */}
      {sorted.length > 0 && (
        <Section title="明日候选">
          <Stack spacing={1.5}>
            {sorted.slice(0, 5).map((c, i) => (
              <Box key={`${c.code}-${i}`} sx={{ borderLeft: "4px solid", borderColor: GRADE_COLOR[c.grade] ?? "#30363d", pl: 1.5 }}>
                <Stack direction="row" alignItems="center" spacing={1.25}>
                  {c.grade && (
                    <Chip
                      label={c.grade}
                      size="small"
                      sx={{ bgcolor: GRADE_COLOR[c.grade], color: "#fff", fontWeight: 800, fontSize: 14, height: 24 }}
                    />
                  )}
                  <Typography sx={{ fontSize: 20, fontWeight: 700 }}>{c.name}</Typography>
                  {boards[c.code] ? (
                    <Typography sx={{ fontSize: 15, color: "#f5a623" }}>{boards[c.code]}板</Typography>
                  ) : null}
                  <Typography sx={{ fontSize: 14, color: "#8b949e" }}>{c.style}</Typography>
                  {c.position && (
                    <Typography sx={{ fontSize: 14, color: "#8b949e" }}>· {c.position}</Typography>
                  )}
                </Stack>
                {c.trigger && (
                  <Typography sx={{ fontSize: 15, color: "#30a46c", mt: 0.25 }}>进:{c.trigger}</Typography>
                )}
                {c.giveup && (
                  <Typography sx={{ fontSize: 15, color: "#e5484d" }}>弃:{c.giveup}</Typography>
                )}
              </Box>
            ))}
          </Stack>
        </Section>
      )}

      {/* 明日核心矛盾 */}
      {conflict && (
        <Section title="明日核心矛盾">
          <Typography sx={{ fontSize: 16, lineHeight: 1.7, whiteSpace: "pre-wrap", color: "#c9d1d9" }}>
            {conflict}
          </Typography>
        </Section>
      )}

      <Typography sx={{ fontSize: 12, color: "#484f58", mt: 3, textAlign: "center" }}>
        agent 推理复盘 · 条件判断非确定性结论 · 仅供个人复盘参考
      </Typography>
    </Box>
  );
}
