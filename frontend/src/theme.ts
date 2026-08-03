import { createTheme } from "@mui/material/styles";

// 暗色交易风格:红涨绿跌沿用 A股习惯(红为强/涨)
export const theme = createTheme({
  palette: {
    mode: "dark",
    background: { default: "#0d1117", paper: "#161b22" },
    primary: { main: "#e5484d" }, // 涨/强
    success: { main: "#30a46c" }, // 跌/弱
    warning: { main: "#f5a623" },
    divider: "rgba(255,255,255,0.08)",
  },
  typography: {
    fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
    fontSize: 13,
  },
  shape: { borderRadius: 8 },
  components: {
    MuiCard: { styleOverrides: { root: { border: "1px solid rgba(255,255,255,0.08)" } } },
  },
});
