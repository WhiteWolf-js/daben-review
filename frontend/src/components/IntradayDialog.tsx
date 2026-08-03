import { useEffect, useRef, useState } from "react";
import {
  Box,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import * as echarts from "echarts";
import { getIntraday, type Intraday, type Stock } from "../api";

const yi = (v: number | null | undefined) => (v == null ? "—" : `${(v / 1e8).toFixed(2)}亿`);
/** HHMMSS / HH:MM:SS → HH:MM */
const hhmm = (s: string | undefined) => {
  const d = String(s || "").replace(/\D/g, "");
  return d.length >= 4 ? `${d.slice(0, 2)}:${d.slice(2, 4)}` : "";
};
/** 封流比分档:打板圈口径(本地回测对隔日溢价严格单调),≥3% 超强、2-3% 强、1-2% 中、<1% 弱 */
const sealTier = (s: number) =>
  s >= 0.03
    ? { label: "超强封", color: "error" as const }
    : s >= 0.02
      ? { label: "强封", color: "warning" as const }
      : s >= 0.01
        ? { label: "中封", color: "primary" as const }
        : { label: "弱封", color: "default" as const };

export default function IntradayDialog({
  stock,
  date,
  onClose,
}: {
  stock: Stock | null;
  date: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<Intraday | null>(null);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!stock || !date) return;
    setData(null);
    setLoading(true);
    getIntraday(stock.code, date)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [stock, date]);

  useEffect(() => {
    const el = boxRef.current;
    if (!el || !data || data.points.length === 0) return;
    const chart = echarts.init(el);
    const times = data.points.map((p) => p.t);
    const closes = data.points.map((p) => p.c);
    const vols = data.points.map((p) => p.v);
    const maxVol = vols.length ? Math.max(...vols) : 1;
    const prev = data.prev_close ?? undefined;

    // 价格轴以昨收为中心上下对称(行情软件的标准画法):这样昨收线居中、涨跌视觉对称,
    // 右侧的涨幅刻度才能和左侧价格刻度一一对应。范围取当日最大偏离 ×1.15 留白,
    // 下限 ±1%(平开票不至于把线压成一条),上限 ±22%(容得下 20cm 票)。
    const maxDev = prev
      ? Math.min(Math.max(...closes.map((c) => Math.abs(c / prev - 1)), 0.01) * 1.15, 0.22)
      : 0;
    const priceMin = prev ? prev * (1 - maxDev) : undefined;
    const priceMax = prev ? prev * (1 + maxDev) : undefined;
    const pctLimit = +(maxDev * 100).toFixed(2);
    const pctOf = (v: number) => (prev ? (v / prev - 1) * 100 : null);
    const up = prev ? (closes[closes.length - 1] ?? prev) >= prev : true;
    const lineColor = up ? "#e5484d" : "#30a46c";

    // 首封时刻在分时序列里的位置(时间点可能不完全对齐,取第一个 ≥ 首封时间的点)
    const sealHM = hhmm(data.profile?.first_seal);
    const sealIdx = sealHM
      ? times.findIndex((t) => String(t).replace(/\D/g, "").slice(0, 4) >= sealHM.replace(":", ""))
      : -1;

    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        // 价格旁边直接带涨幅,免得心算
        formatter: (ps: { axisValue?: string; seriesType?: string; value?: number }[]) => {
          const price = ps.find((p) => p.seriesType === "line")?.value;
          const vol = ps.find((p) => p.seriesType === "bar")?.value;
          const pct = typeof price === "number" ? pctOf(price) : null;
          const pctTxt =
            pct == null
              ? ""
              : `<span style="color:${pct >= 0 ? "#e5484d" : "#30a46c"}">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</span>`;
          return [
            ps[0]?.axisValue ?? "",
            `价 ${typeof price === "number" ? price.toFixed(2) : "—"} ${pctTxt}`,
            `量 ${typeof vol === "number" ? vol.toLocaleString() : "—"}`,
          ].join("<br/>");
        },
      },
      grid: { left: 52, right: 54, top: 20, bottom: 36 },
      xAxis: {
        type: "category",
        data: times,
        boundaryGap: false,
        axisLabel: { color: "#8b949e", interval: Math.max(0, Math.floor(times.length / 6)) },
      },
      yAxis: [
        {
          type: "value",
          scale: !prev, // 有昨收就用上面算好的对称范围,没有才让 echarts 自适应
          min: priceMin,
          max: priceMax,
          // 与右侧涨幅轴共用 4 等分,两边刻度一一对齐(否则左右格线错位、对不上)
          splitNumber: prev ? 4 : undefined,
          interval: prev ? (priceMax! - priceMin!) / 4 : undefined,
          axisLabel: { color: "#8b949e", formatter: (v: number) => v.toFixed(2) },
          splitLine: { lineStyle: { color: "rgba(255,255,255,0.06)" } },
        },
        { type: "value", max: maxVol * 4, axisLabel: { show: false }, splitLine: { show: false } },
        // 右轴:涨幅%。与左轴同为「以昨收为中心的对称区间」,故两侧刻度天然对齐
        {
          type: "value",
          min: prev ? -pctLimit : undefined,
          max: prev ? pctLimit : undefined,
          splitNumber: prev ? 4 : undefined,
          interval: prev ? pctLimit / 2 : undefined, // 与左轴同 4 等分:-L, -L/2, 0, +L/2, +L
          position: "right",
          axisLabel: {
            color: "#8b949e",
            formatter: (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`,
          },
          splitLine: { show: false },
        },
      ],
      series: [
        { type: "bar", data: vols, yAxisIndex: 1, itemStyle: { color: "rgba(139,148,158,0.35)" } },
        {
          type: "line",
          data: closes,
          yAxisIndex: 0,
          showSymbol: false,
          lineStyle: { color: lineColor, width: 1.5 },
          areaStyle: { color: up ? "rgba(229,72,77,0.08)" : "rgba(48,164,108,0.08)" },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: "#8b949e", type: "dashed" },
            data: [
              ...(prev
                ? [
                    {
                      yAxis: prev,
                      // 标签贴左上:默认在右端会压住右侧涨幅轴的 0% 刻度,两个标签糊成一团
                      label: {
                        formatter: `昨收 ${prev}`,
                        color: "#8b949e",
                        position: "insideStartTop" as const,
                      },
                    },
                  ]
                : []),
              // 首封竖线:封板之后是锁死还是反复开板,是判断封单质量的关键
              ...(sealIdx >= 0
                ? [
                    {
                      xAxis: times[sealIdx],
                      lineStyle: { color: "#f5a524", type: "dotted" as const },
                      label: {
                        formatter: `首封 ${hhmm(data.profile?.first_seal)}`,
                        color: "#f5a524",
                        position: "insideEndTop" as const,
                      },
                    },
                  ]
                : []),
            ],
          },
        },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    requestAnimationFrame(() => chart.resize());
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [data]);

  const hasChart = !loading && data && data.points.length > 0;

  const p = data?.profile ?? null;
  // 标题栏直接给收盘价与涨幅(图上要找末端点,不如直接写出来)
  const lastPrice = data?.points.length ? data.points[data.points.length - 1].c : null;
  const lastPct =
    lastPrice != null && data?.prev_close ? (lastPrice / data.prev_close - 1) * 100 : null;

  return (
    <Dialog open={!!stock} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ pb: 0 }}>
        {stock?.name}{" "}
        <Typography component="span" color="text.secondary">
          {stock?.code}
          {stock?.boards ? ` · ${stock.boards}板` : ""}
          {stock?.industry ? ` · ${stock.industry}` : ""}
        </Typography>
        {lastPrice != null && (
          <Typography
            component="span"
            sx={{
              ml: 1.5,
              fontWeight: 700,
              color: lastPct == null ? "text.primary" : lastPct >= 0 ? "error.main" : "success.main",
            }}
          >
            {lastPrice.toFixed(2)}
            {lastPct != null && ` ${lastPct >= 0 ? "+" : ""}${lastPct.toFixed(2)}%`}
          </Typography>
        )}
        {data?.prev_close != null && (
          <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
            昨收 {data.prev_close}
          </Typography>
        )}

        {/* 资金强弱:封流比定档 + 封单金额/首末封/炸板/换手/成交额。看分时不能只看形态,
            一字板但封单只有 0.3% 和封单 3% 是两回事 */}
        {p && (
          <Stack direction="row" spacing={0.75} sx={{ mt: 1, mb: 0.5 }} flexWrap="wrap" useFlexGap>
            {p.seal_strength != null ? (
              <Tooltip title="封流比 = 封板资金 / 流通市值。本地回测对隔日溢价严格单调:≥3% 超强、2–3% 强、1–2% 中、<1% 弱">
                <Chip
                  size="small"
                  color={sealTier(p.seal_strength).color}
                  label={`${sealTier(p.seal_strength).label} 封流比 ${(p.seal_strength * 100).toFixed(2)}%`}
                  sx={{ height: 22, fontWeight: 700 }}
                />
              </Tooltip>
            ) : (
              <Chip size="small" variant="outlined" label="炸板未封 · 无封单" sx={{ height: 22 }} />
            )}
            {p.seal_amount != null && (
              <Tooltip title="封板资金(尾盘封单金额)">
                <Chip size="small" variant="outlined" label={`封单 ${yi(p.seal_amount)}`} sx={{ height: 22 }} />
              </Tooltip>
            )}
            {p.first_seal && (
              <Tooltip title="首次封板时间。≤9:45 封住的隔日溢价最高;午后才封多是跟风">
                <Chip size="small" variant="outlined" label={`首封 ${hhmm(p.first_seal)}`} sx={{ height: 22 }} />
              </Tooltip>
            )}
            {p.last_seal && hhmm(p.last_seal) !== hhmm(p.first_seal) && (
              <Tooltip title="最终封板时间(与首封不同说明中间开过板)">
                <Chip size="small" variant="outlined" label={`末封 ${hhmm(p.last_seal)}`} sx={{ height: 22 }} />
              </Tooltip>
            )}
            <Chip
              size="small"
              variant="outlined"
              color={p.break_times >= 3 ? "warning" : "default"}
              label={p.break_times ? `炸板 ${p.break_times} 次` : "全程未炸"}
              sx={{ height: 22 }}
            />
            {p.turnover != null && (
              <Tooltip title="换手率:越低越锁筹(<5% 隔日溢价最高),>15% 筹码涣散">
                <Chip size="small" variant="outlined" label={`换手 ${p.turnover.toFixed(1)}%`} sx={{ height: 22 }} />
              </Tooltip>
            )}
            {p.amount != null && (
              <Chip size="small" variant="outlined" label={`成交 ${yi(p.amount)}`} sx={{ height: 22 }} />
            )}
            {p.zt_stat && (
              <Tooltip title="涨停统计(N 天 M 板)">
                <Chip size="small" variant="outlined" label={p.zt_stat} sx={{ height: 22 }} />
              </Tooltip>
            )}
          </Stack>
        )}
      </DialogTitle>
      <DialogContent>
        {loading && (
          <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
            <CircularProgress size={28} />
          </Box>
        )}
        {!loading && data && data.points.length === 0 && (
          <Typography color="text.secondary" sx={{ py: 4 }}>
            无分时数据(可能非交易日或数据源暂无)
          </Typography>
        )}
        <Box ref={boxRef} sx={{ height: 380, width: "100%", display: hasChart ? "block" : "none" }} />
      </DialogContent>
    </Dialog>
  );
}
