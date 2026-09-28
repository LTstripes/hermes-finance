import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const root = path.dirname(fileURLToPath(import.meta.url));
export default defineConfig({
  testDir: "./e2e",
  testMatch: "alfa-baseline.acceptance.ts",
  outputDir: ".visual-audit/alfa-results",
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:8000", locale: "ru-RU", trace: "retain-on-failure" },
  webServer: {
    command: "uv run --locked python ../frontend/e2e/alfa_fixture.py",
    cwd: path.resolve(root, "../backend"),
    url: "http://127.0.0.1:8000/api/health",
    reuseExistingServer: false,
    timeout: 120000,
  },
});
