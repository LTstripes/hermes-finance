import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

const configDir = path.dirname(fileURLToPath(import.meta.url));
const baseURL = process.env.HERMES_VISUAL_AUDIT_BASE_URL ?? "http://127.0.0.1:4174";

const repeatedViewportSpecs =
  /[/\\](?:performance-preparation\.visual|ui-v2-iis-forms|ui-v2-months|ui-v2-capital-allocation|ui-v2-scenario|ui-v2-payout-forecast)\.spec\.ts$/;

function visualProject(name: string, width: number, height: number) {
  const referenceDesktop = name === "1440x900";
  return {
    name,
    ...(referenceDesktop
      ? {}
      : {
          grepInvert: /@viewport-owned/,
          testIgnore: repeatedViewportSpecs,
        }),
    use: { viewport: { width, height } },
  };
}

export default defineConfig({
  testDir: "./e2e",
  testMatch: [
    "visual-audit.spec.ts",
    "ui-v2.visual.spec.ts",
    "ui-v2-data.visual.spec.ts",
    "ui-v2-income.visual.spec.ts",
    "ui-v2-default-switch.spec.ts",
    "performance-preparation.visual.spec.ts",
    "ui-v2-months.spec.ts",
    "ui-v2-month-editor.visual.spec.ts",
    "ui-v2-statement-import.spec.ts",
    "ui-v2-payout-forecast.spec.ts",
    "ui-v2-iis-forms.spec.ts",
    "ui-v2-capital-allocation.spec.ts",
    "ui-v2-scenario.spec.ts",
  ],
  outputDir: path.join(configDir, ".visual-audit", "playwright-results"),
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 2,
  reporter: "list",
  expect: { timeout: 10_000 },
  use: {
    baseURL,
    colorScheme: "light",
    locale: "ru-RU",
    reducedMotion: "reduce",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  // 1440x900 owns tests that replace the project viewport with their own sizes.
  // The other desktop projects skip those executions. --project=1440x900 still
  // selects them, including the UI evidence grep.
  projects: [
    visualProject("1366x768", 1366, 768),
    visualProject("1440x900", 1440, 900),
    visualProject("1920x1080", 1920, 1080),
  ],
});
