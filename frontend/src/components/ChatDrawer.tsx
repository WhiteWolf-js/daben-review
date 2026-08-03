import { useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  CircularProgress,
  Drawer,
  IconButton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import dayjs from "dayjs";
import SendIcon from "@mui/icons-material/Send";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CheckIcon from "@mui/icons-material/Check";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import StopCircleIcon from "@mui/icons-material/StopCircle";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { streamSSE } from "../api";

interface Msg {
  role: "user" | "assistant";
  text: string;
  ts?: number; // 毫秒时间戳(旧历史可能没有)
}

const STORE_KEY = "daban_chat_history"; // 追问历史仅存本地 localStorage,不落后端库

function loadHistory(): Msg[] {
  try {
    const arr = JSON.parse(localStorage.getItem(STORE_KEY) || "[]");
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

const fmtTs = (ts?: number) => (ts ? dayjs(ts).format("MM-DD HH:mm") : "");
const dayKey = (ts?: number) => (ts ? dayjs(ts).format("YYYYMMDD") : "");

export default function ChatDrawer({
  date,
  open,
  onClose,
}: {
  date: string;
  open: boolean;
  onClose: () => void;
}) {
  const [msgs, setMsgs] = useState<Msg[]>(loadHistory);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0); // 已等待秒数:首字节前要等十几秒到一分多,没提示会以为卡死
  const [copied, setCopied] = useState<number | null>(null);
  const [locate, setLocate] = useState<string>(""); // 定位到的 YYYYMMDD(仅滚动,不过滤)
  const abortRef = useRef<AbortController | null>(null);
  const startedAt = useRef<number | null>(null);
  const itemRefs = useRef<(HTMLDivElement | null)[]>([]);

  // 等待期每秒刷新计时(agent 走 CLI 有约 110k token 的固定 prompt 开销,首字节 15s 起;
  // 每多调一个工具就多一轮往返、再加十几到几十秒)
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => {
      if (startedAt.current) setElapsed(Math.round((Date.now() - startedAt.current) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [busy]);

  // 追问历史持久化到 localStorage(不落库)
  useEffect(() => {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(msgs));
    } catch {
      /* 存储满 / 隐私模式:忽略 */
    }
  }, [msgs]);

  // 历史里出现过的日期(仅这些可在「定位到」里选)
  const availableDates = useMemo(() => {
    const s = new Set<string>();
    msgs.forEach((m) => m.ts && s.add(dayKey(m.ts)));
    return s;
  }, [msgs]);

  const jumpToDay = (d: string) => {
    setLocate(d);
    const idx = msgs.findIndex((m) => dayKey(m.ts) === d);
    if (idx >= 0) itemRefs.current[idx]?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const send = () => {
    const q = input.trim();
    if (!q || busy || !date) return;
    setInput("");
    const now = Date.now();
    setMsgs((m) => [...m, { role: "user", text: q, ts: now }, { role: "assistant", text: "", ts: now }]);
    setBusy(true);
    setElapsed(0);
    startedAt.current = Date.now();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const done = () => {
      setBusy(false);
      startedAt.current = null;
    };
    streamSSE(
      "/api/chat",
      { date, question: q },
      (t) =>
        setMsgs((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          copy[copy.length - 1] = { ...last, text: last.text + t };
          return copy;
        }),
      done,
      ctrl.signal,
    ).catch((e) => {
      done();
      const msg = String(e?.message || e || "");
      if (msg.includes("abort")) return; // 用户主动中断,不写错误
      setMsgs((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        copy[copy.length - 1] = { ...last, text: last.text || `[追问失败] ${msg || "连接中断"}` };
        return copy;
      });
    });
  };

  /** 主动中断:等太久时能停(agent 每多调一次工具就多等几十秒) */
  const stop = () => {
    abortRef.current?.abort();
    setBusy(false);
    startedAt.current = null;
    setMsgs((m) => {
      const copy = [...m];
      const last = copy[copy.length - 1];
      if (last && last.role === "assistant" && !last.text) {
        copy[copy.length - 1] = { ...last, text: "[已中断]" };
      }
      return copy;
    });
  };

  const copy = (text: string, i: number) => {
    navigator.clipboard
      ?.writeText(text)
      .then(() => {
        setCopied(i);
        setTimeout(() => setCopied((c) => (c === i ? null : c)), 1500);
      })
      .catch(() => {});
  };

  const clearHistory = () => {
    setMsgs([]);
    setInput("");
    setLocate("");
  };

  return (
    <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ sx: { width: { xs: "92vw", sm: 640 } } }}>
      <Box sx={{ p: 2, display: "flex", flexDirection: "column", height: "100%" }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="subtitle1" fontWeight={600} sx={{ flexGrow: 1 }}>
            追问 · {date}
          </Typography>
          <DatePicker
            label="定位到"
            value={locate ? dayjs(`${locate.slice(0, 4)}-${locate.slice(4, 6)}-${locate.slice(6)}`) : null}
            onChange={(v) => v && jumpToDay(v.format("YYYYMMDD"))}
            shouldDisableDate={(d) => !availableDates.has(d.format("YYYYMMDD"))}
            format="MM-DD"
            slotProps={{ textField: { size: "small", sx: { width: 128 } } }}
          />
          {msgs.length > 0 && (
            <Tooltip title="清空追问历史(本地)">
              <IconButton size="small" onClick={clearHistory}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </Stack>
        <Box sx={{ flex: 1, overflow: "auto" }}>
          {msgs.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              基于当日数据向 agent 追问,如「小哈今天走的是哪个属性?」「半导体能不能出连板?」历史仅存本地。
            </Typography>
          )}
          <Stack spacing={1.5}>
            {msgs.map((m, i) => {
              const placeholder = !m.text && busy && i === msgs.length - 1;
              return (
                <Box
                  key={i}
                  ref={(el: HTMLDivElement | null) => {
                    itemRefs.current[i] = el;
                  }}
                  sx={{
                    alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                    bgcolor: m.role === "user" ? "primary.dark" : "background.default",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: 1.5,
                    p: 1,
                    maxWidth: "92%",
                    fontSize: 13,
                    scrollMarginTop: 8,
                    "& p": { m: 0 },
                    "& table": { borderCollapse: "collapse", fontSize: 11 },
                    "& th, & td": { border: "1px solid rgba(255,255,255,0.12)", p: "2px 6px" },
                  }}
                >
                  {placeholder ? (
                    <Stack direction="row" alignItems="center" spacing={1}>
                      <CircularProgress size={13} />
                      <Typography variant="body2" color="text.secondary">
                        {elapsed < 15
                          ? `准备上下文…已等 ${elapsed}s`
                          : elapsed < 45
                            ? `思考中…已等 ${elapsed}s`
                            : `在查数据补充(每调一次工具多一轮)…已等 ${elapsed}s`}
                      </Typography>
                      <Tooltip title="中断这次追问">
                        <IconButton size="small" onClick={stop} sx={{ p: 0.25 }}>
                          <StopCircleIcon sx={{ fontSize: 17 }} />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text || "…"}</ReactMarkdown>
                  )}
                  <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mt: 0.5 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontSize: 11 }}>
                      {m.role === "user" ? "我 · " : "AI · "}
                      {fmtTs(m.ts)}
                    </Typography>
                    {m.role === "assistant" && m.text && (
                      <Tooltip title={copied === i ? "已复制" : "复制"}>
                        <IconButton size="small" onClick={() => copy(m.text, i)} sx={{ p: 0.25 }}>
                          {copied === i ? (
                            <CheckIcon color="success" sx={{ fontSize: 15 }} />
                          ) : (
                            <ContentCopyIcon sx={{ fontSize: 15 }} />
                          )}
                        </IconButton>
                      </Tooltip>
                    )}
                  </Stack>
                </Box>
              );
            })}
          </Stack>
        </Box>
        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
          <TextField
            size="small"
            fullWidth
            placeholder="追问…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            disabled={busy}
          />
          <IconButton color="primary" onClick={send} disabled={busy}>
            <SendIcon />
          </IconButton>
        </Stack>
      </Box>
    </Drawer>
  );
}
