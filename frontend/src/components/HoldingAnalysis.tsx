import { useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  FormControlLabel,
  Stack,
  Typography,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
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

const VERDICT_COLOR: Record<string, "success" | "warning" | "error" | "default"> = {
  持有: "success",
  减仓: "warning",
  清仓: "error",
};

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
  const abortRef = useRef<AbortController | null>(null);

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
  // 有 priority 的按它排(agent 给的处置优先级:1=最该先动),没有则保持持仓顺序
  const ordered = rows
    .filter((h) => verdicts[h.code])
    .sort((a, b) => (verdicts[a.code].priority ?? 99) - (verdicts[b.code].priority ?? 99));

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
        {usage && (
          <Typography variant="caption" color="text.secondary">
            本次约 ¥{usage.cost_cny.toFixed(2)} · {(usage.total_tokens / 1000).toFixed(1)}k
          </Typography>
        )}
      </Stack>

      {/* 结构化买卖点:每只一行,按处置优先级排 */}
      {ordered.length > 0 && (
        <Stack spacing={1} sx={{ mb: 1.5 }}>
          {ordered.map((h) => {
            const v = verdicts[h.code];
            return (
              <Box
                key={h.code}
                sx={{ borderLeft: "3px solid", borderColor: `${VERDICT_COLOR[v.verdict ?? ""] ?? "grey"}.main`, pl: 1.25, fontSize: 13 }}
              >
                <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.25 }}>
                  <Typography variant="body2" fontWeight={700}>
                    {h.name || h.code}
                  </Typography>
                  {v.verdict && (
                    <Chip
                      label={v.verdict}
                      size="small"
                      color={VERDICT_COLOR[v.verdict] ?? "default"}
                      sx={{ height: 18, fontSize: 11, fontWeight: 700 }}
                    />
                  )}
                  {v.priority != null && sel.length > 1 && (
                    <Typography variant="caption" color="text.secondary">
                      处置顺序 #{v.priority}
                    </Typography>
                  )}
                </Stack>
                {v.trend_t1 && <Box><b>T+1:</b> {v.trend_t1}</Box>}
                {v.trend_swing && <Box><b>波段:</b> {v.trend_swing}</Box>}
                {v.take_profit && <Box sx={{ color: "error.main" }}><b>止盈:</b> {v.take_profit}</Box>}
                {v.stop_loss && <Box sx={{ color: "success.main" }}><b>止损/离场:</b> {v.stop_loss}</Box>}
              </Box>
            );
          })}
        </Stack>
      )}

      {!md && !analyzing && (
        <Typography variant="body2" color="text.secondary">
          选好票点「跑诊断」:agent 基于 {date} 盘面 + 各票量价/题材给走势(T+1 + 波段)与买卖点;
          多选时还会给处置优先级(先砍谁)与同质化风险。约 1-2 分钟。
        </Typography>
      )}

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
