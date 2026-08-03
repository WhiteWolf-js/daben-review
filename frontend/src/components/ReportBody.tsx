import { useState } from "react";
import { Box, Button, CircularProgress, Stack, Tooltip, Typography } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CheckIcon from "@mui/icons-material/Check";
import DownloadIcon from "@mui/icons-material/Download";
import ImageIcon from "@mui/icons-material/Image";
import MarkdownText from "./MarkdownText";
import ReportStructured from "./ReportStructured";
import { stripJson } from "../utils/report";
import { usePosterExport } from "../hooks/usePosterExport";

/**
 * 复盘完整正文 + 导出。md 由父级 useReport 提供。
 *
 * 生成中(loading)走原文流式,写完再切结构化图示 —— 边流边解析会拿到半行,
 * 卡片/表格会一格格闪出来,不如让文字先流完。
 *
 * 三种导出各有用处:复制 Markdown 贴飞书/微信最快、下载 .md 便于归档二次编辑、
 * 长图 PNG 发群里不用对方点开链接。导出的都是**去掉尾部 json 的正文**(那段是给系统解析的)。
 */
export default function ReportBody({
  md,
  loading,
  date,
}: {
  md: string;
  loading?: boolean;
  date?: string; // 仅用于导出文件名
}) {
  const clean = stripJson(md);
  const [copied, setCopied] = useState(false);
  const [copyErr, setCopyErr] = useState(false);
  const { ref, exporting, download } = usePosterExport(`复盘正文_${date || "latest"}.png`, 1.5);

  /** 复制。clipboard API 在非 https / 文档失焦时会拒绝,故用 textarea+execCommand 兜底,
   *  两条路都失败才提示改用「.md」下载 —— 静默失败最难受。 */
  const copy = async () => {
    const ok = await navigator.clipboard
      ?.writeText(clean)
      .then(() => true)
      .catch(() => false);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
      return;
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = clean;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const done = document.execCommand("copy");
      document.body.removeChild(ta);
      if (!done) throw new Error("execCommand 失败");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopyErr(true);
      setTimeout(() => setCopyErr(false), 2500);
    }
  };

  const downloadMd = () => {
    const blob = new Blob([clean], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `复盘_${date || "latest"}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Box>
      {/* 生成中不给导出:此时正文还在流,导出会截到半篇 */}
      {!loading && clean.trim() && (
        <Stack direction="row" spacing={0.75} justifyContent="flex-end" sx={{ mb: 1 }}>
          <Tooltip title={copyErr ? "浏览器不允许写剪贴板,请用「.md」下载" : copied ? "已复制" : "复制 Markdown 原文"}>
            <Button
              size="small"
              variant="text"
              color={copyErr ? "warning" : "primary"}
              startIcon={copied ? <CheckIcon color="success" /> : <ContentCopyIcon />}
              onClick={copy}
            >
              {copyErr ? "复制失败" : copied ? "已复制" : "复制"}
            </Button>
          </Tooltip>
          <Tooltip title="下载 .md 文件(便于归档/二次编辑)">
            <Button size="small" variant="text" startIcon={<DownloadIcon />} onClick={downloadMd}>
              .md
            </Button>
          </Tooltip>
          <Tooltip title="导出整篇长图 PNG(发群里免点链接)">
            <Button
              size="small"
              variant="text"
              startIcon={exporting ? <CircularProgress size={14} /> : <ImageIcon />}
              onClick={download}
              disabled={exporting}
            >
              {exporting ? "出图中" : "长图"}
            </Button>
          </Tooltip>
        </Stack>
      )}

      {/* ref 只包正文:导出图里不要带上面那排按钮。
          这里**必须留内边距**:段块自带 1px 边框,容器零 padding 会让边框直接顶在容器边上,
          和外层 PanelCard 的圆角挤成两条贴在一起的线。背景色不用设 —— 导出时
          usePosterExport 会铺 #0d1117,屏幕上继承卡片底色即可。 */}
      <Box ref={ref} sx={{ px: { xs: 1, sm: 1.5 }, py: 1.5 }}>
        {loading ? <MarkdownText md={clean} cursor /> : <ReportStructured md={clean} />}
      </Box>

      {!loading && !clean.trim() && (
        <Typography variant="body2" color="text.secondary">
          正文为空。
        </Typography>
      )}
    </Box>
  );
}
