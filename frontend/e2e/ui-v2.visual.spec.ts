import fs from "node:fs";
import path from "node:path";

import { expect, type Page, type TestInfo, test } from "@playwright/test";

import type { MonthCloseWorkflow } from "../src/api/monthCloseWorkflow";

import {
  makeUiV2ArchiveHistory,
  makeUiV2CapitalHistory,
  makeUiV2Cash,
  makeUiV2Comparison,
  makeUiV2Dashboard,
  makeUiV2Debts,
  makeUiV2Deposits,
  makeUiV2Goals,
  makeUiV2LongHistory,
  makeUiV2PassiveHistory,
  makeUiV2Performance,
  makeUiV2Positions,
  makeUiV2Properties,
  makeUiV2RiskAllocation,
  makeUiV2Workflow,
  uiV2Accounts,
  uiV2ArchiveMonths,
  uiV2CapitalMonthId,
  uiV2CapitalPreviousMonthId,
  uiV2Instruments,
  uiV2LongHistoryFirstMonthId,
  uiV2Months,
} from "../src/test/uiV2Fixtures";

type Scene = "normal" | "no-closed" | "first-closed" | "zero" | "passive-error" | "coverage";

async function installApi(page: Page, scene: Scene = "normal") {
  const firstClosed = scene === "first-closed";
  const zero = scene === "zero";
  const state = {
    passiveError: scene === "passive-error",
    workflowError: false,
    comparison: makeUiV2Comparison({ firstClosed, zero }),
    capital: makeUiV2CapitalHistory({ firstClosed, zero }),
    passive: makeUiV2PassiveHistory({ firstClosed, zero }),
    goals: makeUiV2Goals({ firstClosed, zero }),
  };
  if (scene === "coverage" && state.comparison.current) {
    state.comparison.current.portfolio_source_coverage = {
      status: "partial",
      reason_codes: ["active_account_snapshot_missing"],
      missing_account_ids: [2],
    };
    state.comparison.liquid_capital_net_delta_coverage = {
      status: "partial",
      reason_codes: ["active_account_snapshot_missing"],
      missing_account_ids: [],
    };
  }
  const unexpected: string[] = [];
  const reads: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["127.0.0.1", "localhost"].includes(url.hostname))
      unexpected.push(`external: ${url.origin}`);
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }
    reads.push(`${request.method()} ${url.pathname}${url.search}`);
    if (request.method() !== "GET") {
      unexpected.push(`${request.method()} ${url.pathname}`);
      await route.abort();
      return;
    }

    let json: unknown;
    let status = 200;
    if (url.pathname === "/api/months") {
      json =
        scene === "no-closed"
          ? [uiV2Months[1]]
          : scene === "first-closed"
            ? [uiV2Months[0], uiV2Months[1]]
            : uiV2Months;
    } else if (url.pathname === "/api/analytics/closed-report-comparison") {
      json = state.comparison;
    } else if (url.pathname === "/api/analytics/capital-composition") {
      json = state.capital;
    } else if (url.pathname === "/api/analytics/passive-income") {
      json = state.passive;
      status = state.passiveError ? 503 : 200;
    } else if (url.pathname === "/api/goals/summary") {
      json = state.goals;
    } else if (url.pathname === "/api/months/12/close-workflow") {
      json = makeUiV2Workflow();
      status = state.workflowError ? 503 : 200;
    } else {
      unexpected.push(`${request.method()} ${url.pathname}`);
      status = 404;
      json = { error: { code: "synthetic_missing", message: "Missing fixture", details: [] } };
    }
    await route.fulfill({
      status,
      json:
        status === 200
          ? json
          : { error: { code: "synthetic_error", message: "Synthetic failure", details: [] } },
    });
  });
  return { errors, reads, state, unexpected };
}

async function assertBounded(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
  const clipped = await page.locator("#v2-main button, #v2-main a").evaluateAll((elements) =>
    elements
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1);
      })
      .map((element) => element.textContent),
  );
  expect(clipped).toEqual([]);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  const dir = path.resolve(".visual-audit", testInfo.project.name);
  fs.mkdirSync(dir, { recursive: true });
  await page.screenshot({
    path: path.join(dir, `${name}.png`),
    fullPage: true,
    animations: "disabled",
  });
}

test("ui-v2 Home desktop: closed financial picture and draft CTA stay bounded", async ({
  page,
}, testInfo) => {
  const evidence = await installApi(page);
  await page.goto("/v2");
  await expect(page.getByRole("heading", { name: "Мои финансы" })).toBeVisible();
  await expect(page.getByTestId("v2-capital")).toHaveText("2 803 900 ₽");
  await expect(page.getByTestId("v2-draft-action")).toHaveAttribute(
    "href",
    "/v2/close?month=12&step=alfa_baseline",
  );
  await expect(
    page.getByRole("region", { name: "Главные показатели" }).getByRole("article"),
  ).toHaveCount(3);
  await expect(page.getByText(/последние 4 закрытых отчёта/i)).toBeVisible();
  await expect(page.getByTestId("v2-capital-history")).toHaveAttribute("data-gap-count", "2");
  await expect(page.getByTestId("v2-passive-history")).toHaveAttribute("data-point-count", "4");
  await expect(
    page.getByText("Изменение состояния, не инвестиционная доходность", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "История отчётов →" })).toHaveAttribute(
    "href",
    "/v2/reports",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-home-desktop");
  expect(evidence.reads.every((read) => read.startsWith("GET "))).toBe(true);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Home partial capital coverage stays beside the known subtotal", async ({
  page,
}, testInfo) => {
  const evidence = await installApi(page, "coverage");
  await page.goto("/v2");
  await expect(page.getByTestId("v2-capital")).toHaveText("2 803 900 ₽");
  await expect(page.getByText("Частично: нет снимка счёта")).toHaveCount(2);
  await assertBounded(page);
  await capture(page, testInfo, "issue-538-home-partial");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

for (const scene of ["no-closed", "first-closed", "zero", "passive-error"] as const) {
  test(`ui-v2 Home state ${scene}: honest partial result`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "1440x900", "State evidence captured once");
    const evidence = await installApi(page, scene);
    await page.goto("/v2");
    if (scene === "no-closed") {
      await expect(page.getByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
      await expect(page.getByTestId("v2-capital")).toHaveCount(0);
      await expect(page.getByTestId("v2-draft-action")).toBeVisible();
    } else {
      await expect(page.getByTestId("v2-capital")).toBeVisible();
      if (scene === "first-closed") {
        await expect(page.getByText("Пока нет базы сравнения")).toBeVisible();
        await expect(page.getByText("Нужны два закрытых отчёта для сравнения")).toBeVisible();
        await expect(page.getByTestId("v2-passive-history")).toHaveAttribute(
          "data-point-count",
          "1",
        );
        await expect(page.getByText("35,00%")).toBeVisible();
      }
      if (scene === "zero") {
        await expect(page.getByTestId("v2-capital")).toHaveText("0 ₽");
        await expect(page.getByTestId("v2-capital-change")).toHaveText("−2 761 300 ₽");
        await expect(page.getByTestId("v2-passive-actual")).toHaveText("0 ₽");
        await expect(page.getByTestId("v2-passive-history")).toHaveAttribute(
          "data-point-count",
          "4",
        );
        await expect(page.getByText("21,85%")).toBeVisible();
        await expect(page.getByText("10 925 ₽ из 50 000 ₽")).toBeVisible();
      }
      if (scene === "passive-error") {
        await expect(page.getByTestId("v2-passive-actual")).toHaveCount(0);
        await expect(page.getByTestId("v2-capital-history")).toBeVisible();
        await expect(page.getByText("Данные временно недоступны").first()).toBeVisible();
      }
    }
    await assertBounded(page);
    await capture(page, testInfo, `ui-v2-home-${scene}`);
    expect(evidence.unexpected).toEqual([]);
    expect(evidence.errors).toEqual([]);
  });
}

test("ui-v2 Home interactions: history windows and v1 escape preserve semantics", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Interaction proof once");
  const evidence = await installApi(page);
  await page.goto("/v2?month=12&step=actual_payouts");
  await expect(page.getByTestId("v2-capital")).toBeVisible();
  await page.getByRole("button", { name: "3 месяца" }).click();
  await expect(page.getByText(/последние 3 закрытых отчёта/i)).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Открыть этот раздел в предыдущем интерфейсе →" }),
  ).toHaveAttribute("href", "/months/12/close#actual_payouts");
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Мои финансы" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "К содержанию" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#v2-main")).toBeFocused();
  await expect(page.locator("#v2-main")).toHaveCSS("outline-style", "solid");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 back to top desktop: appears after meaningful scroll and restores main focus", async ({
  page,
}, testInfo) => {
  test.skip(
    !["chromium", "1440x900"].includes(testInfo.project.name),
    "Back-to-top browser evidence runs once per desktop harness",
  );
  const evidence = await installApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/v2");
  await expect(page.getByRole("heading", { name: "Мои финансы" })).toBeVisible();

  const backToTop = page.getByRole("button", { name: "Наверх" });
  await expect(backToTop).toHaveCount(0);
  await page.evaluate(() => window.scrollTo({ top: 360, behavior: "auto" }));
  await expect(backToTop).toBeVisible();
  await expect(backToTop).toHaveAttribute("aria-controls", "v2-main");

  await capture(page, testInfo, "ui-v2-back-to-top-desktop");
  await backToTop.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#v2-main")).toBeFocused();
  await expect
    .poll(() => page.evaluate(() => Math.max(window.scrollY, document.documentElement.scrollTop)))
    .toBeLessThan(320);

  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 back to top narrow: remains inside the viewport and keyboard usable", async ({
  page,
}, testInfo) => {
  test.skip(
    !["chromium", "1440x900"].includes(testInfo.project.name),
    "Back-to-top browser evidence runs once per desktop harness",
  );
  const evidence = await installApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2");
  await expect(page.getByRole("heading", { name: "Мои финансы" })).toBeVisible();

  await page.evaluate(() => window.scrollTo({ top: 360, behavior: "auto" }));
  const backToTop = page.getByRole("button", { name: "Наверх" });
  await expect(backToTop).toBeVisible();
  const box = await backToTop.boundingBox();
  expect(box).not.toBeNull();
  if (!box) throw new Error("Back-to-top button has no visible bounding box");
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  await assertBounded(page);

  await capture(page, testInfo, "ui-v2-back-to-top-narrow");
  await backToTop.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#v2-main")).toBeFocused();
  await expect
    .poll(() => page.evaluate(() => Math.max(window.scrollY, document.documentElement.scrollTop)))
    .toBeLessThan(320);

  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Home narrow: hierarchy, long values and actions remain operable", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "390px evidence stored with reference desktop");
  const evidence = await installApi(page);
  if (!evidence.state.comparison.current)
    throw new Error("Synthetic comparison has no current report");
  evidence.state.comparison.current.liquid_capital_net.amount = "9876543210123.45";
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2");
  await expect(page.getByTestId("v2-capital")).toContainText("9 876 543 210 123,45 ₽");
  await expect(page.getByTestId("v2-draft-action")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-home-narrow");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Home draft workflow error never exposes a stale recommendation", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Failure-state proof once");
  const evidence = await installApi(page);
  evidence.state.workflowError = true;
  await page.goto("/v2");
  await expect(page.getByText("Август 2031 ещё не закрыт")).toBeVisible();
  await expect(page.getByTestId("v2-draft-action")).toHaveCount(0);
  await expect(page.getByTestId("v2-capital")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-home-draft-action-error");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

function closeReadyWorkflow(): MonthCloseWorkflow {
  const workflow = structuredClone(makeUiV2Workflow());
  const finalStep = workflow.steps.find((step) => step.id === "final_review_close");
  if (!finalStep) throw new Error("Synthetic final close step is missing");
  finalStep.primary_action = {
    id: "confirm_close",
    label: "Закрыть месяц",
    target: "confirm_close",
  };
  finalStep.state = "ready";
  return workflow;
}

function closePersistedWorkflow(workflow: MonthCloseWorkflow): MonthCloseWorkflow {
  const closed = structuredClone(workflow);
  closed.month.status = "closed";
  closed.recommended_step_id = "next_month_outlook";
  if (closed.final_review.available) closed.final_review.month_header.status = "closed";
  for (const step of closed.steps) step.primary_action = null;
  closed.outlook = {
    available: false,
    reason_code: "no_known_dated_events",
    source_month: { ...closed.month },
    next_month: null,
    upcoming_14_days: null,
    upcoming_30_days: null,
    known_event_count: 0,
    evidence_version: "ui-v2-browser-closed-v1",
  };
  return closed;
}

async function installCloseApi(page: Page) {
  const state = {
    workflow: closeReadyWorkflow(),
    months: structuredClone(uiV2Months),
  };
  const errors: string[] = [];
  const unexpected: string[] = [];
  const requests: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["127.0.0.1", "localhost"].includes(url.hostname)) unexpected.push(url.origin);
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }
    const method = request.method();
    requests.push(`${method} ${url.pathname}${url.search}`);
    let json: unknown;
    if (method === "POST" && url.pathname === "/api/months/12/close") {
      state.workflow = closePersistedWorkflow(state.workflow);
      state.months = state.months.map((month) =>
        month.id === 12 ? { ...month, status: "closed" as const } : month,
      );
      json = state.workflow.month;
    } else if (method !== "GET") {
      unexpected.push(`${method} ${url.pathname}`);
      await route.abort();
      return;
    } else if (url.pathname === "/api/months") {
      json = state.months;
    } else if (url.pathname === "/api/months/12/close-workflow") {
      json = state.workflow;
    } else if (url.pathname === "/api/accounts" || url.pathname === "/api/instruments") {
      json = [];
    } else if (url.pathname === "/api/health") {
      json = { status: "ok", version: "0.9.0-synthetic" };
    } else if (url.pathname === "/api/analytics/closed-report-comparison") {
      json = makeUiV2Comparison();
    } else if (url.pathname === "/api/analytics/capital-composition") {
      json = makeUiV2CapitalHistory();
    } else if (url.pathname === "/api/analytics/passive-income") {
      json = makeUiV2PassiveHistory();
    } else if (url.pathname === "/api/goals/summary") {
      json = makeUiV2Goals();
    } else {
      unexpected.push(`${method} ${url.pathname}`);
      await route.fulfill({
        status: 404,
        json: { error: { code: "synthetic_missing", message: "Missing fixture", details: [] } },
      });
      return;
    }
    await route.fulfill({ status: 200, json });
  });
  return { errors, requests, state, unexpected };
}

test("ui-v2 Monthly Close desktop: provider handoff, final review, Close and Home journey", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Interaction proof once");
  const evidence = await installCloseApi(page);
  await page.goto("/v2");
  await page.getByTestId("v2-draft-action").click();
  await expect(page).toHaveURL(/\/v2\/close\?month=12&step=alfa_baseline$/);
  await expect(page.getByRole("heading", { name: "Сверить состав портфеля" })).toBeVisible();

  await page.getByRole("link", { name: "Открыть предпросмотр Alfa" }).click();
  await expect(page).toHaveURL(/\/accounts\?from=monthly-close-v2&step=alfa_baseline&monthId=12$/);
  await expect(page.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
    "href",
    "/v2/close?month=12&step=alfa_baseline",
  );
  await page.getByRole("link", { name: "Вернуться к закрытию" }).click();

  await page.getByRole("link", { name: "Проверить итоги и закрыть месяц" }).first().click();
  await expect(page.getByRole("heading", { name: /Итоги.*2031/ })).toBeVisible();
  await page.getByRole("button", { name: "Закрыть месяц" }).click();
  await expect(page.getByRole("alertdialog", { name: "Закрыть месяц?" })).toBeVisible();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Месяц зафиксирован" })).toBeVisible();
  await expect(page.getByText(/из 8 шагов/)).toHaveCount(0);
  await capture(page, testInfo, "ui-v2-close-closed-desktop");

  await page.getByRole("link", { name: "Вернуться в «Мои финансы»" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Мои финансы" })).toBeVisible();
  expect(
    evidence.requests.filter((request) => request === "POST /api/months/12/close"),
  ).toHaveLength(1);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Monthly Close narrow: current action and collapsed step list stay bounded", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "390px evidence stored with reference desktop");
  const evidence = await installCloseApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2/close?month=12&step=actual_payouts");
  await expect(page.getByRole("heading", { name: "Проверить полученные выплаты" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Выбрать выписку с выплатами" })).toBeVisible();
  const steps = page.locator("details").filter({ hasText: "Шаги закрытия" });
  await expect(steps).not.toHaveAttribute("open", "");
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-close-narrow");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

type CapitalScene = "normal" | "no-closed" | "first-closed" | "zero" | "partial" | "coverage";

async function installCapitalApi(page: Page, scene: CapitalScene = "normal") {
  const firstClosed = scene === "first-closed";
  const zero = scene === "zero";
  const partial = scene === "partial";
  const state = {
    monthsError: false,
    propertiesError: partial,
    riskError: partial,
    instrumentsError: partial,
    comparison: makeUiV2Comparison({ firstClosed, zero }),
    composition: makeUiV2CapitalHistory({ firstClosed, zero }),
    risk: makeUiV2RiskAllocation(),
    dashboard: makeUiV2Dashboard(),
    cash: makeUiV2Cash(),
    deposits: makeUiV2Deposits(),
    positions: makeUiV2Positions(),
    debts: makeUiV2Debts(),
    properties: makeUiV2Properties(),
    performance: makeUiV2Performance(),
  };
  if (scene === "coverage" && state.comparison.current) {
    state.comparison.current.portfolio_source_coverage = {
      status: "partial",
      reason_codes: ["active_account_snapshot_missing"],
      missing_account_ids: [2],
    };
    const latest = state.composition.points.at(-1);
    if (!latest) throw new Error("Missing current composition fixture");
    latest.portfolio_source_coverage = state.comparison.current.portfolio_source_coverage;
  }
  const unexpected: string[] = [];
  const reads: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["127.0.0.1", "localhost"].includes(url.hostname))
      unexpected.push(`external: ${url.origin}`);
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }
    reads.push(`${request.method()} ${url.pathname}${url.search}`);
    if (request.method() !== "GET") {
      unexpected.push(`${request.method()} ${url.pathname}`);
      await route.abort();
      return;
    }
    let json: unknown;
    let status = 200;
    if (url.pathname === "/api/months") {
      json =
        scene === "no-closed"
          ? [uiV2Months[1]]
          : scene === "first-closed"
            ? [uiV2Months[0], uiV2Months[1]]
            : uiV2Months;
      status = state.monthsError ? 503 : 200;
    } else if (url.pathname === "/api/analytics/closed-report-comparison") {
      json = state.comparison;
    } else if (url.pathname === "/api/analytics/capital-composition") {
      json = state.composition;
    } else if (url.pathname === "/api/analytics/risk-allocation") {
      json = state.risk;
      status = state.riskError ? 503 : 200;
    } else if (url.pathname === `/api/months/${uiV2CapitalMonthId}/dashboard`) {
      json = state.dashboard;
    } else if (url.pathname === "/api/cash-balances") {
      json = state.cash;
    } else if (url.pathname === "/api/deposits") {
      json = state.deposits;
    } else if (url.pathname === "/api/positions") {
      json = state.positions;
    } else if (url.pathname === "/api/debts") {
      json = state.debts;
    } else if (url.pathname === "/api/properties") {
      json = state.properties;
      status = state.propertiesError ? 503 : 200;
    } else if (url.pathname === "/api/accounts") {
      json = uiV2Accounts;
    } else if (url.pathname === "/api/instruments") {
      json = uiV2Instruments;
      status = state.instrumentsError ? 503 : 200;
    } else if (url.pathname === "/api/performance/attribution") {
      json = state.performance.attribution;
    } else if (url.pathname === "/api/performance/xirr") {
      json = state.performance.xirr;
    } else if (url.pathname === "/api/performance/twrr") {
      json = state.performance.twrr;
    } else {
      unexpected.push(`${request.method()} ${url.pathname}`);
      status = 404;
      json = { error: { code: "synthetic_missing", message: "Missing fixture", details: [] } };
    }
    await route.fulfill({
      status,
      json:
        status === 200
          ? json
          : { error: { code: "synthetic_error", message: "Synthetic failure", details: [] } },
    });
  });
  return { errors, reads, state, unexpected };
}

test("ui-v2 Capital desktop: closed composition, accounts and performance stay bounded", async ({
  page,
}, testInfo) => {
  const evidence = await installCapitalApi(page);
  await page.goto("/v2/capital");
  await expect(page.getByRole("heading", { level: 1, name: "Капитал" })).toBeVisible();
  await expect(page.getByTestId("capital-net")).toHaveText("2 803 900 ₽");
  await expect(page.getByTestId("capital-assets")).toHaveText("3 203 900 ₽");
  await expect(page.getByTestId("capital-debts")).toHaveText("− 400 000 ₽");
  await expect(page.getByTestId("capital-draft-note")).toContainText("Август 2031 ещё не закрыт");
  await expect(page.getByTestId("capital-composition")).toHaveAttribute("data-point-count", "4");
  await expect(page.getByTestId("capital-change-list")).toBeVisible();
  await expect(page.getByTestId("capital-class-cash")).toContainText("803 900 ₽");
  await expect(page.getByTestId("capital-bucket-unassigned_cash")).toContainText(
    "Наличные без привязки к счёту",
  );
  await expect(page.getByTestId("capital-holding-cash-702")).toContainText(
    "не входит в ликвидный капитал",
  );
  await expect(page.getByTestId("capital-pair-21")).toContainText("1 000 000 ₽");
  await expect(page.getByTestId("capital-pair-gap")).toBeVisible();
  await expect(page.getByTestId("capital-pair-22")).toContainText("—");
  await expect(page.getByTestId("capital-performance-bridge")).toContainText("+42 600 ₽");
  await expect(page.getByText("Разница: капитал − ипотека")).toBeVisible();
  await expect(
    page.locator(".capital-composition-chart path[fill='#5f7e9e']").first(),
  ).toBeVisible();
  expect(await page.locator(".capital-composition-chart path[fill='#27734c']").count()).toBe(0);
  await expect(page.getByText("164,9%", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Все отчёты →" })).toHaveAttribute(
    "href",
    "/v2/reports",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-capital-desktop");
  expect(evidence.reads.every((read) => read.startsWith("GET "))).toBe(true);
  expect(evidence.reads.some((read) => read.includes("forecast_version=v1"))).toBe(true);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Capital partial coverage keeps the known net", async ({ page }, testInfo) => {
  const evidence = await installCapitalApi(page, "coverage");
  await page.goto("/v2/capital");
  await expect(page.getByTestId("capital-net")).toHaveText("2 803 900 ₽");
  await expect(page.getByText("Частично: нет снимка счёта")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "issue-538-capital-partial");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Capital narrow: long values, collapsed performance and actions stay operable", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "390px evidence stored with reference desktop");
  const evidence = await installCapitalApi(page);
  if (!evidence.state.comparison.current)
    throw new Error("Synthetic comparison has no current report");
  evidence.state.comparison.current.liquid_capital_net.amount = "9876543210123.45";
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2/capital");
  await expect(page.getByTestId("capital-net")).toContainText("9 876 543 210 123,45 ₽");
  const disclosure = page.locator("details").first();
  await expect(disclosure).not.toHaveAttribute("open", "");
  await page.locator("details summary").first().click();
  await expect(page.getByTestId("capital-performance-xirr")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-capital-narrow");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

for (const scene of ["no-closed", "first-closed", "zero", "partial"] as const) {
  test(`ui-v2 Capital state ${scene}: honest partial result`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "1440x900", "State evidence captured once");
    const evidence = await installCapitalApi(page, scene);
    await page.goto("/v2/capital");
    if (scene === "no-closed") {
      await expect(page.getByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
      await expect(page.getByTestId("capital-net")).toHaveCount(0);
    } else if (scene === "zero") {
      await expect(page.getByTestId("capital-net")).toHaveText("0 ₽");
      await expect(page.getByTestId("capital-class-cash")).toContainText("0 ₽");
      await expect(page.getByTestId("capital-class-cash")).toContainText("—");
    } else {
      await expect(page.getByTestId("capital-net")).toBeVisible();
      if (scene === "first-closed") {
        await expect(
          page.getByText("Нужны два закрытых отчёта для сравнения").first(),
        ).toBeVisible();
        await expect(
          page.getByText(/Нужны два закрытых отчёта для расчёта за период/),
        ).toBeVisible();
      }
      if (scene === "partial") {
        await expect(page.getByText("Данные временно недоступны").first()).toBeVisible();
        await expect(page.getByTestId("capital-composition")).toBeVisible();
        await expect(page.getByTestId("capital-holding-cash-701")).toBeVisible();
        await expect(page.getByTestId("capital-holding-deposit-601")).toBeVisible();
        await expect(page.getByTestId("capital-holding-position-501")).toHaveCount(0);
        await expect(page.getByTestId("capital-pair-21")).toBeVisible();
      }
    }
    await assertBounded(page);
    await capture(page, testInfo, `ui-v2-capital-${scene}`);
    expect(evidence.unexpected).toEqual([]);
    expect(evidence.errors).toEqual([]);
  });
}

test("ui-v2 Capital interactions: filters, windows and the v1 escape preserve semantics", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Interaction proof once");
  const evidence = await installCapitalApi(page);
  await page.goto(`/v2/capital?month=${uiV2CapitalPreviousMonthId}&step=actual_payouts`);
  await expect(page.getByTestId("capital-net")).toBeVisible();
  await page.getByRole("button", { name: "3 месяца" }).click();
  await expect(page.getByTestId("capital-composition")).toHaveAttribute("data-point-count", "3");
  await page.getByTestId("capital-class-stocks").click();
  await expect(page.getByText("Фильтр: Акции")).toBeVisible();
  await expect(page.getByTestId("capital-holding-position-501")).toBeVisible();
  await page.getByRole("button", { name: "Сбросить" }).click();
  await page.getByTestId("capital-bucket-account:1").click();
  await expect(page.getByTestId("capital-holding-deposit-601")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Открыть этот раздел в предыдущем интерфейсе →" }),
  ).toHaveAttribute("href", `/months/${uiV2CapitalPreviousMonthId}/close#actual_payouts`);
  await expect(page.getByRole("link", { name: "Мои финансы", exact: true })).toHaveAttribute(
    "href",
    "/v2",
  );
  await expect(page.getByRole("link", { name: "Капитал" })).toHaveAttribute("aria-current", "page");
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-capital-interactions");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

/* ------------------------------------------------------------------ *
 * Contextual report history / archive (#427).
 * Synthetic fixtures only: no owner runtime, no provider, read-only GET.
 * ------------------------------------------------------------------ */

type ReportsScene =
  | "archive"
  | "no-closed"
  | "first-closed"
  | "money-error"
  | "report"
  | "report-partial"
  | "report-coverage"
  | "report-older-than-window";

/** 2030-12: older than the latest twelve CLOSED reports (2031-01 … 2031-12). */
const olderReportId = uiV2LongHistoryFirstMonthId + 11;

async function installReportsApi(page: Page, scene: ReportsScene = "archive") {
  const report = scene === "report" || scene === "report-partial" || scene === "report-coverage";
  const olderThanWindow = scene === "report-older-than-window";
  const long = olderThanWindow ? makeUiV2LongHistory({ count: 24 }) : null;
  const rowMonthId = olderThanWindow ? olderReportId : uiV2CapitalPreviousMonthId;
  const months =
    long !== null
      ? long.months
      : scene === "no-closed"
        ? [uiV2Months[1]]
        : scene === "first-closed"
          ? [uiV2Months[0], uiV2Months[1]]
          : uiV2ArchiveMonths;
  const state = {
    monthsError: false,
    compositionError: scene === "money-error",
    riskError: scene === "report-partial",
    instrumentsError: scene === "report-partial",
    composition:
      long !== null ? long.history : report ? makeUiV2CapitalHistory() : makeUiV2ArchiveHistory(),
    risk: makeUiV2RiskAllocation({ monthId: rowMonthId }),
    cash: makeUiV2Cash({ monthId: rowMonthId }),
    deposits: makeUiV2Deposits({ monthId: rowMonthId }),
    positions: makeUiV2Positions({ monthId: rowMonthId }),
  };
  if (scene === "report-coverage") {
    const selected = state.composition.points.find(
      (point) => point.reporting_month_id === rowMonthId,
    );
    if (!selected) throw new Error("Missing selected report fixture");
    selected.portfolio_source_coverage = {
      status: "partial",
      reason_codes: ["active_account_snapshot_missing"],
      missing_account_ids: [2],
    };
  }
  const unexpected: string[] = [];
  const reads: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["127.0.0.1", "localhost"].includes(url.hostname))
      unexpected.push(`external: ${url.origin}`);
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }
    reads.push(`${request.method()} ${url.pathname}${url.search}`);
    if (request.method() !== "GET") {
      unexpected.push(`${request.method()} ${url.pathname}`);
      await route.abort();
      return;
    }
    let json: unknown;
    let status = 200;
    if (url.pathname === "/api/months") {
      json = months;
      status = state.monthsError ? 503 : 200;
    } else if (url.pathname === "/api/analytics/capital-composition") {
      json = state.composition;
      status = state.compositionError ? 503 : 200;
    } else if (url.pathname === "/api/analytics/risk-allocation") {
      json = state.risk;
      status = state.riskError ? 503 : 200;
    } else if (url.pathname === "/api/cash-balances") {
      json = state.cash;
    } else if (url.pathname === "/api/deposits") {
      json = state.deposits;
    } else if (url.pathname === "/api/positions") {
      json = state.positions;
    } else if (url.pathname === "/api/accounts") {
      json = uiV2Accounts;
    } else if (url.pathname === "/api/instruments") {
      json = uiV2Instruments;
      status = state.instrumentsError ? 503 : 200;
    } else {
      unexpected.push(`${request.method()} ${url.pathname}`);
      status = 404;
      json = { error: { code: "synthetic_missing", message: "Missing fixture", details: [] } };
    }
    await route.fulfill({
      status,
      json:
        status === 200
          ? json
          : { error: { code: "synthetic_error", message: "Synthetic failure", details: [] } },
    });
  });
  return { errors, reads, state, unexpected };
}

test("ui-v2 reports archive desktop: year groups, gaps and the current report stay bounded", async ({
  page,
}, testInfo) => {
  const evidence = await installReportsApi(page);
  await page.goto("/v2/reports");
  await expect(page.getByRole("heading", { level: 1, name: "Отчёты" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "2031" })).toBeVisible();
  await expect(page.getByTestId("reports-row-91")).toContainText("Текущий отчёт");
  await expect(page.getByTestId("reports-row-91")).toContainText("2 803 900 ₽");
  await expect(page.getByTestId("reports-row-90")).toContainText("2 761 300 ₽");
  await expect(page.getByTestId("reports-row-90")).toContainText("− 390 000 ₽");
  await expect(page.getByTestId("reports-gap-2031-6")).toContainText("отчёта нет");
  await expect(page.getByTestId("reports-row-12")).toHaveCount(0);
  await expect(page.getByTestId("reports-draft-note")).toContainText("Август 2031 ещё не закрыт");
  await expect(page.getByTestId("reports-year-2030")).toContainText("Ноябрь 2030");
  await expect(page.getByRole("link", { name: "Месяцы в предыдущем интерфейсе →" })).toBeVisible();
  const archiveLayout = await page.getByTestId("reports-row-91").evaluate((row) => {
    const cells = Array.from(row.children).map((cell) => cell.getBoundingClientRect());
    const action = row.querySelector("td:last-child a")?.getBoundingClientRect();
    return {
      cellCount: cells.length,
      tableLayout: getComputedStyle(row.closest("table") as HTMLTableElement).tableLayout,
      actionGap: action && cells.at(-2) ? action.left - cells.at(-2).right : -1,
      widths: cells.map((cell) => cell.width),
    };
  });
  expect(archiveLayout.cellCount).toBe(7);
  expect(archiveLayout.tableLayout).toBe("fixed");
  expect(archiveLayout.actionGap).toBeGreaterThanOrEqual(12);
  expect(archiveLayout.widths.every((width) => width > 0)).toBe(true);
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-reports-archive-desktop");
  expect(evidence.reads.every((read) => read.startsWith("GET "))).toBe(true);
  // No extra endpoint on the archive path, regardless of duplicate dev-mode reads.
  expect([...new Set(evidence.reads.map((read) => read.split(" ")[1]))].sort()).toEqual([
    "/api/analytics/capital-composition",
    "/api/months",
  ]);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("issue 538 archive keeps a known subtotal beside its source coverage", async ({
  page,
}, testInfo) => {
  const evidence = await installReportsApi(page);
  const selected = evidence.state.composition.points.find(
    (point) => point.reporting_month_id === uiV2CapitalPreviousMonthId,
  );
  if (!selected) throw new Error("Missing archive fixture point");
  selected.portfolio_source_coverage = {
    status: "partial",
    reason_codes: ["active_account_snapshot_missing"],
    missing_account_ids: [2],
  };
  await page.goto("/v2/reports");
  const row = page.getByTestId(`reports-row-${uiV2CapitalPreviousMonthId}`);
  await expect(row).toContainText("2 761 300 ₽");
  await expect(row).toContainText("Частично: нет снимка счёта");
  const overlap = await row.evaluate((element) => {
    const note = element.querySelector('[data-testid="portfolio-coverage-note"]');
    const assets = element.querySelectorAll("td")[4];
    if (!note || !assets) throw new Error("Missing archive coverage or assets cell");
    return note.getBoundingClientRect().right > assets.getBoundingClientRect().left;
  });
  expect(overlap).toBe(false);
  await capture(page, testInfo, "issue-538-archive-partial");
  expect(evidence.errors).toEqual([]);
  expect(evidence.unexpected).toEqual([]);
});

test("ui-v2 reports archive narrow: rows stay readable as cards", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "390px evidence stored with reference desktop");
  const evidence = await installReportsApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2/reports");
  await expect(page.getByTestId("reports-row-90")).toContainText("2 761 300 ₽");
  await expect(page.getByTestId("reports-gap-2031-6")).toContainText("отчёта нет");
  await expect(page.getByTestId("reports-row-90")).toHaveCSS("display", "block");
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-reports-archive-narrow");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

for (const scene of ["no-closed", "first-closed", "money-error"] as const) {
  test(`ui-v2 reports archive state ${scene}: honest partial result`, async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "1440x900", "State evidence captured once");
    const evidence = await installReportsApi(page, scene);
    await page.goto("/v2/reports");
    if (scene === "no-closed") {
      await expect(page.getByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
      await expect(page.getByTestId("reports-archive")).toHaveCount(0);
    } else if (scene === "first-closed") {
      await expect(page.getByTestId("reports-single-note")).toBeVisible();
      await expect(page.getByText("отчёта нет")).toHaveCount(0);
    } else {
      await expect(page.getByTestId("reports-archive")).toHaveAttribute(
        "data-money-state",
        "unavailable",
      );
      await expect(page.getByTestId("reports-row-90")).toContainText("—");
    }
    await assertBounded(page);
    await capture(page, testInfo, `ui-v2-reports-archive-${scene}`);
    expect(evidence.unexpected).toEqual([]);
    expect(evidence.errors).toEqual([]);
  });
}

test("ui-v2 historical report desktop: context, values and place in history stay bounded", async ({
  page,
}, testInfo) => {
  const evidence = await installReportsApi(page, "report");
  await page.goto(`/v2/reports/${uiV2CapitalPreviousMonthId}`);
  await expect(page.getByRole("heading", { level: 1, name: "Исторический отчёт" })).toBeVisible();
  await expect(page.getByTestId("v2-report-context")).toHaveAttribute("data-context", "historical");
  await expect(page.getByTestId("v2-report-context")).toContainText("Май 2031");
  await expect(page.getByTestId("v2-report-context")).toContainText("Снимок 31.05.2031");
  await expect(page.getByTestId("report-net")).toHaveText("2 761 300 ₽");
  await expect(page.getByTestId("report-assets")).toHaveText("3 151 300 ₽");
  await expect(page.getByTestId("report-debts")).toHaveText("− 390 000 ₽");
  await expect(page.getByTestId("report-class-cash")).toContainText("751 300 ₽");
  await expect(page.getByTestId("report-history")).toBeVisible();
  await expect(page.locator('[data-highlight-key="2031-05"]')).toHaveCount(1);
  await expect(page.getByTestId("report-neighbour-previous")).toHaveAttribute(
    "href",
    "/v2/reports/89",
  );
  await expect(page.getByTestId("report-neighbour-next")).toHaveAttribute("href", "/v2/reports/91");
  await expect(page.getByTestId("report-change-unavailable")).toContainText(
    "Изменение между отчётами",
  );
  await expect(
    page.getByText(/Поздние цены, остатки и позиции никогда не подставляются/),
  ).toBeVisible();
  await expect(page.getByTestId("report-holding-deposit-601")).toBeVisible();
  await expect(page.getByTestId("report-top-positions")).toBeVisible();
  await expect(page.getByText(/XIRR|TWRR/)).toHaveCount(0);
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-report-desktop");
  expect(evidence.reads.every((read) => read.startsWith("GET "))).toBe(true);
  expect(evidence.reads.some((read) => read.includes("/api/performance/"))).toBe(false);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 report partial source coverage stays beside the historical value", async ({
  page,
}, testInfo) => {
  const evidence = await installReportsApi(page, "report-coverage");
  await page.goto(`/v2/reports/${uiV2CapitalPreviousMonthId}`);
  await expect(page.getByTestId("report-net")).toHaveText("2 761 300 ₽");
  await expect(page.getByText("Частично: нет снимка счёта")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "issue-538-report-partial");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 historical report narrow: header, values and handoff stay operable", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "390px evidence stored with reference desktop");
  const evidence = await installReportsApi(page, "report");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/v2/reports/${uiV2CapitalPreviousMonthId}`);
  await expect(page.getByTestId("report-net")).toContainText("2 761 300 ₽");
  await expect(page.getByRole("link", { name: "← Все отчёты" })).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-report-narrow");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 historical report partial: one failed widget never blanks the report", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Failure-state proof once");
  const evidence = await installReportsApi(page, "report-partial");
  await page.goto(`/v2/reports/${uiV2CapitalPreviousMonthId}`);
  await expect(page.getByTestId("report-net")).toContainText("2 761 300 ₽");
  await expect(page.getByText("Данные временно недоступны").first()).toBeVisible();
  await expect(page.getByTestId("report-holding-cash-701")).toBeVisible();
  await expect(page.getByTestId("report-holding-position-501")).toHaveCount(0);
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-report-partial");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 historical report contextual window: an older report keeps its highlight for 3 and 12", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Regression evidence captured once");
  const evidence = await installReportsApi(page, "report-older-than-window");
  await page.goto(`/v2/reports/${olderReportId}`);
  const history = page.getByTestId("report-history");

  // 2030-12 is older than the latest twelve CLOSED reports, so the window must end
  // at the opened report instead of sliding to latest-global history.
  await expect(history).toHaveAttribute("data-point-count", "12");
  await expect(history).toHaveAttribute("data-window-last-id", String(olderReportId));
  await expect(history.locator('[data-highlight-key="2030-12"]')).toHaveCount(1);
  await expect(page.getByText(/окно заканчивается открытым отчётом/)).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-report-contextual-window-12");

  await page.getByRole("button", { name: "3 месяца" }).click();
  await expect(history).toHaveAttribute("data-point-count", "3");
  await expect(history).toHaveAttribute("data-window-last-id", String(olderReportId));
  await expect(history.locator('[data-highlight-key="2030-12"]')).toHaveCount(1);
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-report-contextual-window-3");

  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

for (const scene of ["draft", "unknown", "current"] as const) {
  test(`ui-v2 historical report deep link ${scene}: current and historical never blur`, async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "1440x900", "State evidence captured once");
    const evidence = await installReportsApi(page, "report");
    const path =
      scene === "draft"
        ? "/v2/reports/12"
        : scene === "unknown"
          ? "/v2/reports/999"
          : `/v2/reports/${uiV2CapitalMonthId}`;
    await page.goto(path);
    if (scene === "draft") {
      await expect(page.getByRole("heading", { name: "Этот месяц ещё не закрыт" })).toBeVisible();
      await expect(page.getByText(/черновик, не исторический отчёт/)).toBeVisible();
    } else if (scene === "unknown") {
      await expect(page.getByRole("heading", { name: "Отчёт не найден" })).toBeVisible();
    } else {
      await expect(page.getByRole("heading", { name: "Это текущий отчёт" })).toBeVisible();
    }
    await expect(page.getByTestId("report-net")).toHaveCount(0);
    await assertBounded(page);
    await capture(page, testInfo, `ui-v2-report-deep-link-${scene}`);
    expect(evidence.unexpected).toEqual([]);
    expect(evidence.errors).toEqual([]);
  });
}
