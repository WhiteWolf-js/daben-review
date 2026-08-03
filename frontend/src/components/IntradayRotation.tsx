import { useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  Card,
  CardContent,
  CircularProgress,
  Stack,
  Tab,
  Tabs,
  Tooltip,
  Typography,
} from "@mui/material";
import * as echarts from "echarts";
import { getIntradayRotation, type IntradayRotation as Data, type RotationCurve, type Stock } from "../api";

const C = {
  up: "#e5484d",
  down: "#30a46c",
  warn: "#f5a623",
  blue: "#58a6ff",
  text: "#e6edf3",
  muted: "#8b949e",
  dim: "#6e7681",
  line: "#21262d",
  panel: "#161b22",
};

/** 形态 → 颜色。退潮方红(高位在派发)、接棒方绿(资金在进)—— 与涨跌红绿无关,是「谁在退谁在进」。 */
const SHAPE_TONE: Record<string, string> = {
  早盘冲高回落: C.up,
  冲高回落: C.up,
  盘中接棒: C.down,
  尾盘走强: C.down,
  全天平推: C.muted,
  全天弱: C.dim,
};

/**
 * 图里只给**首条切换配对**的两方上红绿(它们才是结论),其余一律取各自不同的中性色。
 * 一开始按 shape 上色,结果「盘中接棒/尾盘走强」三四个板块全是同一个绿,legend 里分不出谁是谁。
 */
const NEUTRAL = ["#58a6ff", "#a371f7", "#d29922", "#39c5cf", "#db6d28", "#8b949e", "#6e7681"];

function Pill({ children, color = C.muted, solid }: { children: React.ReactNode; color?: string; solid?: boolean }) {
  return (
    <Box
      component="span"
      sx={{
        fontSize: 11,
        fontWeight: 700,
        lineHeight: 1.7,
        px: 0.75,
        borderRadius: 0.5,
        whiteSpace: "nowrap",
        ...(solid ? { bgcolor: color, color: "#fff" } : { color, border: `1px solid ${color}55`, bgcolor: `${color}14` }),
      }}
    >
      {children}
    </Box>
  );
}

const sign = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(1)}`;

/**
 * 盘中情绪切换:板块分时均涨幅曲线 + 退潮/接棒配对 + 封板时序。
 *
 * 为什么需要:其余面板都是日终截面。收盘看起来一样强的两个板块,一个是早盘冲高回落的
 * 退潮方、一个是盘中接棒收在高位的进攻方,次日赔率完全相反 —— 只有时间轴看得出来。
 *
 * 曲线口径含**炸板池 + 昨日涨停**(后端 metrics/intraday_rotation.py 的铁律):
 * 只取涨停池是生存者偏差,每条线都会收在 +10% 平掉。
 */
export default function IntradayRotation({
  date,
  onPick,
}: {
  date: string;
  onPick?: (s: Stock) => void;
}) {
  const [d, setD] = useState<Data | null>(null);
  const [loading, setLoading] = useState(false);
  const [dim, setDim] = useState<"groups" | "industries">("groups");
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!date) return;
    setD(null);
    setLoading(true);
    getIntradayRotation(date)
      .then(setD)
      .catch(() => setD(null))
      .finally(() => setLoading(false));
  }, [date]);

  const rotations = dim === "groups" ? d?.group_rotations ?? [] : d?.rotations ?? [];

  /**
   * 行业口径有 20+ 条线会糊成一团,只画收盘最强的 8 条 —— 但**必须把切换配对涉及的板块并进来**:
   * 退潮方收盘本来就弱,按收盘取前 8 正好把它剔掉,于是切换表写着「半导体 10:00 见顶」而图上
   * 根本没有半导体的线,结论和图对不上(踩过)。
   */
  const curves = useMemo<RotationCurve[]>(() => {
    if (!d) return [];
    if (dim === "groups") return d.groups;
    const must = new Set(rotations.flatMap((r) => [r.fader, r.taker]));
    const top = d.industries.slice(0, 8);
    const extra = d.industries.filter((c) => must.has(c.name) && !top.includes(c));
    return [...top, ...extra];
  }, [d, dim, rotations]);

  // 首条配对的两方 = 当日结论,图里只给它俩红绿加粗
  const emphasis = useMemo<Record<string, string>>(() => {
    const r = rotations[0];
    return r ? { [r.fader]: C.up, [r.taker]: C.down } : {};
  }, [rotations]);

  useEffect(() => {
    const el = boxRef.current;
    if (!el || curves.length === 0) return;
    // 原生 echarts 手动 init/setOption/resize —— echarts-for-react 在 MUI 容器里会 stale 只画左半
    const chart = echarts.init(el);
    const times = curves[0].points.map((p) => p.t);
    let ni = 0;

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        // 按当前时点的强弱排序,一眼看出这一刻是谁在最上面
        formatter: (ps: { axisValue?: string; seriesName?: string; value?: number; color?: string }[]) => {
          const rows = [...ps]
            .sort((a, b) => (b.value ?? -99) - (a.value ?? -99))
            .map(
              (p) =>
                `<span style="color:${p.color}">●</span> ${p.seriesName} ` +
                `<b>${typeof p.value === "number" ? sign(p.value) : "—"}%</b>`,
            );
          return [`<b>${ps[0]?.axisValue ?? ""}</b>`, ...rows].join("<br/>");
        },
      },
      legend: {
        type: "scroll",
        top: 0,
        textStyle: { color: C.muted, fontSize: 11 },
        inactiveColor: C.line,
      },
      grid: { left: 44, right: 16, top: 34, bottom: 28 },
      xAxis: {
        type: "category",
        data: times,
        boundaryGap: false,
        axisLabel: { color: C.muted, fontSize: 10, interval: 1 },
        axisLine: { lineStyle: { color: C.line } },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: C.muted, fontSize: 10, formatter: "{value}%" },
        splitLine: { lineStyle: { color: C.line } },
      },
      series: curves.map((c) => {
        const hot = emphasis[c.name];
        const color = hot ?? NEUTRAL[ni++ % NEUTRAL.length];
        const strong = !!hot;
        return {
          name: `${c.name}(${c.count})`,
          type: "line",
          smooth: true,
          symbol: "none",
          lineStyle: { color, width: strong ? 2.5 : 1.2, opacity: strong ? 1 : 0.75 },
          itemStyle: { color },
          // 峰值打点:退潮方的顶就是当日情绪的高点
          markPoint: strong
            ? {
                symbolSize: 6,
                symbol: "circle",
                data: [{ coord: [c.peak_at, c.peak], itemStyle: { color } }],
                label: { show: false },
              }
            : undefined,
          data: c.points.map((p) => p.pct),
        };
      }),
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    requestAnimationFrame(() => chart.resize());
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [curves, emphasis]);

  const pick = (l: { code: string; name: string; boards: number; pct: number; first_seal: string; break_times: number }, industry: string) =>
    onPick?.({
      code: l.code, name: l.name, boards: l.boards, pct: l.pct,
      seal_strength: 0, first_seal: l.first_seal, break_times: l.break_times,
      turnover: 0, zt_stat: "", industry,
    } as Stock);

  return (
    <Card>
      <CardContent>
        <Stack direction="row" alignItems="center" justifyContent="space-between" flexWrap="wrap" useFlexGap>
          <Stack direction="row" alignItems="baseline" spacing={1} flexWrap="wrap" useFlexGap>
            <Typography variant="subtitle1" fontWeight={600}>
              盘中切换
            </Typography>
            {d && (
              <Typography variant="caption" color="text.secondary">
                口径 {d.universe} 只(涨停+炸板+昨日涨停)· 取到分时 {d.fetched} · 板块均涨幅,15 分钟采样
              </Typography>
            )}
          </Stack>
          <Tabs value={dim} onChange={(_, v) => setDim(v)} sx={{ minHeight: 32 }}>
            <Tab value="groups" label="大类" sx={{ minHeight: 32, py: 0 }} />
            <Tab value="industries" label="行业" sx={{ minHeight: 32, py: 0 }} />
          </Tabs>
        </Stack>

        {loading && (
          <Box sx={{ display: "flex", justifyContent: "center", alignItems: "center", py: 4, gap: 1.5 }}>
            <CircularProgress size={22} />
            <Typography variant="body2" color="text.secondary">
              首次算这一天要拉 200+ 只分时(约 15s),之后走缓存
            </Typography>
          </Box>
        )}

        {!loading && d && curves.length > 0 && (
          <>
            <Box ref={boxRef} sx={{ width: "100%", height: 300, mt: 1 }} />

            {/* 切换配对:左退潮 → 右接棒。方向就是结论,别反 */}
            {rotations.length > 0 && (
              <Stack spacing={1} sx={{ mt: 1.5 }}>
                {rotations.map((x, i) => (
                  <Box key={i} sx={{ border: `1px solid ${C.line}`, borderRadius: 1, p: 1.25 }}>
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      spacing={1}
                      alignItems={{ xs: "flex-start", sm: "center" }}
                    >
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography sx={{ fontSize: 13.5, fontWeight: 700, color: C.up }}>{x.fader}</Typography>
                        <Typography sx={{ fontSize: 11.5, color: C.muted }}>
                          {x.fader_peak_at} 见顶 {sign(x.fader_peak)}% → 收 {sign(x.fader_close)}% · 回落{" "}
                          {x.fader_fade.toFixed(1)}
                        </Typography>
                      </Box>
                      <Pill solid color={C.dim}>接棒 ▸</Pill>
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography sx={{ fontSize: 13.5, fontWeight: 700, color: C.down }}>{x.taker}</Typography>
                        <Typography sx={{ fontSize: 11.5, color: C.muted }}>
                          开盘 {sign(x.taker_open)}% → {x.taker_peak_at} 峰值 → 收 {sign(x.taker_close)}% · 涨{" "}
                          {sign(x.taker_rise)}
                        </Typography>
                      </Box>
                    </Stack>
                  </Box>
                ))}
              </Stack>
            )}

            {/* 每条曲线的读数 + 代表票(点开看分时) */}
            <Box sx={{ mt: 1.5, border: `1px solid ${C.line}`, borderRadius: 1, overflow: "hidden" }}>
              {curves.map((c, i) => (
                <Stack
                  key={c.name}
                  direction="row"
                  spacing={1}
                  alignItems="center"
                  flexWrap="wrap"
                  useFlexGap
                  sx={{ px: 1.5, py: 0.85, borderTop: i ? `1px solid ${C.line}` : "none" }}
                >
                  <Typography sx={{ fontSize: 13.5, fontWeight: 700, color: C.text, minWidth: 76 }}>
                    {c.name}
                  </Typography>
                  <Typography sx={{ fontSize: 11, color: C.dim }}>{c.count}只</Typography>
                  <Pill solid color={SHAPE_TONE[c.shape] ?? C.muted}>{c.shape}</Pill>
                  <Tooltip title="09:35 → 峰值@时点 → 收盘">
                    <Typography sx={{ fontSize: 12, color: C.muted }}>
                      {sign(c.open)} → <b style={{ color: C.text }}>{sign(c.peak)}</b>@{c.peak_at} → {sign(c.close)}
                    </Typography>
                  </Tooltip>
                  <Tooltip title="峰值−收盘,越大说明高位派发越重">
                    <Typography sx={{ fontSize: 12, color: c.fade >= 2 ? C.up : C.muted }}>
                      回落 {c.fade.toFixed(1)}
                    </Typography>
                  </Tooltip>
                  <Tooltip title="收盘−11:30,午后是谁在做">
                    <Typography sx={{ fontSize: 12, color: c.am_pm >= 0 ? C.down : C.up }}>
                      午后 {sign(c.am_pm)}
                    </Typography>
                  </Tooltip>
                  <Box sx={{ flexGrow: 1 }} />
                  <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                    {c.leaders.map((l) => (
                      <Typography
                        key={l.code}
                        onClick={() => pick(l, c.name)}
                        sx={{
                          fontSize: 12,
                          color: C.blue,
                          cursor: onPick ? "pointer" : "default",
                          "&:hover": onPick ? { textDecoration: "underline" } : undefined,
                        }}
                      >
                        {l.name} {sign(l.pct)}
                      </Typography>
                    ))}
                  </Stack>
                </Stack>
              ))}
            </Box>

            {/* 封板/炸板时序:纯本地零请求的另一路信号,与曲线互相印证 */}
            <SealTimeline rows={d.seal_timeline} />

            <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: "block" }}>
              曲线=板块内个股相对昨收涨幅的均值,口径含炸板池与昨日涨停(只取涨停池会全部收在
              +10%,看不到"跌下来"那一半)。回落大=高位派发,午后为正=资金在午后进。点代表票看分时。
            </Typography>
          </>
        )}

        {!loading && d && curves.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {date} 没有 ≥3 只票的板块,画不出曲线。
          </Typography>
        )}
        {!loading && !d && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            取不到 {date} 的盘中数据。
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

/** 封板 / 炸板时序条:每 30 分钟一格,上红=封板数、下绿=炸板数。看得出「几点是谁在封」。 */
function SealTimeline({ rows }: { rows: Data["seal_timeline"] }) {
  const max = Math.max(
    1,
    ...rows.flatMap((r) => [
      Object.values(r.sealed).reduce((a, b) => a + b, 0),
      Object.values(r.broken).reduce((a, b) => a + b, 0),
    ]),
  );
  const total = (m: Record<string, number>) => Object.values(m).reduce((a, b) => a + b, 0);
  const detail = (m: Record<string, number>) =>
    Object.entries(m)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k} ${v}`)
      .join(" · ") || "无";

  return (
    <Box sx={{ mt: 1.5 }}>
      <Typography sx={{ fontSize: 11.5, color: C.dim, mb: 0.5 }}>
        封板(红)/ 炸板(绿)时序 · 每 30 分钟
      </Typography>
      <Stack direction="row" spacing={0.5} alignItems="stretch">
        {rows.map((r) => {
          const s = total(r.sealed);
          const b = total(r.broken);
          return (
            <Tooltip key={r.t} title={`${r.t} 前\n封 ${s}:${detail(r.sealed)}\n炸 ${b}:${detail(r.broken)}`}>
              <Box sx={{ flex: 1, minWidth: 0, textAlign: "center", px: "2px" }}>
                <Box sx={{ height: 34, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>
                  <Box sx={{ height: `${(s / max) * 100}%`, bgcolor: C.up, borderRadius: "2px 2px 0 0" }} />
                </Box>
                {/* 基线:封/炸都顶满时(如 0731 的 10:00 桶 封26+炸55)没这条线就是一整块,分不出红绿界 */}
                <Box sx={{ height: "1px", bgcolor: C.dim }} />
                <Box sx={{ height: 34 }}>
                  <Box sx={{ height: `${(b / max) * 100}%`, bgcolor: C.down, borderRadius: "0 0 2px 2px" }} />
                </Box>
                <Typography sx={{ fontSize: 9.5, color: C.dim }}>{r.t.slice(0, 5)}</Typography>
              </Box>
            </Tooltip>
          );
        })}
      </Stack>
    </Box>
  );
}
