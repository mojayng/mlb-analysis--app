import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the page is served from Vite (port 5173) while the API runs
// on Flask (port 5000). Browsers block cross-origin requests by default (CORS),
// so Vite forwards anything starting with /api to Flask. The React code can
// then call a relative URL like "/api/probables" and never hardcode a port.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:5000",
    },
  },
});
