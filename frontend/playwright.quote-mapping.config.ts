import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const directory = path.dirname(fileURLToPath(import.meta.url));
const port = process.env.HERMES_SYNTHETIC_QUOTE_MAPPING_PORT ?? "18469";
export default defineConfig({
  testDir: "./e2e",
  testMatch: "quote-mapping.acceptance.ts",
  workers: 1,
  retries: 0,
  outputDir:
    process.env.HERMES_SYNTHETIC_QUOTE_MAPPING_OUTPUT ??
    path.join(os.tmpdir(), "hermes-quote-mapping-browser"),
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    locale: "ru-RU",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"}" -m uvicorn quote_mapping_browser_fixture:create_browser_app --factory --host 127.0.0.1 --port ${port}`,
    cwd: path.resolve(directory, "../backend"),
    env: { PYTHONPATH: path.resolve(directory, "../backend/tests") },
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
