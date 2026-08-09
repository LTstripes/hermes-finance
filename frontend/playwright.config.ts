import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const configDir = path.dirname(fileURLToPath(import.meta.url));
const databaseDir = fs.mkdtempSync(path.join(os.tmpdir(), "hermes-finance-g04-"));
const databasePath = path.join(databaseDir, "finance.db");

export default defineConfig({
  testDir: "./e2e",
  outputDir: path.join(os.tmpdir(), "hermes-finance-playwright-results"),
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "uv run alembic upgrade head && uv run hermes-finance-api",
      cwd: path.resolve(configDir, "../backend"),
      env: {
        HERMES_FINANCE_DATABASE_PATH: databasePath,
        HERMES_FINANCE_HOST: "127.0.0.1",
        HERMES_FINANCE_PORT: "8000",
        HERMES_FINANCE_RELOAD: "false",
        PYTHONPATH: "",
      },
      url: "http://127.0.0.1:8000/api/health",
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --host 127.0.0.1",
      cwd: configDir,
      url: "http://127.0.0.1:5173",
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
