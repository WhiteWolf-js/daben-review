import { Box, Card, CardContent, Stack, Typography, type CardProps } from "@mui/material";
import type { ReactNode } from "react";

/**
 * 常开面板卡:标题行 + 内容,始终展开。
 *
 * 只给**自身不带 Card/标题**的裸内容用(EmotionPanel 完整版 / ReportBody / HoldingAnalysis / HoldingForm);
 * ThemePanel、LadderView、CandidatePanel 这类自带 Card + 标题的直接放进 section,别再套一层。
 */
export default function PanelCard({
  title,
  hint,
  children,
  sx,
}: {
  title: string;
  hint?: ReactNode; // 标题右侧的补充说明
  children: ReactNode;
  sx?: CardProps["sx"];
}) {
  return (
    <Card sx={sx}>
      <CardContent>
        <Stack direction="row" alignItems="baseline" spacing={1} sx={{ mb: 1.5 }}>
          <Typography variant="subtitle1" fontWeight={600}>
            {title}
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          {hint && (
            <Typography variant="caption" color="text.secondary">
              {hint}
            </Typography>
          )}
        </Stack>
        {children}
      </CardContent>
    </Card>
  );
}
