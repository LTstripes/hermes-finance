import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const configDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  testDir: "./e2e",
  testMatch: "ui-v2-month-editor.visual.spec.ts",
  outputDir: path.join(os.tmpdir(), "hermes-finance-month-editor-playwright"),
  workers: 1,
  reporter: "list",
  use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:1607" },
  webServer: {
    command: "node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 1607 --strictPort",
    cwd: configDir,
    url: "http://127.0.0.1:1607",
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
