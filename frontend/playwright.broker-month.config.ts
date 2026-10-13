import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const root = path.dirname(fileURLToPath(import.meta.url));
const port = process.env.HERMES_BROKER_MONTH_TEST_PORT ?? "18773";
export default defineConfig({
  testDir: "./e2e",
  testMatch: "broker-month.acceptance.ts",
  outputDir: path.join(os.tmpdir(), "hermes-broker-month-playwright"),
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${port}`, locale: "ru-RU", trace: "retain-on-failure" },
  webServer: {
    command: "uv run --locked --group dev python ../frontend/e2e/broker_month_fixture.py",
    cwd: path.resolve(root, "../backend"),
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 120000,
  },
});
