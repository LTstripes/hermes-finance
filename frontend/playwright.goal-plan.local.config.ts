import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  testMatch: "goal-plan.acceptance.ts",
  workers: 1,
  retries: 0,
  outputDir: "./.visual-audit/goal-plan-1129",
  use: { baseURL: "http://127.0.0.1:5199", locale: "ru-RU", trace: "retain-on-failure" },
  webServer: [
    {
      command: `${process.env.HERMES_GOAL_PLAN_PYTHON ?? "python"} ../frontend/e2e/goal_plan_fixture.py`,
      cwd: "../backend",
      env: { PYTHONPATH: "src", PYTHONIOENCODING: "utf-8" },
      url: "http://127.0.0.1:18929/api/health",
      reuseExistingServer: false,
      gracefulShutdown: { signal: "SIGINT", timeout: 10_000 },
    },
    {
      command: "npm run dev -- --port 5199 --strictPort",
      env: { HERMES_CHROMIUM_TEST_PORT: "18929" },
      url: "http://127.0.0.1:5199",
      reuseExistingServer: false,
    },
  ],
});
