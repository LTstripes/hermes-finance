import path from "node:path";
import { defineConfig } from "@playwright/test";
const baseURL = `http://127.0.0.1:${process.env.HERMES_RETURNS_TEST_PORT ?? "18963"}`;
export default defineConfig({
  testDir: "./e2e",
  testMatch: "returns-api.acceptance.ts",
  workers: 1,
  retries: 0,
  outputDir: ".visual-audit/returns-api",
  reporter: "list",
  use: {
    baseURL,
    viewport: { width: 1440, height: 1000 },
    locale: "ru-RU",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"}" ../frontend/e2e/returns_api_fixture.py`,
    cwd: path.resolve("../backend"),
    url: `${baseURL}/api/returns/context`,
    reuseExistingServer: false,
    timeout: 60000,
  },
});
