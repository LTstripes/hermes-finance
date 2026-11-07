import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    manifest: true,
    rollupOptions: { input: { main: "index.html", instrumentUat: "instrument-uat.html" } },
  },
  server: {
    host: "127.0.0.1",
    // Trace resources include HTML. Writing evidence must not reload an active
    // browser journey (the visual harness writes inside the frontend root).
    watch: { ignored: ["**/.visual-audit/**", "**/test-results/**"] },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
        // Mocked visual runs have no backend. A request escaping their explicit
        // fixtures must fail locally, never reach an unrelated runtime on 8000.
        bypass: process.env.HERMES_VISUAL_AUDIT === "true" ? () => false : undefined,
      },
    },
  },
  test: {
    css: true,
    exclude: ["**/node_modules/**", "**/dist/**", "**/e2e/**", "**/test-results/**"],
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
