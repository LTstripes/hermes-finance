import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const root = path.dirname(fileURLToPath(import.meta.url));
export default defineConfig({
  testDir: "./e2e",
  testMatch: "instrument-uat.acceptance.ts",
  outputDir: path.join(os.tmpdir(), "hermes-instrument-uat-playwright"),
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:18868", locale: "ru-RU", trace: "retain-on-failure" },
  webServer: {
    command: "uv run --locked --offline --no-sync python ../frontend/e2e/instrument_uat_fixture.py",
    cwd: path.resolve(root, "../backend"),
    url: "http://127.0.0.1:18868/api/health",
    reuseExistingServer: false,
    timeout: 120000,
  },
});
