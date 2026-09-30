import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export default defineConfig({
  testDir: ".",
  testMatch: "ui-v2-capital-allocation.spec.ts",
  outputDir: path.join(os.tmpdir(), "hermes-569-playwright"),
  workers: 1,
  reporter: "list",
  use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:5173" },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1",
    cwd: frontend,
    url: "http://127.0.0.1:5173/e2e/fixtures/capital-allocation.html",
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
