import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AppBar,
  Badge,
  Box,
  Button,
  CircularProgress,
  Container,
  IconButton,
  Link,
  Tab,
  Tabs,
  Toolbar,
  Tooltip,
  Typography,
} from "@mui/material";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import dayjs from "dayjs";
import ChatIcon from "@mui/icons-material/Chat";
import RefreshIcon from "@mui/icons-material/Refresh";
import {
  getDates,
  getEmotion,
  getLadder,
  getLive,
  getSeries,
  getUsageToday,
  refreshDay,
  type Emotion,
  type Ladder,
  type SeriesPoint,
  type Stock,
  type UsageToday,
} from "./api";
import ChatDrawer from "./components/ChatDrawer";
import IntradayDialog from "./components/IntradayDialog";
import PreMarketView from "./views/PreMarketView";
import IntradayView from "./views/IntradayView";
import PostMarketView from "./views/PostMarketView";
import { getTradePhase, PHASE_LABEL, type TradePhase } from "./utils/phase";

// 页脚文档链接。内网地址走 .env.local,不硬编码(仓库是公开的)
const DOC_URL = import.meta.env.VITE_DOC_URL;

const fmt = (d: string) => (d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : d);
const PHASES: TradePhase[] = ["pre", "intraday", "post"];
const today = () => dayjs().format("YYYYMMDD");

export default function App() {
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState(""); // 盘后视图看的日期(盘前/盘中固定今天)
  const [phase, setPhase] = useState<TradePhase>(() => getTradePhase());
  const [pinned, setPinned] = useState(false); // 用户手动切过 tab 后不再按时钟自动跳
  const [emotion, setEmotion] = useState<Emotion | null>(null);
  const [ladder, setLadder] = useState<Ladder | null>(null);
  const [series, setSeries] = useState<SeriesPoint[]>([]);
  const [chatOpen, setChatOpen] = useState(false);
  const [selected, setSelected] = useState<Stock | null>(null);
  const [reportVer, setReportVer] = useState(0); // 复盘重新生成后 +1,触发候选表刷新
  const [refreshKey, setRefreshKey] = useState(0); // 刷新盘面数据(题材等)
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefresh, setLastRefresh] = useState("");
  const [usageToday, setUsageToday] = useState<UsageToday | null>(null);
  const [liveEvents, setLiveEvents] = useState(0); // 盘中 tab 的事件数 badge

  const refreshUsage = useCallback(() => {
    getUsageToday().then(setUsageToday).catch(() => {});
  }, []);

  useEffect(() => {
    getDates().then((ds) => {
      setDates(ds);
      if (ds[0]) setDate(ds[0]);
    });
    getSeries().then(setSeries).catch(() => {});
    refreshUsage();
  }, [refreshUsage]);

  // 跨时段(如盘中→盘后)自动切视图;用户手动切过就不抢
  useEffect(() => {
    if (pinned) return;
    const id = setInterval(() => setPhase(getTradePhase()), 60_000);
    return () => clearInterval(id);
  }, [pinned]);

  // 盘中事件数(给 tab 挂 badge,不在盘中视图也能看到有拐点发生)
  useEffect(() => {
    const tick = () =>
      getLive()
        .then((l) => setLiveEvents(l.running ? l.events.length : 0))
        .catch(() => {});
    tick();
    const id = setInterval(tick, 30_000);
    return () => clearInterval(id);
  }, []);

  // 盘后视图的数据(情绪/天梯)跟随所选日期
  useEffect(() => {
    if (!date) return;
    setEmotion(null);
    setLadder(null);
    getEmotion(date).then(setEmotion).catch(() => setEmotion(null));
    getLadder(date).then(setLadder).catch(() => setLadder(null));
  }, [date, refreshKey]);

  /** 盘前/盘中要的「上一交易日」:当日池盘前还没入库,dates[0] 天然是上一交易日;
   *  收盘后 dates[0] 变成今天,此时取第二个。 */
  const prevDate = useMemo(() => {
    if (!dates.length) return "";
    return dates[0] === today() ? dates[1] ?? dates[0] : dates[0];
  }, [dates]);

  const doRefresh = async () => {
    const d = phase === "post" ? date : today();
    if (!d || refreshing) return;
    setRefreshing(true);
    try {
      await refreshDay(d);
    } catch {
      /* 拉取失败沿用旧数据 */
    }
    getSeries().then(setSeries).catch(() => {});
    setRefreshKey((k) => k + 1);
    setLastRefresh(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    setRefreshing(false);
  };

  const pickPhase = (p: TradePhase) => {
    setPhase(p);
    setPinned(true);
  };

  return (
    <>
      <AppBar position="sticky" color="default" elevation={0} sx={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
        <Toolbar variant="dense">
          <Typography variant="h6" sx={{ fontWeight: 700, mr: 2 }}>
            打板情绪复盘
          </Typography>
          <Tabs value={phase} onChange={(_, v) => pickPhase(v)} sx={{ flexGrow: 1, minHeight: 36 }}>
            {PHASES.map((p) => (
              <Tab
                key={p}
                value={p}
                sx={{ minHeight: 36 }}
                label={
                  p === "intraday" && liveEvents > 0 ? (
                    <Badge badgeContent={liveEvents} color="error" sx={{ "& .MuiBadge-badge": { right: -12, top: 2 } }}>
                      {PHASE_LABEL[p]}
                    </Badge>
                  ) : (
                    PHASE_LABEL[p]
                  )
                }
              />
            ))}
          </Tabs>

          {/* 日期选择器只在盘后有意义(盘前/盘中固定今天,避免"选了历史日期但实时条还是今天"的割裂) */}
          {phase === "post" && (
            <DatePicker
              value={date ? dayjs(fmt(date)) : null}
              onChange={(v) => v && setDate(v.format("YYYYMMDD"))}
              shouldDisableDate={(d) => !dates.includes(d.format("YYYYMMDD"))}
              minDate={dates.length ? dayjs(fmt(dates[dates.length - 1])) : undefined}
              maxDate={dates.length ? dayjs(fmt(dates[0])) : undefined}
              format="YYYY-MM-DD"
              slotProps={{ textField: { size: "small", sx: { width: 172, mr: 1 } } }}
            />
          )}
          <Tooltip title={lastRefresh ? `上次更新 ${lastRefresh}` : "强制重拉当日数据"}>
            <span>
              <IconButton size="small" onClick={doRefresh} disabled={refreshing} sx={{ mr: 0.5 }}>
                {refreshing ? <CircularProgress size={18} /> : <RefreshIcon fontSize="small" />}
              </IconButton>
            </span>
          </Tooltip>
          <Button startIcon={<ChatIcon />} onClick={() => setChatOpen(true)} disabled={!date}>
            追问
          </Button>
        </Toolbar>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 2 }}>
        {usageToday && usageToday.count > 0 && (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
            今日 AI 成本约 ¥{usageToday.cost_cny.toFixed(2)} · {usageToday.count} 次 ·{" "}
            {(usageToday.total_tokens / 1000).toFixed(0)}k tokens
          </Typography>
        )}

        <Box>
          {phase === "pre" && <PreMarketView prevDate={prevDate} onPick={setSelected} />}
          {phase === "intraday" && <IntradayView prevDate={prevDate} onPick={setSelected} />}
          {phase === "post" && (
            <PostMarketView
              date={date}
              emotion={emotion}
              ladder={ladder}
              series={series}
              refreshKey={refreshKey}
              reportVer={reportVer}
              onReportGenerated={() => {
                setReportVer((v) => v + 1);
                refreshUsage();
              }}
              onCostChanged={refreshUsage}
              onPick={setSelected}
            />
          )}
        </Box>

        {/* 页脚。文档链接走 VITE_DOC_URL(配在 .env.local,不进仓库)——
            那是内网文档地址,硬编码进代码会随仓库公开出去;未配置就只显示标题行。 */}
        <Box
          sx={{
            mt: 4,
            pt: 2,
            borderTop: "1px solid rgba(255,255,255,0.08)",
            display: "flex",
            justifyContent: "center",
            gap: 1,
            flexWrap: "wrap",
          }}
        >
          <Typography variant="caption" color="text.secondary">
            打板情绪复盘系统 · 仅供个人复盘参考
          </Typography>
          {DOC_URL && (
            <>
              <Typography variant="caption" color="text.secondary">
                ·
              </Typography>
              <Link href={DOC_URL} target="_blank" rel="noreferrer" variant="caption" underline="hover">
                项目总文档
              </Link>
            </>
          )}
        </Box>
      </Container>

      <ChatDrawer date={phase === "post" ? date : prevDate} open={chatOpen} onClose={() => setChatOpen(false)} />
      <IntradayDialog stock={selected} date={phase === "post" ? date : today()} onClose={() => setSelected(null)} />
    </>
  );
}
