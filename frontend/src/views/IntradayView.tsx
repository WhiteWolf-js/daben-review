import { useState } from "react";
import { Button, Divider, Stack, Typography } from "@mui/material";
import PhotoCameraIcon from "@mui/icons-material/PhotoCamera";
import dayjs from "dayjs";
import type { Stock } from "../api";
import SectionedPage, { type PageSection } from "../components/base/SectionedPage";
import PanelCard from "../components/base/PanelCard";
import LiveBar from "../components/LiveBar";
import HoldingsList from "../components/HoldingsList";
import HoldingForm from "../components/HoldingForm";
import HoldingImportDialog from "../components/HoldingImportDialog";
import CandidatePanel from "../components/CandidatePanel";

/**
 * 盘中视图(9:30–15:00):盯情绪拐点 + 盯持仓。
 *
 * 实时条常显在顶部(自带事件流折叠),持仓/加仓/候选平铺成 section。
 * 不在这里跑任何 agent(一次 1-2 分钟,盘中等不了);持仓的止盈/止损来自盘后已生成的诊断。
 */
export default function IntradayView({
  prevDate,
  onPick,
}: {
  prevDate: string;
  onPick: (s: Stock) => void;
}) {
  const [holdingsVer, setHoldingsVer] = useState(0);
  const [importOpen, setImportOpen] = useState(false);
  // 截图导入按「今天」补买入板数与买入日(盘中买的就是今天的板);当日涨停池拉不到时后端降级为 0
  const today = dayjs().format("YYYYMMDD");

  const sections: PageSection[] = [
    {
      id: "holdings",
      label: "持仓实时",
      content: <HoldingsList reload={holdingsVer} onPick={(s) => onPick(s as Stock)} />,
    },
    {
      id: "add",
      label: "添加持仓",
      content: (
        <PanelCard title="添加持仓" hint="截图批量导入,或手动录一条">
          <Stack spacing={1.5}>
            <Stack direction="row" spacing={1.5} alignItems="center">
              <Button
                variant="outlined"
                size="small"
                startIcon={<PhotoCameraIcon />}
                onClick={() => setImportOpen(true)}
              >
                上传持仓截图
              </Button>
              <Typography variant="caption" color="text.secondary">
                识别后勾选要盯的票,成本价/股数可改
              </Typography>
            </Stack>
            <Divider flexItem>
              <Typography variant="caption" color="text.disabled">
                或手动录入
              </Typography>
            </Divider>
            <HoldingForm onAdded={() => setHoldingsVer((v) => v + 1)} />
          </Stack>
        </PanelCard>
      ),
    },
    {
      id: "candidates",
      label: "今日候选",
      content: (
        <CandidatePanel
          date={prevDate}
          reload={0}
          onPick={(s) => onPick(s as Stock)}
          title="今日候选(盘中可能触发)"
          subtitle="来自昨晚复盘"
          emptyHint="昨晚复盘没有产出候选。"
        />
      ),
    },
  ];

  return (
    <>
      <SectionedPage header={<LiveBar defaultEventsOpen />} sections={sections} />
      <HoldingImportDialog
        open={importOpen}
        date={today}
        onClose={() => setImportOpen(false)}
        onImported={() => setHoldingsVer((v) => v + 1)}
      />
    </>
  );
}
