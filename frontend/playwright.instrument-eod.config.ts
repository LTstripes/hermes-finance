import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const root = path.dirname(fileURLToPath(import.meta.url));
const port = process.env.HERMES_EOD_TEST_PORT ?? "18860";
export default defineConfig({
  testDir: "./e2e",
  testMatch: "instrument-eod.acceptance.ts",
  outputDir: path.join(os.tmpdir(), "hermes-instrument-eod-playwright"),
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${port}`, locale: "ru-RU", trace: "retain-on-failure" },
  webServer: {
    command: "uv run --locked --group dev python ../frontend/e2e/instrument_eod_fixture.py",
    cwd: path.resolve(root, "../backend"),
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 120000,
  },
});
