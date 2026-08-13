import React from "react";
import ReactDOM from "react-dom/client";
import { CssBaseline, ThemeProvider } from "@mui/material";
import { LicenseInfo } from "@mui/x-license";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDayjs } from "@mui/x-date-pickers/AdapterDayjs";
import { theme } from "./theme";
import App from "./App";
import PosterView from "./components/PosterView";
import AuctionPoster from "./components/AuctionPoster";
import LadderPoster from "./components/LadderPoster";
import HoldingPoster from "./components/HoldingPoster";

// ?poster=YYYYMMDD 直接渲染纯海报页(供手动分享与后端 Playwright 截图),不引路由库
// 追加 &kind=auction 渲染盘前竞价海报(&brief= 传 agent 盘前解读)、&kind=ladder 渲染连板天梯、
// &kind=holding 渲染持仓处置速览
const _q = new URLSearchParams(window.location.search);
const posterDate = _q.get("poster");
const posterKind = _q.get("kind");
const posterBrief = _q.get("brief") ?? "";

// MUI X pro license(供 mui-x 组件使用)。**必须走环境变量,绝不能硬编码** ——
// 授权码是商业凭证,写进代码会随仓库公开出去。配在 `.env.local`(见 .env.example)。
const MUI_LICENSE = import.meta.env.VITE_MUI_LICENSE;
if (MUI_LICENSE) LicenseInfo.setLicenseKey(MUI_LICENSE);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <LocalizationProvider dateAdapter={AdapterDayjs}>
        {posterDate ? (
          posterKind === "auction" ? (
            <AuctionPoster brief={posterBrief} />
          ) : posterKind === "ladder" ? (
            <LadderPoster date={posterDate} />
          ) : posterKind === "holding" ? (
            <HoldingPoster date={posterDate} />
          ) : (
            <PosterView date={posterDate} />
          )
        ) : (
          <App />
        )}
      </LocalizationProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
