import { useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  FormControlLabel,
  Stack,
  Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ImageIcon from "@mui/icons-material/Image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getHoldingAnalysis,
  getHoldings,
  streamSSE,
  type Holding,
  type HoldingVerdict,
  type UsageCost,
} from "../api";
import HoldingBoard, { type BoardRow } from "./HoldingBoard";
import HoldingPoster, { HOLDING_WIDTH } from "./HoldingPoster";
import { usePosterExport } from "../hooks/usePosterExport";

const mdSx = {
  "& h1,& h2": { fontSize: 15, mt: 1.5, mb: 0.5, color: "primary.main" },
  "& h3": { fontSize: 13, mt: 1, mb: 0.5 },
  "& table": { borderCollapse: "collapse", width: "100%", my: 1, fontSize: 12 },
  "& th,& td": { border: "1px solid rgba(255,255,255,0.12)", p: "4px 8px" },
  "& code": { bgcolor: "rgba(255,255,255,0.08)", px: 0.5, borderRadius: 0.5 },
  "& pre": { display: "none" }, // 尾部 json 块不展示
};

/**
 * 持仓 agent 诊断(盘后):走势判断 + T+1/波段 + 买卖点,**支持多选一起分析**。
 *
 * 多只一起跑比逐只跑更省(大盘情绪/题材/热门票 K 线只拉一次)、也更有用 ——
 * agent 会额外给「处置优先级」和同质化风险,明天开盘只来得及动一两笔时知道先砍谁。
 * 跑一次 1-2 分钟,故只在盘后做;结果落库后盘中 HoldingsList 直接读止盈/止损。
 */
export default function HoldingAnalysis({ date, onAnalyzed }: { date: string; onAnalyzed?: () => void }) {
  const [rows, setRows] = useState<Holding[]>([]);
  const [sel, setSel] = useState<string[]>([]);
  const [md, setMd] = useState("");
  const [verdicts, setVerdicts] = useState<Record<string, HoldingVerdict>>({});
  const [usage, setUsage] = useState<UsageCost | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [posterOpen, setPosterOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const { ref, exporting, download } = usePosterExport(`持仓处置_${date}.png`);

  useEffect(() => {
    getHoldings()
      .then((hs) => {
        setRows(hs);
        setSel(hs.map((h) => h.code)); // 默认全选:持仓通常就 3-5 只,一次看完最省事
      })
      .catch(() => setRows([]));
    return () => abortRef.current?.abort();
  }, []);

  /** 拉选中持仓已存的历史诊断(多票分析时每只都存了同一篇 markdown) */
  const loadStored = useCallback((codes: string[]) => {
    if (codes.length === 0) {
      setMd("");
      setVerdicts({});
      return;
    }
    Promise.all(codes.map((c) => getHoldingAnalysis(c).catch(() => null))).then((list) => {
      const vs: Record<string, HoldingVerdict> = {};
      list.forEach((a, i) => {
        if (a?.verdict) vs[codes[i]] = a.verdict;
      });
      setVerdicts(vs);
      // markdown 取最新那份(同批分析的几只内容相同)
      const newest = list
        .filter((a): a is NonNullable<typeof a> => Boolean(a?.markdown))
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
      setMd(newest?.markdown ?? "");
    });
  }, []);

  useEffect(() => {
    if (analyzing) return; // 分析中不要用历史结果覆盖流式内容
    loadStored(sel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel.join(","), loadStored]);

  const toggle = (code: string) =>
    setSel((s) => (s.includes(code) ? s.filter((c) => c !== code) : [...s, code]));

  const analyze = () => {
    if (sel.length === 0) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const codes = rows.map((h) => h.code).filter((c) => sel.includes(c)); // 按持仓列表顺序提交
    setMd("");
    setVerdicts({});
    setUsage(null);
    setAnalyzing(true);
    streamSSE(
      "/api/holdings/analyze",
      { codes, date },
      (t) => setMd((p) => p + t),
      (u) => {
        setAnalyzing(false);
        if (u) setUsage(u);
        loadStored(codes);
        onAnalyzed?.();
      },
      ctrl.signal,
    ).catch(() => setAnalyzing(false));
  };

  if (rows.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        还没有持仓,先在盘中视图的「添加持仓」录入(支持上传持仓截图批量导入)。
      </Typography>
    );
  }

  const allChecked = sel.length === rows.length;
  // 只把已诊断的票交给速览板;排序(先动谁)由 HoldingBoard 自己按动作+优先级处理
  const boardRows: BoardRow[] = rows
    .filter((h) => verdicts[h.code])
    .map((h) => ({ h, v: verdicts[h.code] }));

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
        <FormControlLabel
          sx={{ mr: 1 }}
          control={
            <Checkbox
              size="small"
              checked={allChecked}
              indeterminate={sel.length > 0 && !allChecked}
              onChange={(e) => setSel(e.target.checked ? rows.map((h) => h.code) : [])}
            />
          }
          label={<Typography variant="caption">全选</Typography>}
        />
        {rows.map((h) => (
          <Chip
            key={h.code}
            size="small"
            clickable
            onClick={() => toggle(h.code)}
            color={sel.includes(h.code) ? "primary" : "default"}
            variant={sel.includes(h.code) ? "filled" : "outlined"}
            label={
              <span>
                {h.name || h.code}
                {h.pnl_pct != null && (
                  <span style={{ opacity: 0.75, marginLeft: 4 }}>
                    {h.pnl_pct > 0 ? "+" : ""}
                    {h.pnl_pct}%
                  </span>
                )}
              </span>
            }
          />
        ))}
      </Stack>

      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }} flexWrap="wrap" useFlexGap>
        <Button
          size="small"
          variant="contained"
          startIcon={analyzing ? <CircularProgress size={14} color="inherit" /> : <AutoAwesomeIcon />}
          disabled={analyzing || sel.length === 0}
          onClick={analyze}
        >
          {md ? "重新诊断" : "跑诊断"}
          {sel.length > 1 ? `(${sel.length}只)` : ""}
        </Button>
        <Button
          size="small"
          startIcon={<ImageIcon />}
          disabled={boardRows.length === 0}
          onClick={() => setPosterOpen(true)}
        >
          导出速览图
        </Button>
        {usage && (
          <Typography variant="caption" color="text.secondary">
            本次约 ¥{usage.cost_cny.toFixed(2)} · {(usage.total_tokens / 1000).toFixed(1)}k
          </Typography>
        )}
      </Stack>

      {/* 处置速览:要动的出完整行、持有的折一行;走势散文进 tooltip,别在这平铺 */}
      {boardRows.length > 0 && (
        <Box sx={{ mb: 1.5 }}>
          <HoldingBoard rows={boardRows} scale={0.9} />
        </Box>
      )}

      {!md && !analyzing && (
        <Typography variant="body2" color="text.secondary">
          选好票点「跑诊断」:agent 基于 {date} 盘面 + 各票量价/题材给走势(T+1 + 波段)与买卖点;
          多选时还会给处置优先级(先砍谁)与同质化风险。约 1-2 分钟。
        </Typography>
      )}

      {/* 导出预览:按原始 1080 宽渲染(不缩放,否则 html-to-image 出图会变小),窗口不够宽则滚动 */}
      <Dialog open={posterOpen} onClose={() => setPosterOpen(false)} maxWidth={false}>
        <DialogContent sx={{ p: 2, bgcolor: "#010409", overflow: "auto" }}>
          <Box ref={ref} sx={{ width: HOLDING_WIDTH }}>
            <HoldingPoster date={date} />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPosterOpen(false)}>关闭</Button>
          <Button
            variant="contained"
            onClick={download}
            disabled={exporting}
            startIcon={exporting ? <CircularProgress size={14} color="inherit" /> : <ImageIcon />}
          >
            下载 PNG
          </Button>
        </DialogActions>
      </Dialog>

      <Box sx={mdSx}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
        {analyzing && (
          <Typography variant="body2" color="text.secondary">
            🤔 分析中({sel.length} 只,约 1-2 分钟)…
          </Typography>
        )}
      </Box>
    </Box>
  );
}
