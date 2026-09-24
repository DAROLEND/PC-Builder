/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the Vite server proxies /api to Django, so the browser sees a
// single origin (no CORS). In Docker, nginx does the same in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.VITE_PROXY_TARGET ?? "http://localhost:8000",
      "/admin": process.env.VITE_PROXY_TARGET ?? "http://localhost:8000",
      "/static": process.env.VITE_PROXY_TARGET ?? "http://localhost:8000",
      "/media": process.env.VITE_PROXY_TARGET ?? "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
