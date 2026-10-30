import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies /api to Django, so the browser sees one origin (no CORS).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: { "/api": process.env.VITE_API_PROXY ?? "http://localhost:8000" },
  },
});
