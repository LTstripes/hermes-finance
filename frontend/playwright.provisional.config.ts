import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const root = path.dirname(fileURLToPath(import.meta.url));
export default defineConfig({
  testDir: "./e2e",
  testMatch: "provisional-source.acceptance.ts",
  outputDir: path.join(os.tmpdir(), "hermes-provisional-playwright"),
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:18790",
    locale: "ru-RU",
    trace: "retain-on-failure",
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH },
  },
  webServer: {
    command: "uv run --locked --group dev python ../frontend/e2e/provisional_source_fixture.py",
    cwd: path.resolve(root, "../backend"),
    url: "http://127.0.0.1:18790/api/health",
    reuseExistingServer: false,
    timeout: 120000,
  },
});
