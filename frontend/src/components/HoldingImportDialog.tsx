import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import Tooltip from "@mui/material/Tooltip";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { addHoldingsBulk, ocrHoldings, type OcrHoldingRow, type OcrUsage } from "../api";

/** 表格里可编辑的一行 = 识别结果 + 勾选态(编辑中的数值先按字符串存,避免输入过程被 Number 吃掉) */
type Row = OcrHoldingRow & { picked: boolean; costText: string; sharesText: string; boardsText: string };

const MAX_MB = 7;

const toRows = (rows: OcrHoldingRow[]): Row[] =>
  rows.map((r) => ({
    ...r,
    // 代码或成本价缺失的行默认不勾:提交前得先补,免得用户手滑存进一条脏数据
    picked: Boolean(r.code && r.cost_price),
    costText: r.cost_price == null ? "" : String(r.cost_price),
    sharesText: r.shares ? String(r.shares) : "",
    boardsText: r.buy_boards ? String(r.buy_boards) : "",
  }));

/**
 * 持仓截图导入:选图/粘贴 → agent 识别 → 勾选(可就地改成本价/股数/买入板/买入日)→ 批量入库。
 *
 * 识别走后端 /api/holdings/ocr(不落库),真正写入在「加入持仓」时才发生;
 * 已在持仓的票会标「将覆盖」——补仓后成本价变了,覆盖通常正是想要的。
 * 手动录入(HoldingForm)保持独立,识别失败时直接引导过去。
 */
export default function HoldingImportDialog({
  open,
  date,
  onClose,
  onImported,
}: {
  open: boolean;
  date: string;
  onClose: () => void;
  onImported?: () => void;
}) {
  const [preview, setPreview] = useState<string>(""); // dataURL,给缩略图
  const [rows, setRows] = useState<Row[]>([]);
  const [usage, setUsage] = useState<OcrUsage | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(0);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const reset = useCallback(() => {
    setPreview("");
    setRows([]);
    setUsage(null);
    setErr("");
    setBusy(false);
    setDone(0);
  }, []);

  useEffect(() => {
    if (open) reset();
  }, [open, reset]);

  const recognize = useCallback(
    (file: File) => {
      if (file.size > MAX_MB * 1024 * 1024) {
        setErr(`图片超过 ${MAX_MB}MB,请压缩后再传`);
        return;
      }
      setErr("");
      setRows([]);
      setUsage(null);
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = String(reader.result || "");
        setPreview(dataUrl);
        const b64 = dataUrl.split(",")[1] || "";
        setBusy(true);
        ocrHoldings(b64, file.type || "image/png", date)
          .then((res) => {
            setRows(toRows(res.rows));
            setUsage(res.usage);
            if (res.rows.length === 0) setErr("没从这张图里认出持仓行,换一张完整的持仓列表截图,或用下方手动录入");
          })
          .catch((e) => setErr(e?.response?.data?.detail || "识别失败,可改用下方手动录入"))
          .finally(() => setBusy(false));
      };
      reader.readAsDataURL(file);
    },
    [date],
  );

  // 截图后直接 Ctrl/Cmd+V 最顺手,不必先存文件
  const onPaste = useCallback(
    (e: React.ClipboardEvent) => {
      const item = Array.from(e.clipboardData?.items || []).find((i) => i.type.startsWith("image/"));
      const file = item?.getAsFile();
      if (file) {
        e.preventDefault();
        recognize(file);
      }
    },
    [recognize],
  );

  const patch = (i: number, p: Partial<Row>) =>
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...p } : r)));

  const picked = rows.filter((r) => r.picked && r.code.trim() && r.costText.trim());

  const submit = () => {
    if (picked.length === 0) return;
    setBusy(true);
    addHoldingsBulk(
      picked.map((r) => ({
        code: r.code.trim(),
        name: r.name,
        buy_price: Number(r.costText),
        shares: Number(r.sharesText || 0),
        buy_boards: Number(r.boardsText || 0),
        buy_date: r.buy_date,
      })),
    )
      .then((res) => {
        setDone(res.added);
        onImported?.();
        setTimeout(onClose, 900); // 让用户看到「已加入 N 只」再关
      })
      .catch(() => setErr("写入持仓失败,请重试"))
      .finally(() => setBusy(false));
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="md" fullWidth onPaste={onPaste}>
      <DialogTitle sx={{ pb: 1 }}>
        上传持仓截图
        <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
          券商 App 持仓页截图即可,识别后勾选要盯的票
        </Typography>
      </DialogTitle>
      <DialogContent dividers>
        <Stack spacing={1.5}>
          <Stack direction="row" spacing={1.5} alignItems="center">
            <Button
              variant="outlined"
              size="small"
              startIcon={<UploadFileIcon />}
              onClick={() => fileRef.current?.click()}
              disabled={busy}
            >
              选择图片
            </Button>
            <Typography variant="caption" color="text.secondary">
              或直接 {navigator.platform.includes("Mac") ? "⌘" : "Ctrl"}+V 粘贴截图
            </Typography>
            <Box sx={{ flexGrow: 1 }} />
            {preview && (
              <Box
                component="img"
                src={preview}
                alt="截图预览"
                sx={{ height: 44, borderRadius: 1, border: "1px solid", borderColor: "divider" }}
              />
            )}
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) recognize(f);
                e.target.value = ""; // 允许重选同一张
              }}
            />
          </Stack>

          {busy && rows.length === 0 && (
            <Box>
              <LinearProgress />
              <Typography variant="caption" color="text.secondary">
                识别中(约 5-10 秒)…
              </Typography>
            </Box>
          )}

          {err && <Alert severity="warning">{err}</Alert>}
          {done > 0 && <Alert severity="success">已加入 {done} 只持仓</Alert>}

          {rows.length > 0 && (
            <>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell padding="checkbox">
                      <Checkbox
                        size="small"
                        checked={rows.every((r) => r.picked)}
                        indeterminate={rows.some((r) => r.picked) && !rows.every((r) => r.picked)}
                        onChange={(e) => setRows((rs) => rs.map((r) => ({ ...r, picked: e.target.checked })))}
                      />
                    </TableCell>
                    <TableCell>名称 / 代码</TableCell>
                    {/* 股数是 5 位数(1.2万股),加上 number 输入框的步进箭头,窄于 140 会把数字截掉 */}
                    <TableCell align="right" sx={{ width: 116 }}>成本价</TableCell>
                    <TableCell align="right" sx={{ width: 140 }}>股数</TableCell>
                    <TableCell align="right" sx={{ width: 104 }}>买入板</TableCell>
                    <TableCell align="right" sx={{ width: 92 }}>截图盈亏</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((r, i) => (
                    <TableRow key={`${r.code}-${i}`} hover selected={r.picked}>
                      <TableCell padding="checkbox">
                        <Checkbox
                          size="small"
                          checked={r.picked}
                          onChange={(e) => patch(i, { picked: e.target.checked })}
                        />
                      </TableCell>
                      <TableCell>
                        <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                          <Typography variant="body2" fontWeight={600}>
                            {r.name || "(未识别)"}
                          </Typography>
                          {/* 代码**始终可改**:截图没有代码列时后端按名称反查,查错/查不到都要能就地改 */}
                          <TextField
                            size="small"
                            placeholder="补代码"
                            value={r.code}
                            onChange={(e) => patch(i, { code: e.target.value.replace(/\D/g, "").slice(0, 6) })}
                            error={Boolean(r.code) && r.code.length !== 6}
                            helperText={r.code && r.code.length !== 6 ? "需 6 位" : undefined}
                            sx={{ width: 104 }}
                          />
                          {r.code_from === "name" && (
                            <Tooltip title="截图里没有代码,按股票名称反查到的,请核对">
                              <Chip label="名称反查" size="small" variant="outlined" sx={{ height: 18, fontSize: 11 }} />
                            </Tooltip>
                          )}
                          {r.exists && <Chip label="已有·将覆盖" size="small" color="warning" sx={{ height: 18, fontSize: 11 }} />}
                        </Stack>
                      </TableCell>
                      <TableCell align="right">
                        <TextField
                          size="small"
                          type="number"
                          value={r.costText}
                          onChange={(e) => patch(i, { costText: e.target.value })}
                          inputProps={{ style: { textAlign: "right" } }}
                          fullWidth
                        />
                      </TableCell>
                      <TableCell align="right">
                        <TextField
                          size="small"
                          type="number"
                          value={r.sharesText}
                          onChange={(e) => patch(i, { sharesText: e.target.value })}
                          inputProps={{ style: { textAlign: "right" } }}
                          fullWidth
                        />
                      </TableCell>
                      <TableCell align="right">
                        <TextField
                          size="small"
                          type="number"
                          value={r.boardsText}
                          onChange={(e) => patch(i, { boardsText: e.target.value })}
                          inputProps={{ style: { textAlign: "right" } }}
                          fullWidth
                        />
                      </TableCell>
                      <TableCell
                        align="right"
                        sx={{
                          fontWeight: 700,
                          color: r.pnl_pct == null ? "text.secondary" : r.pnl_pct >= 0 ? "error.main" : "success.main",
                        }}
                      >
                        {r.pnl_pct == null ? "—" : `${r.pnl_pct > 0 ? "+" : ""}${r.pnl_pct}%`}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Typography variant="caption" color="text.secondary">
                买入板数已按 {date} 涨停池自动填,可改;买入日默认 {date}。截图的现价不入库(系统自己取最新价)。
                {usage && ` · 本次识别 ${usage.total_tokens} tokens ≈ ¥${usage.cost_cny.toFixed(3)}`}
              </Typography>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy} size="small">
          取消
        </Button>
        <Button variant="contained" size="small" onClick={submit} disabled={busy || picked.length === 0}>
          加入持仓{picked.length > 0 ? `(${picked.length})` : ""}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
