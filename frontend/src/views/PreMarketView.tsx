import { useEffect, useState } from "react";
import { Card, CardContent, Typography } from "@mui/material";
import { getAuctionBrief, type Stock } from "../api";
import SectionedPage, { type PageSection } from "../components/base/SectionedPage";
import PanelCard from "../components/base/PanelCard";
import AuctionPanel from "../components/AuctionPanel";
import CandidatePanel from "../components/CandidatePanel";
import ReportBody from "../components/ReportBody";
import { useReport } from "../hooks/useReport";

/**
 * 盘前视图(<9:30):今天要打什么 + 竞价验证。
 *
 * 平铺成 section + 吸顶锚点:作战清单(昨晚候选,含进/弃条件)→ 竞价决策台 → agent 盘前解读 → 昨日正文。
 * prevDate = 上一交易日(候选与复盘都属于那天),由父级从 auction-live.base_date 或 dates[0] 给。
 */
export default function PreMarketView({
  prevDate,
  onPick,
}: {
  prevDate: string;
  onPick: (s: Stock) => void;
}) {
  const [brief, setBrief] = useState("");
  const { md, loading } = useReport(prevDate);

  useEffect(() => {
    getAuctionBrief()
      .then((b) => setBrief(b.brief ?? ""))
      .catch(() => setBrief(""));
  }, []);

  const sections: PageSection[] = [
    {
      id: "checklist",
      label: "作战清单",
      content: (
        <CandidatePanel
          date={prevDate}
          reload={0}
          onPick={(s) => onPick(s as Stock)}
          title="今日作战清单"
          // 说清「昨晚的复盘给今天用」,只写「来自 20260728」会被读成清单过期了
          subtitle={`${prevDate || "上一交易日"} 收盘后复盘产出、给今天打的 · 满足「进」才动手,触发「弃」就放掉`}
          emptyHint={`${prevDate || "上一交易日"} 的复盘没有产出候选(或尚未生成复盘)。可在盘后视图生成。`}
        />
      ),
    },
    {
      id: "auction",
      label: "竞价决策台",
      // 内部仍保留个股榜的折叠(几十行明细,常开会淹没方向判断)
      content: <AuctionPanel onPick={(s) => onPick(s as Stock)} />,
    },
    ...(brief
      ? [
          {
            id: "brief",
            label: "盘前解读",
            content: (
              <Card>
                <CardContent>
                  <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
                    agent 盘前解读
                  </Typography>
                  <Typography sx={{ fontSize: 14, lineHeight: 1.75, whiteSpace: "pre-wrap" }}>{brief}</Typography>
                </CardContent>
              </Card>
            ),
          },
        ]
      : []),
    {
      id: "report",
      label: "昨日正文",
      content: (
        <PanelCard title="昨日复盘正文" hint={md ? "含方向拆解与属性归因" : "未生成"}>
          {md ? (
            <ReportBody md={md} loading={loading} date={prevDate} />
          ) : (
            <Typography variant="body2" color="text.secondary">
              {prevDate} 尚未生成复盘。
            </Typography>
          )}
        </PanelCard>
      ),
    },
  ];

  return <SectionedPage sections={sections} />;
}
