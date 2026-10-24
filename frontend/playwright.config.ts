import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices, type PlaywrightTestConfig } from "@playwright/test";

import { selectPlaywrightProjects } from "./playwrightProjects";

const configDir = path.dirname(fileURLToPath(import.meta.url));
const databaseDir = fs.mkdtempSync(path.join(os.tmpdir(), "hermes-finance-g04-"));
const databasePath = path.join(databaseDir, "finance.db");

// Keep each former config's project and server settings together. Playwright's
// webServer/reporter/workers/forbidOnly settings are invocation-wide, so only the
// selected suite supplies those settings. The visual evidence matrix stays in
// playwright.visual.config.ts.
const suites: Record<string, PlaywrightTestConfig> = {
  "capital-allocation": {
    testDir: "./e2e",
    testMatch: "ui-v2-capital-allocation.spec.ts",
    outputDir: path.join(os.tmpdir(), "hermes-569-playwright"),
    workers: 1,
    reporter: "list",
    use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:5173" },
    webServer: {
      command: "npm run dev -- --host 127.0.0.1",
      cwd: configDir,
      url: "http://127.0.0.1:5173/e2e/fixtures/capital-allocation.html",
      timeout: 120_000,
      reuseExistingServer: false,
    },
  },
  alfa: {
    testDir: "./e2e",
    testMatch: "alfa-baseline.acceptance.ts",
    outputDir: ".visual-audit/alfa-results",
    workers: 1,
    retries: 0,
    reporter: "list",
    use: { baseURL: "http://127.0.0.1:8000", locale: "ru-RU", trace: "retain-on-failure" },
    webServer: {
      command: "uv run --locked python ../frontend/e2e/alfa_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  "broker-month": {
    testDir: "./e2e",
    testMatch: "broker-month.acceptance.ts",
    outputDir: path.join(os.tmpdir(), "hermes-broker-month-playwright"),
    workers: 1,
    retries: 0,
    reporter: "list",
    use: {
      baseURL: `http://127.0.0.1:${process.env.HERMES_BROKER_MONTH_TEST_PORT ?? "18773"}`,
      locale: "ru-RU",
      trace: "retain-on-failure",
    },
    webServer: {
      command: "uv run --locked --group dev python ../frontend/e2e/broker_month_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: `http://127.0.0.1:${process.env.HERMES_BROKER_MONTH_TEST_PORT ?? "18773"}/api/health`,
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  chromium: {
    testDir: "./e2e",
    outputDir: path.join(os.tmpdir(), "hermes-finance-playwright-results"),
    fullyParallel: false,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 2 : 0,
    workers: 1,
    reporter: "list",
    use: {
      ...devices["Desktop Chrome"],
      baseURL: "http://127.0.0.1:5173",
      trace: "retain-on-failure",
      screenshot: "only-on-failure",
      video: "retain-on-failure",
    },
    webServer: [
      {
        command: "uv run alembic upgrade head && uv run hermes-finance-api",
        cwd: path.resolve(configDir, "../backend"),
        env: {
          HERMES_FINANCE_DATABASE_PATH: databasePath,
          HERMES_FINANCE_HOST: "127.0.0.1",
          HERMES_FINANCE_PORT: "8000",
          HERMES_FINANCE_RELOAD: "false",
          PYTHONPATH: "",
        },
        url: "http://127.0.0.1:8000/api/health",
        timeout: 120_000,
        reuseExistingServer: false,
      },
      {
        command: "npm run dev -- --host 127.0.0.1",
        cwd: configDir,
        url: "http://127.0.0.1:5173",
        timeout: 120_000,
        reuseExistingServer: false,
      },
    ],
  },
  iis: {
    testDir: "./e2e",
    testMatch: "ui-v2-iis-forms.spec.ts",
    outputDir: path.join(configDir, ".visual-audit", "issue-568-results"),
    workers: 1,
    reporter: "list",
    use: {
      ...devices["Desktop Chrome"],
      baseURL: "http://127.0.0.1:4174",
      trace: "retain-on-failure",
    },
    webServer: {
      command: "npm run dev -- --host 127.0.0.1 --port 4174 --strictPort",
      cwd: configDir,
      url: "http://127.0.0.1:4174",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  },
  "instrument-eod": {
    testDir: "./e2e",
    testMatch: "instrument-eod.acceptance.ts",
    outputDir: path.join(os.tmpdir(), "hermes-instrument-eod-playwright"),
    workers: 1,
    retries: 0,
    reporter: "list",
    use: {
      baseURL: `http://127.0.0.1:${process.env.HERMES_EOD_TEST_PORT ?? "18860"}`,
      locale: "ru-RU",
      trace: "retain-on-failure",
    },
    webServer: {
      command: "uv run --locked --group dev python ../frontend/e2e/instrument_eod_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: `http://127.0.0.1:${process.env.HERMES_EOD_TEST_PORT ?? "18860"}/api/health`,
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  "instrument-income": {
    testDir: "./e2e",
    testMatch: "instrument-income.acceptance.ts",
    outputDir: path.join(os.tmpdir(), "hermes-instrument-income-playwright"),
    workers: 1,
    retries: 0,
    reporter: "list",
    use: {
      baseURL: `http://127.0.0.1:${process.env.HERMES_INCOME_TEST_PORT ?? "18858"}`,
      locale: "ru-RU",
      trace: "retain-on-failure",
    },
    webServer: {
      command: "uv run --locked --group dev python ../frontend/e2e/instrument_income_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: `http://127.0.0.1:${process.env.HERMES_INCOME_TEST_PORT ?? "18858"}/api/health`,
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  "instrument-trades": {
    testDir: "./e2e",
    testMatch: "instrument-trades.acceptance.ts",
    outputDir: path.join(os.tmpdir(), "hermes-instrument-trades-playwright"),
    workers: 1,
    retries: 0,
    reporter: "list",
    use: {
      baseURL: `http://127.0.0.1:${process.env.HERMES_TRADES_TEST_PORT ?? "18862"}`,
      locale: "ru-RU",
      trace: "retain-on-failure",
    },
    webServer: {
      command: "uv run --locked --group dev python ../frontend/e2e/instrument_trades_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: `http://127.0.0.1:${process.env.HERMES_TRADES_TEST_PORT ?? "18862"}/api/health`,
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  "instrument-uat": {
    testDir: "./e2e",
    testMatch: "instrument-uat.acceptance.ts",
    outputDir: path.join(os.tmpdir(), "hermes-instrument-uat-playwright"),
    workers: 1,
    retries: 0,
    reporter: "list",
    use: { baseURL: "http://127.0.0.1:18868", locale: "ru-RU", trace: "retain-on-failure" },
    webServer: {
      command:
        "uv run --locked --offline --no-sync python ../frontend/e2e/instrument_uat_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: "http://127.0.0.1:18868/api/health",
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  "instrument-what-if": {
    testDir: "./e2e",
    testMatch: "instrument-what-if.acceptance.ts",
    outputDir: path.join(os.tmpdir(), "hermes-instrument-what-if-playwright"),
    workers: 1,
    retries: 0,
    reporter: "list",
    use: {
      baseURL: `http://127.0.0.1:${process.env.HERMES_WHAT_IF_TEST_PORT ?? "18865"}`,
      locale: "ru-RU",
      trace: "retain-on-failure",
    },
    webServer: {
      command: "uv run --locked --group dev python ../frontend/e2e/instrument_what_if_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: `http://127.0.0.1:${process.env.HERMES_WHAT_IF_TEST_PORT ?? "18865"}/api/health`,
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  "month-editor": {
    testDir: "./e2e",
    testMatch: "ui-v2-month-editor.visual.spec.ts",
    outputDir: path.join(os.tmpdir(), "hermes-finance-month-editor-playwright"),
    workers: 1,
    reporter: "list",
    use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:1607" },
    webServer: {
      command: "node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 1607 --strictPort",
      cwd: configDir,
      url: "http://127.0.0.1:1607",
      timeout: 120_000,
      reuseExistingServer: false,
    },
  },
  "monthly-close": {
    testDir: "./e2e",
    testMatch: "monthly-close.acceptance.ts",
    outputDir: path.join(os.tmpdir(), "hermes-571-playwright"),
    workers: 1,
    retries: 0,
    reporter: "list",
    use: { baseURL: "http://127.0.0.1:18757", locale: "ru-RU", trace: "retain-on-failure" },
    webServer: {
      command: "uv run --no-dev --locked python ../frontend/e2e/monthly_close_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: "http://127.0.0.1:18757/api/health",
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  payout: {
    testDir: "./e2e",
    testMatch: "payout.acceptance.ts",
    workers: 1,
    retries: 0,
    outputDir:
      process.env.HERMES_SYNTHETIC_PAYOUT_OUTPUT ?? path.join(os.tmpdir(), "hermes-payout-browser"),
    use: {
      baseURL: `http://127.0.0.1:${process.env.HERMES_SYNTHETIC_PAYOUT_PORT ?? "18468"}`,
      locale: "ru-RU",
      screenshot: "only-on-failure",
      trace: "retain-on-failure",
    },
    webServer: {
      command: `"${process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"}" -m uvicorn payout_browser_fixture:create_browser_app --factory --host 127.0.0.1 --port ${process.env.HERMES_SYNTHETIC_PAYOUT_PORT ?? "18468"}`,
      cwd: path.resolve(configDir, "../backend"),
      env: { PYTHONPATH: path.resolve(configDir, "../backend/tests") },
      url: `http://127.0.0.1:${process.env.HERMES_SYNTHETIC_PAYOUT_PORT ?? "18468"}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  },
  provisional: {
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
      cwd: path.resolve(configDir, "../backend"),
      url: "http://127.0.0.1:18790/api/health",
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  "bond-source": {
    testDir: "./e2e",
    testMatch: "bond-source.acceptance.ts",
    outputDir: path.join(os.tmpdir(), "hermes-bond-source-playwright"),
    workers: 1,
    retries: 0,
    reporter: "list",
    use: {
      baseURL: `http://127.0.0.1:${process.env.HERMES_BOND_TEST_PORT ?? "18791"}`,
      locale: "ru-RU",
      trace: "retain-on-failure",
      launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH },
    },
    webServer: {
      command: "uv run --locked --group dev python ../frontend/e2e/bond_source_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: `http://127.0.0.1:${process.env.HERMES_BOND_TEST_PORT ?? "18791"}/api/health`,
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  "quote-mapping": {
    testDir: "./e2e",
    testMatch: "quote-mapping.acceptance.ts",
    workers: 1,
    retries: 0,
    outputDir:
      process.env.HERMES_SYNTHETIC_QUOTE_MAPPING_OUTPUT ??
      path.join(os.tmpdir(), "hermes-quote-mapping-browser"),
    use: {
      baseURL: `http://127.0.0.1:${process.env.HERMES_SYNTHETIC_QUOTE_MAPPING_PORT ?? "18469"}`,
      locale: "ru-RU",
      screenshot: "only-on-failure",
      trace: "retain-on-failure",
    },
    webServer: {
      command: `"${process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"}" -m uvicorn quote_mapping_browser_fixture:create_browser_app --factory --host 127.0.0.1 --port ${process.env.HERMES_SYNTHETIC_QUOTE_MAPPING_PORT ?? "18469"}`,
      cwd: path.resolve(configDir, "../backend"),
      env: { PYTHONPATH: path.resolve(configDir, "../backend/tests") },
      url: `http://127.0.0.1:${process.env.HERMES_SYNTHETIC_QUOTE_MAPPING_PORT ?? "18469"}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  },
  statement: {
    testDir: "./e2e",
    testMatch: "statement-import.acceptance.ts",
    outputDir: path.join(os.tmpdir(), "hermes-statement-playwright-results"),
    workers: 1,
    retries: 0,
    reporter: "list",
    use: { baseURL: "http://127.0.0.1:8000", locale: "ru-RU", trace: "retain-on-failure" },
    webServer: {
      command: "uv run --locked python ../frontend/e2e/statement_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
  "what-if": {
    testDir: "./e2e",
    testMatch: "statement-what-if.acceptance.ts",
    outputDir: path.join(os.tmpdir(), "hermes-839-playwright"),
    workers: 1,
    retries: 0,
    reporter: "list",
    use: {
      baseURL: "http://127.0.0.1:18789",
      locale: "ru-RU",
      trace: "retain-on-failure",
      launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH },
    },
    webServer: {
      command: "uv run --locked --group dev python ../frontend/e2e/statement_what_if_fixture.py",
      cwd: path.resolve(configDir, "../backend"),
      url: "http://127.0.0.1:18789/api/health",
      reuseExistingServer: false,
      timeout: 120000,
    },
  },
};

// Match Playwright's repeated/variadic --project option, including its '*' glob.
const filters: string[] = [];
const args = process.argv.slice(2);
for (let index = 0; index < args.length; index += 1) {
  const arg = args[index];
  if (arg === "--project" || arg.startsWith("--project=")) {
    if (arg.startsWith("--project=")) filters.push(arg.slice("--project=".length));
    while (index + 1 < args.length && !args[index + 1].startsWith("-")) {
      filters.push(args[++index]);
    }
  }
}
// Worker processes reload this file without the runner's CLI arguments. Keep
// their project list and settings identical to the parent invocation.
const inheritedFilters = process.env.HERMES_PLAYWRIGHT_PROJECT_FILTERS;
if (!filters.length && inheritedFilters) {
  filters.push(...(JSON.parse(inheritedFilters) as string[]));
}
process.env.HERMES_PLAYWRIGHT_PROJECT_FILTERS = JSON.stringify(filters);

const listing = args.includes("--list");
const names = Object.keys(suites);
const selectedNames = filters.length ? selectPlaywrightProjects(names, filters) : ["chromium"];
if (!listing && selectedNames.length !== 1) {
  throw new Error(
    "Run one Playwright project at a time (fixture servers share ports). Use --list to inspect multiple projects.",
  );
}
const activeSuite = suites[selectedNames[0] ?? "chromium"];
const visibleNames = filters.length || listing ? names : ["chromium"];

export default defineConfig({
  testDir: "./e2e",
  workers: activeSuite.workers,
  reporter: activeSuite.reporter,
  forbidOnly: activeSuite.forbidOnly,
  webServer: activeSuite.webServer,
  projects: visibleNames.map((name) => {
    const {
      webServer: _server,
      reporter: _reporter,
      workers: _workers,
      forbidOnly: _forbidOnly,
      ...project
    } = suites[name];
    return { name, ...project };
  }),
});
