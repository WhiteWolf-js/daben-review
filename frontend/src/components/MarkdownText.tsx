import { Box } from "@mui/material";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** 正文 markdown 的统一排版。ReportBody(流式/回退)与 ReportStructured(段内 rest)共用。 */
const mdSx = {
  "& p": { my: 0.75, fontSize: 13, lineHeight: 1.8 },
  "& ul, & ol": { my: 0.75, pl: 2.5 },
  "& li": { fontSize: 13, lineHeight: 1.8 },
  "& h2": { fontSize: 16, mt: 2, mb: 1, color: "primary.main" },
  "& h3": { fontSize: 14, mt: 1.5, mb: 0.5 },
  "& table": { borderCollapse: "collapse", width: "100%", my: 1, fontSize: 12 },
  "& th, & td": { border: "1px solid rgba(255,255,255,0.12)", p: "4px 8px" },
  "& code": { bgcolor: "rgba(255,255,255,0.08)", px: 0.5, borderRadius: 0.5, fontSize: 12 },
  "& blockquote": {
    borderLeft: "3px solid",
    borderColor: "warning.main",
    pl: 1.5,
    ml: 0,
    color: "text.secondary",
  },
  "& pre": { bgcolor: "rgba(0,0,0,0.3)", p: 1.5, borderRadius: 1, overflow: "auto", fontSize: 12 },
};

export default function MarkdownText({ md, cursor }: { md: string; cursor?: boolean }) {
  return (
    <Box sx={mdSx}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
      {cursor && (
        <>
          <Box component="span" sx={{ animation: "blink 1s infinite" }}>
            ▌
          </Box>
          <style>{"@keyframes blink{50%{opacity:0}}"}</style>
        </>
      )}
    </Box>
  );
}
