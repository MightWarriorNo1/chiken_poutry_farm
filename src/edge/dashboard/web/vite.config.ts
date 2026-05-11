import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// FastAPI serves the built `dist/` directly — see src/edge/dashboard/server.py.
// During `npm run dev`, Vite proxies `/api` + `/events` to the Python backend
// so the React app can fetch from the same origin it'll be served from later.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8090",
      "/events": {
        target: "http://127.0.0.1:8090",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Single-bundle build so FastAPI's static mount stays simple.
    rollupOptions: {
      output: {
        manualChunks: undefined,
      },
    },
  },
});
