import { useEffect, useRef } from "react";
import { Card, CardContent, Typography } from "@mui/material";
import * as echarts from "echarts";
import type { SeriesPoint } from "../api";

// 原生 echarts init/setOption/resize(本仓库 echarts-for-react 有渲染问题,见交接铁律#4)
export default function EmotionTrend({ series }: { series: SeriesPoint[] }) {
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (!el || series.length === 0) return;
    const chart = echarts.init(el);
    const dates = series.map((p) => p.date.slice(4)); // MMDD
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: {
        data: ["涨停数", "最高板", "总晋级率", "炸板率"],
        textStyle: { color: "#8b949e" },
        top: 0,
      },
      grid: { left: 40, right: 44, top: 30, bottom: 32 },
      xAxis: { type: "category", data: dates, axisLabel: { color: "#8b949e" } },
      yAxis: [
        {
          type: "value",
          min: 0,
          axisLabel: { color: "#8b949e" },
          splitLine: { lineStyle: { color: "rgba(255,255,255,0.06)" } },
        },
        {
          type: "value",
          min: 0,
          max: 1,
          axisLabel: { color: "#8b949e", formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "涨停数",
          type: "bar",
          barMaxWidth: 40,
          data: series.map((p) => p.zt_count),
          itemStyle: { color: "rgba(229,72,77,0.55)" },
        },
        { name: "最高板", type: "line", data: series.map((p) => p.max_board), smooth: true, showSymbol: true, itemStyle: { color: "#f5a623" } },
        { name: "总晋级率", type: "line", yAxisIndex: 1, data: series.map((p) => p.promo_overall), smooth: true, showSymbol: true, itemStyle: { color: "#30a46c" } },
        { name: "炸板率", type: "line", yAxisIndex: 1, data: series.map((p) => p.break_rate), smooth: true, showSymbol: true, itemStyle: { color: "#8b949e" } },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    const raf = requestAnimationFrame(() => chart.resize());
    return () => {
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(raf); // 否则 dispose 后回调还去 resize 已销毁实例(控制台刷警告)
      chart.dispose();
    };
  }, [series]);

  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1 }}>
          情绪周期趋势
        </Typography>
        {series.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            暂无历史序列(累积多日后显示)
          </Typography>
        ) : (
          <div ref={boxRef} style={{ height: 264, width: "100%" }} />
        )}
      </CardContent>
    </Card>
  );
}
