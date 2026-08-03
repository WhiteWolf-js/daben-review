import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5173 }, // host:true 监听 0.0.0.0,局域网/手机可访问
});
