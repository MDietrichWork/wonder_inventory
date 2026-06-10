import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API to the local FastAPI backend (uvicorn on :8000), so the React
// console runs against live BigQuery + Jira data with hot-reload for visual / rule iteration.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
