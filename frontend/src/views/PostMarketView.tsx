import { Box, Typography } from "@mui/material";
import type { Emotion, Ladder, SeriesPoint, Stock } from "../api";
import SectionedPage, { type PageSection } from "../components/base/SectionedPage";
import PanelCard from "../components/base/PanelCard";
import EmotionPanel from "../components/EmotionPanel";
import EmotionTrend from "../components/EmotionTrend";
import ThemePanel from "../components/ThemePanel";
import LadderView from "../components/LadderView";
import IntradayRotation from "../components/IntradayRotation";
import CandidatePanel from "../components/CandidatePanel";
import ReportSummary from "../components/ReportSummary";
import ReportBody from "../components/ReportBody";
import HoldingAnalysis from "../components/HoldingAnalysis";
import { useReport } from "../hooks/useReport";

/**
 * 盘后视图(≥15:00):复盘今天 + 定明天。
 *
 * 顶部常显情绪 5 指标(涨停/最高板/炸板率/赚钱效应/1进2),其余内容平铺成 section,
 * 靠吸顶锚点条跳转;复盘状态由 useReport 统一持有(别在子组件各自持有,会双请求+不同步)。
 */
export default function PostMarketView({
  date,
  emotion,
  ladder,
  series,
  refreshKey,
  reportVer,
  onReportGenerated,
  onCostChanged,
  onPick,
}: {
  date: string;
  emotion: Emotion | null;
  ladder: Ladder | null;
  series: SeriesPoint[];
  refreshKey: number;
  reportVer: number;
  onReportGenerated: () => void;
  onCostChanged: () => void;
  onPick: (s: Stock) => void;
}) {
  const { md, createdAt, loading, usage, generate } = useReport(date, onReportGenerated);
  const maxBoard = ladder && Object.keys(ladder).length ? Math.max(...Object.keys(ladder).map(Number)) : 0;

  const sections: PageSection[] = [
    {
      id: "conflict",
      label: "核心矛盾",
      content: (
        <ReportSummary
          date={date}
          md={md}
          createdAt={createdAt}
          loading={loading}
          usage={usage}
          onGenerate={generate}
        />
      ),
    },
    {
      id: "candidates",
      label: "明日候选",
      content: (
        <CandidatePanel
          date={date}
          reload={reportVer}
          onPick={(s) => onPick(s as Stock)}
          title="明日候选票"
          subtitle="agent 产出 + 规则分级(A+~D)"
        />
      ),
    },
    ...(emotion
      ? [
          {
            id: "metrics",
            label: "情绪指标",
            content: (
              <PanelCard title="情绪完整指标" hint="封板率 / 晋级率 / 跌停等">
                <EmotionPanel e={emotion} />
              </PanelCard>
            ),
          },
        ]
      : []),
    {
      id: "trend",
      label: "情绪趋势",
      content: <EmotionTrend series={series} />,
    },
    {
      id: "theme",
      label: "题材热度",
      content: <ThemePanel date={date} reload={refreshKey} onPick={(s) => onPick(s as Stock)} />,
    },
    {
      // 日内时间轴:收盘一样强的两个板块,退潮方与接棒方赔率相反,截面看不出
      id: "rotation",
      label: "盘中切换",
      content: <IntradayRotation date={date} onPick={onPick} />,
    },
    {
      // LadderView 自己拉 ladder-board(含断板票);ladder prop 仅用于 section 标签上的最高板
      id: "ladder",
      label: `连板天梯${maxBoard ? `(最高${maxBoard}板)` : ""}`,
      content: <LadderView date={date} onPick={onPick} />,
    },
    {
      id: "report",
      label: "复盘正文",
      content: (
        <PanelCard title="完整复盘正文" hint={md ? "五段结构化解析" : "未生成"}>
          {md ? (
            <ReportBody md={md} loading={loading} date={date} />
          ) : (
            <Typography variant="body2" color="text.secondary">
              尚未生成复盘。
            </Typography>
          )}
        </PanelCard>
      ),
    },
    {
      id: "holding",
      label: "持仓诊断",
      content: (
        <PanelCard title="持仓 agent 诊断" hint="T+1 走势与买卖点">
          <HoldingAnalysis date={date} onAnalyzed={onCostChanged} />
        </PanelCard>
      ),
    },
  ];

  return (
    <SectionedPage
      header={
        <Box sx={{ mb: 2 }}>
          {emotion ? (
            <EmotionPanel e={emotion} compact />
          ) : (
            <Typography variant="body2" color="text.secondary">
              {date} 无涨停池数据。
            </Typography>
          )}
        </Box>
      }
      sections={sections}
    />
  );
}
