import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "@playwright/test";

const configDir = path.dirname(fileURLToPath(import.meta.url));
const baseURL = process.env.HERMES_VISUAL_AUDIT_BASE_URL ?? "http://127.0.0.1:4174";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "visual-audit.spec.ts",
  outputDir: path.join(configDir, ".visual-audit", "playwright-results"),
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
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
  projects: [
    { name: "1366x768", use: { viewport: { width: 1366, height: 768 } } },
    { name: "1440x900", use: { viewport: { width: 1440, height: 900 } } },
    { name: "1920x1080", use: { viewport: { width: 1920, height: 1080 } } },
  ],
});
