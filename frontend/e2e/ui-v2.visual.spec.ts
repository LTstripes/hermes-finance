import fs from "node:fs";
import path from "node:path";
import { expect, type Page, type TestInfo, test } from "@playwright/test";
import type { BrokerMonthReadback } from "../src/api/brokerMonths";
import type { MonthCloseWorkflow } from "../src/api/monthCloseWorkflow";
import { makeCapitalDraft } from "../src/test/capitalDraftFixtures";
import { returnsDiagnosticsFixture } from "../src/test/returnsDiagnosticsFixture";
import { overallFixture } from "../src/ui-v2/returns/overallFixtures";

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
import { fulfillMonthPlate } from "./visual-fixtures";

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
    overall: overallFixture(),
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
    if (await fulfillMonthPlate(route)) return;
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
    } else if (url.pathname === "/api/returns/overall") {
      json = state.overall;
    } else if (url.pathname === "/api/accounts") {
      json = uiV2Accounts;
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

test("ui-v2 mobile Home, Returns and Month fit with reachable navigation @viewport-owned", async ({
  page,
}, testInfo) => {
  for (const width of [375, 430, 800]) {
    await page.setViewportSize({ width, height: 812 });
    for (const route of ["/v2", "/v2/returns", "/v2/close?month=12"]) {
      await page.unrouteAll({ behavior: "wait" });
      const evidence = route.includes("close")
        ? await installCloseApi(page)
        : await installApi(page);
      await page.goto(route);
      await expect(page.locator('#v2-main[aria-busy="false"]')).toBeVisible();
      await expect(page.getByRole("link", { name: /Рабочий месяц:/ })).toBeVisible();
      const nav = page.getByRole("navigation", { name: "Основная навигация", exact: true });
      await expect(nav.getByRole("link")).toHaveCount(5);
      expect(await nav.evaluate((el) => getComputedStyle(el).position)).toBe("fixed");
      expect(await nav.evaluate((el) => el.getBoundingClientRect().bottom)).toBe(812);
      expect(await page.locator("aside").evaluate((el) => el.getBoundingClientRect().height)).toBe(
        48,
      );
      expect(
        await page.locator("main").evaluate((el) => el.getBoundingClientRect().top),
      ).toBeLessThanOrEqual(60);
      if (route === "/v2") await expect(page.locator(".recharts-surface").first()).toBeVisible();
      if (route === "/v2/returns") {
        const table = page.getByRole("table", { name: "Все бумаги", exact: true });
        await expect(table).toBeVisible();
        if (width <= 550) {
          expect(
            await table
              .locator("tbody tr")
              .first()
              .evaluate((el) => getComputedStyle(el).display),
          ).toBe("grid");
          await table.getByRole("button", { name: "Результат, ₽", exact: true }).click();
          await expect(page).toHaveURL(/sort=pnl-desc/);
        }
      }
      if (route.includes("close"))
        await expect(
          page.getByRole("navigation", { name: "Разделы месяца", exact: true }),
        ).toBeVisible();
      await assertBounded(page);
      // All five destinations and the month entry remain inside the viewport.
      for (const link of await nav.getByRole("link").all()) {
        const rect = await link.boundingBox();
        expect(rect!.x).toBeGreaterThanOrEqual(0);
        expect(rect!.x + rect!.width).toBeLessThanOrEqual(width);
      }
      await capture(
        page,
        testInfo,
        `ui-v2-mobile-${route.includes("close") ? "month" : route.endsWith("returns") ? "returns" : "home"}-${width}`,
      );
      expect(evidence.unexpected).toEqual([]);
      expect(evidence.errors).toEqual([]);
    }
  }
});

for (const route of ["/v2", "/v2/capital"]) {
  test(`ui-v2 charts use CSS pixels at desktop zoom: ${route} @viewport-owned`, async ({
    page,
  }, testInfo) => {
    const evidence = route === "/v2" ? await installApi(page) : await installCapitalApi(page);
    await page.goto(route);
    await expect(page.locator(".recharts-surface").first()).toBeVisible();
    for (const width of [1024, 1280, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      for (const zoom of [1, 1.25]) {
        await page.evaluate((scale) => {
          document.documentElement.style.zoom = String(scale);
        }, zoom);
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), {
            message: `${route} fits ${width}px at CSS zoom ${zoom}`,
          })
          .toBe(true);
        // Also prove that the SVG fits its container, rather than merely clipping overflow.
        await expect
          .poll(() =>
            page.locator(".recharts-responsive-container").evaluateAll((containers) =>
              containers.every((container) => {
                const svg = container.querySelector("svg.recharts-surface");
                return (
                  !svg ||
                  Number(svg.getAttribute("width")) <= container.parentElement!.clientWidth + 1
                );
              }),
            ),
          )
          .toBe(true);
      }
    }
    await capture(page, testInfo, route === "/v2" ? "home-chart-zoom125" : "capital-chart-zoom125");
    expect(evidence.errors).toEqual([]);
    expect(evidence.unexpected).toEqual([]);
  });
}

test("ui-v2 Home Returns: ranking and charts fit desktop zoom @viewport-owned", async ({
  page,
}, testInfo) => {
  const evidence = await installApi(page);
  const template = evidence.state.overall.instruments[1];
  evidence.state.overall.instruments = [
    "400000",
    "300000",
    "200000",
    "100000",
    "-400000",
    "-300000",
    "-200000",
    "-100000",
  ].map((value, index) => ({
    ...template,
    isin: `RU000A00000${index}`,
    name: `Синтетическая бумага ${index}`,
    accounts: [{ ...template.accounts[0], pnl: { ...template.accounts[0].pnl, value } }],
  }));
  await page.goto("/v2");
  const panel = page.getByRole("region", { name: "Доходность бумаг" });
  await expect(panel).toContainText("в плюсе 4 · в минусе 4");
  await expect(panel.getByRole("listitem")).toHaveCount(6);
  await expect(panel.getByRole("link", { name: "Все бумаги →" })).toHaveAttribute(
    "href",
    "/v2/returns",
  );
  for (const width of [1024, 1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    for (const zoom of [1, 1.25]) {
      await page.evaluate((scale) => {
        document.documentElement.style.zoom = String(scale);
      }, zoom);
      // Wait for ResizeObserver/Recharts to settle at the new scale.
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          ),
      );
      await assertBounded(page);
    }
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await capture(page, testInfo, "ui-v2-home-returns-zoom125");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Home desktop: closed financial picture and draft CTA stay bounded", async ({
  page,
}, testInfo) => {
  const evidence = await installApi(page);
  await page.goto("/v2");
  await expect(page.getByRole("heading", { name: "Мои финансы" })).toBeVisible();
  await expect(page.getByTestId("v2-capital")).toHaveText("2 803 900 ₽");
  await expect(page.getByTestId("v2-draft-action")).toHaveAttribute(
    "href",
    "/v2/close?month=12&step=market_quotes",
  );
  const hero = page.getByRole("region", { name: "Главные показатели" });
  await expect(hero.getByTestId("v2-capital")).toBeVisible();
  await expect(hero.getByText("Обязательства")).toBeVisible();
  await expect(
    page
      .getByRole("group", { name: "Период динамики капитала" })
      .getByRole("button", { name: "12 месяцев" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("v2-capital-history")).toHaveAttribute("data-point-count", "4");
  await expect(page.getByTestId("v2-capital-history")).toHaveAttribute("data-gap-count", "2");
  await expect(page.getByTestId("v2-passive-history")).toHaveAttribute("data-point-count", "4");
  await expect(page.getByTestId("v2-capital-change")).toHaveText("+42 600 ₽");
  await expect(page.getByTestId("v2-capital-change")).toHaveAccessibleDescription("к маю");
  await expect(
    page
      .getByRole("region", { name: "Что изменило капитал" })
      .getByText("Изменение ликвидного капитала"),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Все месяцы →" })).toHaveAttribute(
    "href",
    "/v2/reports",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-home-desktop");
  expect(evidence.reads.every((read) => read.startsWith("GET "))).toBe(true);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Home passive hover keeps tooltip without a full-height cursor", async ({
  page,
}, testInfo) => {
  const evidence = await installApi(page);
  await page.goto("/v2");
  const chart = page.getByTestId("v2-passive-history");
  await expect(chart).toHaveAttribute("data-point-count", "4");
  await chart.locator(".recharts-bar-rectangle").first().hover();
  await expect(chart.locator(".recharts-tooltip-wrapper")).toBeVisible();
  await expect(chart.locator(".recharts-tooltip-cursor")).toHaveCount(0);
  await capture(page, testInfo, "ui-v2-passive-hover");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Home partial capital coverage stays beside the known subtotal", async ({
  page,
}, testInfo) => {
  const evidence = await installApi(page, "coverage");
  await page.goto("/v2");
  await expect(page.getByTestId("v2-capital")).toHaveText("2 803 900 ₽");
  const notes = page.getByTestId("portfolio-coverage-note");
  await expect(notes).toHaveCount(2);
  await expect(notes.nth(0)).toContainText("Синтетический старый вклад");
  await expect(notes.nth(1)).toContainText("Синтетический старый вклад");
  await notes.nth(0).getByRole("button", { name: "Подробнее" }).click();
  await expect(notes.nth(0)).toContainText(
    "Не хватает снимка за Июль 2031: Синтетический старый вклад",
  );
  await assertBounded(page);
  await capture(page, testInfo, "issue-538-home-partial");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Home linked pair: gross details and fixed residuals", async ({ page }, testInfo) => {
  const evidence = await installApi(page);
  const comparison = evidence.state.comparison;
  if (!comparison.explanation || !comparison.current || !comparison.previous)
    throw new Error("Missing comparison fixture");
  comparison.explanation.pairs = [
    {
      account_id: 7,
      account_name: "Синтетический накопительный счёт с длинным названием",
      previous: {
        debt_id: 5,
        debt_name: "Синтетическая кредитка ранее",
        account_balance: { amount: "100.00", currency: "RUB" },
        debt_balance: { amount: "80.00", currency: "RUB" },
        net_contribution: { amount: "20.00", currency: "RUB" },
      },
      current: {
        debt_id: 6,
        debt_name: "Синтетическая кредитка сейчас",
        account_balance: { amount: "40.00", currency: "RUB" },
        debt_balance: { amount: "20.00", currency: "RUB" },
        net_contribution: { amount: "20.00", currency: "RUB" },
      },
      net_contribution_delta: { amount: "0.00", currency: "RUB" },
    },
  ];
  comparison.explanation.noncomparable_account_ids = [8];
  comparison.explanation.residual_asset_class_deltas[0].amount.amount = "52660.00";
  comparison.explanation.residual_debt_contribution_delta.amount = "-10060.00";
  await page.goto("/v2");
  const summary = page.locator("summary").filter({ hasText: "Синтетический накопительный" });
  await expect(summary).toHaveCount(1);
  await summary.click();
  await expect(page.getByText(/Синтетическая кредитка ранее/)).toBeVisible();
  const linkageHelp = page.getByRole("button", { name: "Почему часть счетов не объединена" });
  await linkageHelp.focus();
  await page.keyboard.press("Enter");
  await expect(linkageHelp).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("tooltip")).toContainText(
    "Для части счетов нет явной связи на обоих отчётах: изменение пары недоступно, суммы сохранены в остальных строках.",
  );
  await assertBounded(page);
  await capture(page, testInfo, "issue-651-linked-pair-expanded");
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
        await expect(page.getByText("35%", { exact: true })).toBeVisible();
      }
      if (scene === "zero") {
        await expect(page.getByTestId("v2-capital")).toHaveText("0 ₽");
        await expect(page.getByTestId("v2-capital-change")).toHaveText("−2 761 300 ₽");
        await expect(page.getByTestId("v2-passive-actual")).toHaveText("0 ₽");
        await expect(page.getByTestId("v2-passive-history")).toHaveAttribute(
          "data-point-count",
          "4",
        );
        await expect(page.getByText("22%", { exact: true })).toBeVisible();
        await expect(page.getByText("10 925 ₽ сейчас · осталось 39 075 ₽")).toBeVisible();
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

test("ui-v2 Home interactions: history windows and native navigation preserve semantics", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Interaction proof once");
  const evidence = await installApi(page);
  await page.goto("/v2?month=12&step=actual_payouts");
  await expect(page.getByTestId("v2-capital")).toBeVisible();
  const period = page.getByRole("group", { name: "Период динамики капитала" });
  await period.getByRole("button", { name: "3 месяца" }).click();
  await expect(period.getByRole("button", { name: "3 месяца" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(period.getByRole("button", { name: "12 месяцев" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await expect(page.getByTestId("v2-capital-history")).toHaveAttribute("data-point-count", "3");
  await expect(
    page.getByRole("link", { name: "Открыть этот раздел в предыдущем интерфейсе →" }),
  ).toHaveCount(0);
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
  await expect(page.getByTestId("v2-capital")).toHaveText("2 803 900 ₽");
  await expect(backToTop).toHaveCount(0);
  await page.evaluate(() => window.scrollTo({ top: 360, behavior: "auto" }));
  await expect(backToTop).toBeVisible();
  await expect(backToTop).toHaveAttribute("aria-controls", "v2-main");
  const box = await backToTop.boundingBox();
  expect(box).not.toBeNull();
  if (!box) throw new Error("Back-to-top button has no visible bounding box");
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(1440);
  await assertBounded(page);

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

test("ui-v2 Home desktop long values: hierarchy and actions remain operable", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Unique desktop evidence captured once");
  const evidence = await installApi(page);
  if (!evidence.state.comparison.current)
    throw new Error("Synthetic comparison has no current report");
  evidence.state.comparison.current.liquid_capital_net.amount = "9876543210123.45";
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/v2");
  await expect(page.getByTestId("v2-capital")).toContainText("9 876 543 210 123 ₽");
  await expect(page.getByTestId("v2-draft-action")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-home-desktop-long-values");
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
    label: "Месяц",
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
    if (await fulfillMonthPlate(route)) return;
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
    } else if (url.pathname === "/api/months/12") {
      json = state.workflow.month;
    } else if (url.pathname === "/api/months/12/close-readiness") {
      json = { ...state.workflow.month, can_close: state.workflow.readiness.can_close, items: [] };
    } else if (url.pathname === "/api/positions" && url.search === "?month_id=12") {
      json = [];
    } else if (url.pathname === "/api/broker-months" && url.search === "?reporting_month_id=12") {
      json = [];
    } else if (
      url.pathname === "/api/broker-months/intakes" &&
      ["?reporting_month_id=12&include_unbound=true", "?include_unbound=true"].includes(url.search)
    ) {
      json = [];
    } else if (url.pathname === "/api/accounts" || url.pathname === "/api/instruments") {
      json = [];
    } else if (url.pathname === "/api/health") {
      json = { status: "ok", version: "0.9.0-synthetic" };
    } else if (url.pathname === "/api/analytics/closed-report-comparison") {
      json = makeUiV2Comparison();
    } else if (url.pathname === "/api/returns/overall") {
      json = overallFixture();
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

test("ui-v2 Monthly Close desktop: final review, Close and Home journey", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Interaction proof once");
  const evidence = await installCloseApi(page);
  await page.goto("/v2");
  await page.getByTestId("v2-draft-action").click();
  await expect(page).toHaveURL(/\/v2\/close\?month=12&step=market_quotes$/);
  await expect(page.locator('dl[aria-label="Итоги месяца"]')).toBeVisible();
  await page.getByRole("button", { name: "Закрыть месяц" }).click();
  await expect(page.getByRole("alertdialog", { name: "Закрыть месяц?" })).toBeVisible();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/из 8 шагов/)).toHaveCount(0);
  await capture(page, testInfo, "ui-v2-close-closed-desktop");

  await page.getByRole("link", { name: "Открыть «Мои финансы»" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Мои финансы" })).toBeVisible();
  expect(
    evidence.requests.filter((request) => request === "POST /api/months/12/close"),
  ).toHaveLength(1);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Month desktop: legacy payout return has one Close panel without the wizard", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Unique desktop evidence captured once");
  const evidence = await installCloseApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/v2/close?month=12&step=actual_payouts");
  await expect(page.locator('dl[aria-label="Итоги месяца"]')).toBeVisible();
  await expect(page.getByRole("button", { name: "Закрыть месяц", exact: true })).toHaveCount(1);
  await expect(page.getByRole("list", { name: "Шаги закрытия" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Выбрать выписку с выплатами" })).toHaveCount(0);
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-close-desktop-payout-step");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

type CapitalScene =
  | "normal"
  | "no-closed"
  | "first-closed"
  | "zero"
  | "partial"
  | "coverage"
  | "readiness-missing"
  | "readiness-empty"
  | "excluded";

/** Coherent readiness projection mirroring the synthetic performance fixture. */
function makeReadinessBody(performance: ReturnType<typeof makeUiV2Performance>) {
  const available = performance.xirr.availability === "available";
  return {
    schema_version: 1,
    scope: "portfolio",
    account_id: null,
    start_date: "2031-05-31",
    end_date: "2031-07-31",
    performance_currency: "RUB",
    xirr: { ...performance.xirr, account_id: null },
    twrr: performance.twrr,
    evidence: {
      scope: "portfolio",
      account_id: null,
      start_date: "2031-05-31",
      end_date: "2031-07-31",
      performance_currency: "RUB",
      availability: available ? "available" : "not_computable",
      reason_codes: [],
      scope_membership: {
        status: "complete",
        account_ids: [3],
        missing_or_ambiguous_account_ids: [],
        reason_codes: [],
      },
      cash_boundary_coverage: {
        status: "complete",
        account_ids: [3],
        missing_or_incomplete_account_ids: [],
        reason_codes: [],
      },
      in_kind_boundary_coverage: {
        status: "complete",
        account_ids: [],
        missing_or_incomplete_account_ids: [],
        reason_codes: [],
      },
    },
    diagnostics: [],
  };
}

function makeExcludedReadiness(performance: ReturnType<typeof makeUiV2Performance>, url: URL) {
  const body = makeReadinessBody(performance);
  const scope = url.searchParams.get("scope") === "account" ? "account" : "portfolio";
  const accountId = scope === "account" ? Number(url.searchParams.get("account_id")) : null;
  const reasons = [
    "not_computable_opening_valuation_missing",
    "not_computable_closing_valuation_missing",
    "not_computable_scope_membership_history_missing",
    "mybroker_excluded_source_impact",
  ];
  for (const metric of [body.xirr, body.twrr]) {
    Object.assign(metric, {
      scope,
      account_id: accountId,
      value: null,
      availability: "not_computable",
      quality: "unavailable",
      reason_codes: reasons,
    });
  }
  const refs = {
    account_ids: [],
    reporting_month_ids: [],
    external_flow_ids: [],
    legacy_flow_ids: [],
    movement_ids: [],
    boundary_group_ids: [],
    dates: [],
  };
  return {
    ...body,
    scope,
    account_id: accountId,
    evidence: {
      ...body.evidence,
      scope,
      account_id: accountId,
      availability: "not_computable",
      reason_codes: reasons,
      scope_membership: {
        status: "unknown",
        account_ids: [3],
        missing_or_ambiguous_account_ids: [3],
        reason_codes: [reasons[2]],
      },
      cash_boundary_coverage: {
        status: "unknown",
        account_ids: [],
        missing_or_incomplete_account_ids: [],
        reason_codes: [],
      },
      in_kind_boundary_coverage: {
        status: "unknown",
        account_ids: [],
        missing_or_incomplete_account_ids: [],
        reason_codes: [],
      },
    },
    diagnostics: [
      "opening_valuation",
      "closing_valuation",
      "membership_history",
      "excluded_source",
    ].map((key, index) => ({
      key,
      reason_codes: [reasons[index]],
      affected_metrics: ["xirr", "twrr"],
      category: "limitation",
      refs,
      action: {
        kind: "inspect_result",
        capability: "source_required",
        params: refs,
        verify: "reread_readiness",
      },
    })),
  };
}

async function installCapitalApi(page: Page, scene: CapitalScene = "normal") {
  const candidateScene = scene === "readiness-missing" || scene === "readiness-empty";
  const readinessFor = (url: URL) => {
    const body = makeExcludedReadiness(state.performance, url);
    if (!candidateScene) return body;
    const ids = scene === "readiness-empty" ? [] : [1, 3];
    const accountId = body.account_id;
    body.evidence.scope_membership.account_ids = accountId === null ? ids : [accountId];
    body.evidence.scope_membership.missing_or_ambiguous_account_ids =
      accountId === null ? ids : [accountId];
    body.diagnostics = body.diagnostics.filter(
      (diagnostic) => diagnostic.key !== "excluded_source",
    );
    if (accountId === 1) {
      Object.assign(body.xirr, {
        value: "0.00",
        availability: "available",
        quality: "exact",
        reason_codes: [],
      });
    }
    return body;
  };
  const firstClosed = scene === "first-closed";
  const zero = scene === "zero";
  const partial = scene === "partial";
  const state = {
    months:
      scene === "no-closed"
        ? [uiV2Months[1]]
        : scene === "first-closed"
          ? [uiV2Months[0], uiV2Months[1]]
          : uiV2Months,
    brokerMonths: [] as BrokerMonthReadback[],
    accounts: scene === "readiness-empty" ? [] : uiV2Accounts,
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
  if (zero) {
    // Risk uses raw class keys; zero only the values, not its dimension keys.
    for (const metric of [state.risk.allocation_by_asset_class, state.risk.allocation_by_account]) {
      metric.denominator.amount = "0.00";
      metric.covered_amount.amount = "0.00";
      metric.unallocated_amount.amount = "0.00";
      metric.coverage_pct = null;
      for (const item of metric.items) {
        item.amount.amount = "0.00";
        item.share_pct = null;
      }
    }
    state.risk.top_positions.denominator.amount = "0.00";
    state.risk.top_positions.top_amount.amount = "0.00";
    state.risk.top_positions.top_share_pct = null;
    state.risk.top_positions.items = [];
  }
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
    if (await fulfillMonthPlate(route)) return;
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
    const returnsHost =
      url.pathname === "/api/returns/overall"
        ? overallFixture()
        : returnsDiagnosticsFixture(url, state.accounts);
    if (returnsHost) {
      json = returnsHost;
    } else if (url.pathname === "/api/months") {
      json = state.months;
      status = state.monthsError ? 503 : 200;
    } else if (url.pathname === "/api/broker-months") {
      expect(url.searchParams.get("reporting_month_id")).toBe("12");
      json = state.brokerMonths;
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
      json = state.accounts;
    } else if (url.pathname === "/api/instruments") {
      json = uiV2Instruments;
      status = state.instrumentsError ? 503 : 200;
    } else if (url.pathname === "/api/performance/attribution") {
      json = state.performance.attribution;
    } else if (url.pathname === "/api/performance/readiness") {
      json = makeReadinessBody(state.performance);
      if (scene === "excluded" || candidateScene) json = readinessFor(url);
    } else if (
      (scene === "excluded" || candidateScene) &&
      [
        "/api/performance/valuation-captures",
        "/api/performance/membership",
        "/api/performance/preparation",
      ].includes(url.pathname)
    ) {
      const readiness = readinessFor(url);
      const context = {
        scope: readiness.scope,
        account_id: readiness.account_id,
        start_date: readiness.start_date,
        end_date: readiness.end_date,
      };
      if (url.pathname.endsWith("valuation-captures")) {
        json = {
          ...context,
          schema_version: 1,
          performance_currency: "RUB",
          targets: [],
          captured: null,
          readiness,
        };
      } else if (url.pathname.endsWith("membership")) {
        json = {
          ...context,
          rows: [],
          identity: "synthetic-history",
          form_token: "synthetic-form",
          readiness,
        };
      } else {
        json = {
          ...context,
          evidence_token: "synthetic",
          flows: [],
          transfer_links: [],
          cash_coverages: [],
          in_kind_coverages: [],
          movements: [],
          cash_balances: [],
          months: [],
        };
      }
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

for (const scene of ["closed-only", "draft-only", "both", "inaccessible"] as const) {
  test(`ui-v2 Capital DRAFT ${scene}: native facts and isolation @viewport-owned`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: scene === "both" ? 1440 : 1280, height: 900 });
    const evidence = await installCapitalApi(page);
    if (scene === "closed-only")
      evidence.state.months = uiV2Months.filter((m) => m.status === "closed");
    if (scene === "draft-only") evidence.state.months = [uiV2Months[1]];
    if (scene !== "closed-only")
      evidence.state.brokerMonths = [makeCapitalDraft(scene === "inaccessible" ? 999 : 3)];
    await page.goto("/v2/capital");
    const preview = page.getByRole("region", {
      name: "Черновик / предварительная оценка, не закрытый месяц",
    });
    if (scene === "draft-only") {
      await expect(page.getByRole("heading", { name: "Закрой первый отчёт" })).toBeVisible();
      await expect(page.getByTestId("capital-net")).toHaveCount(0);
      expect(evidence.reads.some((r) => r.includes("/api/analytics/"))).toBe(false);
    } else {
      await expect(page.getByTestId("capital-net")).toHaveText("2 803 900 ₽");
      await expect(page.getByTestId("capital-assets")).toHaveText("3 203 900 ₽");
    }
    if (scene === "closed-only" || scene === "inaccessible") {
      await expect(preview).toHaveCount(0);
    } else {
      await expect(preview).toBeVisible();
      await expect(preview.getByRole("table", { name: /Позиции DRAFT/ })).toContainText(
        "1 234,56 ₽",
      );
      await expect(preview.getByRole("table", { name: /Позиции DRAFT/ })).toContainText(
        "Неизвестно",
      );
      await expect(preview.getByRole("table", { name: "Отдельный RUB cash DRAFT" })).toContainText(
        "789,01 ₽",
      );
      await expect(preview.getByText(/Close заблокирован/)).toBeVisible();
      await expect(preview.getByText("money_semantics_unsupported")).toBeVisible();
      await expect(preview.getByRole("button", { name: "Закрыть месяц" })).toBeDisabled();
      await page.evaluate(() => {
        document.documentElement.style.zoom = "1.25";
      });
      await assertBounded(page);
      const account = preview.getByLabel("Брокерский счёт черновика");
      await account.focus();
      await expect(account).toBeFocused();
      const dir = path.resolve(".visual-audit", testInfo.project.name);
      fs.mkdirSync(dir, { recursive: true });
      await preview.screenshot({ path: path.join(dir, `ui-v2-capital-draft-${scene}-125.png`) });
      await account.selectOption("4");
      await expect(preview.getByText("Для этого счёта нет совместимого DRAFT.")).toBeVisible();
      await expect(preview.getByRole("table")).toHaveCount(0);
      const other = makeCapitalDraft(4);
      if (other.accepted.document) other.accepted.document.positions[0].ending_value = "4321.98";
      evidence.state.brokerMonths.push(other);
      await preview.getByRole("button", { name: "Обновить DRAFT" }).click();
      await expect(preview.getByText("4 321,98 ₽")).toBeVisible();
      await expect(preview.getByText("1 234,56 ₽")).toHaveCount(0);
      await expect(preview.getByText(/Счёт исключён из капитала/)).toBeVisible();
      await preview.getByRole("link", { name: "Источник и предупреждения месяца →" }).focus();
      await expect(
        preview.getByRole("link", { name: "Источник и предупреждения месяца →" }),
      ).toBeFocused();
      await preview.screenshot({
        path: path.join(dir, `ui-v2-capital-draft-${scene}-account-b-125.png`),
      });
      if (scene === "both") {
        const withdrawn = makeCapitalDraft(4);
        withdrawn.request_id = "synthetic-withdrawn-source";
        evidence.state.brokerMonths.push(withdrawn);
        await preview.getByRole("button", { name: "Обновить DRAFT" }).click();
        await preview.getByLabel("Исходная выписка черновика").selectOption(withdrawn.request_id);
        evidence.state.brokerMonths = evidence.state.brokerMonths.filter(
          (b) => b.request_id !== withdrawn.request_id,
        );
        await preview.getByRole("button", { name: "Обновить DRAFT" }).click();
        await expect(
          preview.getByText("Выбранная выписка DRAFT недоступна. Выбери другую исходную выписку."),
        ).toBeVisible();
        await expect(preview.getByRole("table")).toHaveCount(0);
        await preview.screenshot({
          path: path.join(dir, "ui-v2-capital-draft-withdrawn-source-125.png"),
        });
        await preview.getByLabel("Исходная выписка черновика").selectOption(other.request_id);
        await expect(preview.getByText("4 321,98 ₽")).toBeVisible();
        await expect(page.getByTestId("capital-net")).toHaveText("2 803 900 ₽");
      }
    }
    await assertBounded(page);
    await capture(page, testInfo, `ui-v2-capital-draft-${scene}-full`);
    expect(evidence.reads.every((r) => r.startsWith("GET "))).toBe(true);
    expect(evidence.unexpected).toEqual([]);
    expect(evidence.errors).toEqual([]);
  });
}

for (const width of [1440]) {
  test(`ui-v2 excluded source remains visible in Performance ${width}px @viewport-owned`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const evidence = await installCapitalApi(page, "excluded");
    const explanation =
      "Источник сохранён; для затронутой исторической доходности требуется полное подтверждение.";
    await page.goto("/v2/capital");
    await expect(page.getByTestId("capital-performance-xirr")).toHaveCount(0);
    expect(evidence.reads.some((read) => read.includes("/api/performance"))).toBe(false);
    for (const scope of ["portfolio", "account"]) {
      await page.goto(
        `/v2/returns/account?diagnostics=performance&start=2031-05-31&end=2031-07-31&scope=${scope === "account" ? "account:3" : scope}`,
      );
      await expect(page.getByText(explanation)).toBeVisible();
      for (const metric of ["xirr", "twrr"]) {
        await expect(page.getByTestId(`performance-detail-${metric}`)).toContainText(
          "Исторические данные исключены из расчёта",
        );
        await expect(page.getByTestId(`performance-detail-${metric}`)).not.toContainText(
          /\d[,.]\d+%/,
        );
      }
      await capture(page, testInfo, `ui-v2-excluded-detail-${scope}-collapsed-${width}`);
      const expand = page.getByRole("button", { name: /Все причины/ });
      await expand.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("button", { name: "Скрыть полный список" })).toBeFocused();
      await expect(
        page.getByText("Выберите другую конечную дату либо откройте отчёт из данных границы."),
      ).toBeVisible();
      await expect(page.getByText(explanation)).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      await expect(page.getByText("mybroker_excluded_source_impact", { exact: true })).toHaveCount(
        0,
      );
      await capture(page, testInfo, `ui-v2-excluded-detail-${scope}-${width}`);
    }
    expect(evidence.errors).toEqual([]);
    expect(evidence.unexpected).toEqual([]);
  });
}

test("ui-v2 readiness candidates: missing coverage, ambiguity and keyboard Back @viewport-owned", async ({
  page,
}, testInfo) => {
  const evidence = await installCapitalApi(page, "readiness-missing");
  const path =
    "/v2/returns/account?diagnostics=performance&start=2031-05-31&end=2031-07-31&scope=portfolio";
  await page.goto(path);
  const table = page.getByTestId("performance-accounts-table");
  await expect(table.getByRole("row")).toHaveCount(3);
  const ambiguous = page.getByTestId("performance-account-row-3");
  await expect(ambiguous).toContainText("История участия отсутствует или неоднозначна");
  await expect(ambiguous).toContainText("недоступен");
  await expect(ambiguous.getByRole("cell").nth(1)).toHaveText("—");
  await expect(ambiguous.getByRole("cell").nth(2)).toHaveText("—");
  const mixed = page.getByTestId("performance-account-row-1");
  await expect(mixed).toContainText("частично доступен");
  await expect(mixed).toContainText("0,00%");
  await expect(page.getByTestId("performance-detail-xirr")).not.toContainText(/\d[,.]\d+%/);
  await expect(page.getByTestId("performance-composition-cash")).toContainText(
    "Список счетов денежной проверки не подтверждён",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-readiness-candidates");
  const open = ambiguous.getByRole("link", { name: "Открыть" });
  await open.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/v2\/returns\/account\?.*scope=account%3A3/);
  await expect(page.getByTestId("performance-detail-period")).toContainText("31.05.2031");
  await expect(page.getByTestId("performance-detail-period")).toContainText("31.07.2031");
  await expect(page.getByTestId("performance-detail-xirr")).not.toContainText(/\d[,.]\d+%/);
  await page.goBack();
  await expect(page).toHaveURL(path);
  await expect(page.getByTestId("performance-account-row-3")).toBeVisible();
  expect(evidence.reads.every((read) => read.startsWith("GET "))).toBe(true);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 readiness empty catalogue: honest empty state @viewport-owned", async ({
  page,
}, testInfo) => {
  const evidence = await installCapitalApi(page, "readiness-empty");
  await page.goto(
    "/v2/returns/account?diagnostics=performance&start=2031-05-31&end=2031-07-31&scope=portfolio",
  );
  await expect(
    page.getByText("Каталог счетов пуст. Исторический состав расчёта не подтверждён."),
  ).toBeVisible();
  await expect(page.getByTestId("performance-accounts-table")).toHaveCount(0);
  await expect(page.getByTestId("performance-composition-membership")).not.toContainText(
    "Проблем нет",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-readiness-empty");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Capital desktop: closed composition, allocation and holdings stay bounded", async ({
  page,
}, testInfo) => {
  const evidence = await installCapitalApi(page);
  await page.goto("/v2/capital");
  await expect(page.getByRole("heading", { level: 1, name: "Капитал" })).toBeVisible();
  await expect(page.getByTestId("capital-net")).toHaveText("2 803 900 ₽");
  await expect(page.getByTestId("capital-assets")).toHaveText("3 203 900 ₽");
  await expect(page.getByTestId("capital-debts")).toHaveText("−400 000 ₽");
  await expect(page.getByTestId("capital-draft-note")).toContainText("Август 2031 ещё не закрыт");
  await expect(page.getByTestId("capital-composition")).toHaveAttribute("data-point-count", "4");
  await expect(page.getByTestId("capital-change-list")).toHaveCount(0);
  for (const name of ["По классам активов", "Счета и позиции"]) {
    await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  }
  await expect(page.getByTestId("capital-top-summary")).toBeVisible();
  await expect(page.getByTestId("capital-class-cash")).toContainText("803 900 ₽");
  await expect(page.getByTestId("capital-bucket-unassigned_cash")).toContainText(
    "Деньги без привязки к счёту",
  );
  await expect(page.getByTestId("capital-holding-cash-702")).toContainText(
    "не входит в ликвидный капитал",
  );
  await expect(page.getByTestId("capital-pair-21")).toHaveCount(0);
  await expect(page.getByTestId("capital-pair-gap")).toHaveCount(0);
  await expect(page.getByTestId("capital-pair-22")).toHaveCount(0);
  await expect(page.getByTestId("capital-performance-bridge")).toHaveCount(0);
  expect(evidence.reads.some((read) => read.includes("/api/performance"))).toBe(false);
  await expect(page.getByText("Разница: капитал − ипотека")).toBeVisible();
  await expect(
    page.locator(".capital-composition-chart path[fill='#9aa3ae']").first(),
  ).toBeVisible();
  expect(await page.locator(".capital-composition-chart path[fill='#27734c']").count()).toBe(0);
  await expect(page.getByText("164,9%", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Распределение", exact: true })).toHaveAttribute(
    "href",
    "/v2/capital/allocation",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-capital-desktop");
  expect(evidence.reads.every((read) => read.startsWith("GET "))).toBe(true);
  expect(evidence.reads.some((read) => read.includes("forecast_version=v1"))).toBe(true);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("@viewport-owned ui-v2 Capital groups fit 720px at desktop widths and zoom", async ({
  page,
}, testInfo) => {
  const evidence = await installCapitalApi(page);
  await page.goto("/v2/capital");
  await expect(page.getByTestId("capital-bucket-account:3")).toBeVisible();
  const panel = page.getByTestId("capital-panel-capital-holdings-title");
  await panel.evaluate((element) => {
    element.style.maxWidth = "720px";
  });
  for (const [width, zoom] of [
    [1024, 1],
    [1280, 1],
    [1280, 1.25],
    [1440, 1],
    [1440, 1.25],
    [1920, 1],
    [1920, 1.25],
  ]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate((value) => {
      document.documentElement.style.zoom = String(value);
    }, zoom);
    for (const mode of ["По счетам", "По классам"]) {
      await panel.getByRole("button", { name: mode, exact: true }).click();
      for (const group of await panel.getByTestId("capital-holding-group").all()) {
        if (!(await group.evaluate((element) => (element as HTMLDetailsElement).open)))
          await group.locator(":scope > summary").click();
      }
      const overflow = await panel.evaluate(
        (element) =>
          [...element.querySelectorAll("summary, li")].filter(
            (row) => row.scrollWidth > row.clientWidth + 1,
          ).length,
      );
      expect(overflow).toBe(0);
      await expect(page.getByTestId("capital-net")).toHaveText("2 803 900 ₽");
      await assertBounded(page);
    }
    await capture(page, testInfo, `capital-${width}-${zoom}`);
  }
  await page.setViewportSize({ width: 1280, height: 1000 });
  const longLabel = "СинтетическийСчёт".repeat(5).slice(0, 80);
  await page.goto(
    `/v2/capital?${new URLSearchParams({ holding_kind: "account", holding_value: "account:3", holding_label: longLabel })}`,
  );
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  await expect(page.getByText(`Фильтр: ${longLabel}`, { exact: true })).toBeVisible();
  await expect(page.getByTestId("capital-holding-position-501")).toBeVisible();
  await assertBounded(page);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Capital partial coverage keeps the known net", async ({ page }, testInfo) => {
  const evidence = await installCapitalApi(page, "coverage");
  await page.goto("/v2/capital");
  await expect(page.getByTestId("capital-net")).toHaveText("2 803 900 ₽");
  await expect(page.getByTestId("portfolio-coverage-note")).toContainText(
    "Частично: нет снимка счёта: Синтетический старый вклад",
  );
  await assertBounded(page);
  await capture(page, testInfo, "issue-538-capital-partial");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Capital desktop long values: allocation filters stay operable", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Unique desktop evidence captured once");
  const evidence = await installCapitalApi(page);
  if (!evidence.state.comparison.current)
    throw new Error("Synthetic comparison has no current report");
  evidence.state.comparison.current.liquid_capital_net.amount = "9876543210123.45";
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/v2/capital");
  await expect(page.getByTestId("capital-net")).toContainText("9 876 543 210 123 ₽");
  await expect(page.getByTestId("capital-net")).toHaveAttribute("title", /123,45/);
  const stocks = page.getByTestId("capital-class-stock").getByRole("button");
  await stocks.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Фильтр: Акции")).toBeVisible();
  await expect(page.getByTestId("capital-holding-position-501")).toBeVisible();
  await expect(page.getByTestId("capital-holding-position-502")).toHaveCount(0);
  const reset = page.getByRole("button", { name: "Сбросить" });
  await reset.focus();
  await page.keyboard.press("Enter");
  await page.getByTestId("capital-bucket-account:3").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("capital-holding-position-502")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-capital-desktop-long-values");
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
      await expect(page.getByTestId("capital-class-cash")).toHaveCount(0);
      await expect(page.getByTestId("capital-assets")).toHaveText("0 ₽");
      await expect(page.getByText("Ненулевых строк нет.", { exact: true })).toBeVisible();
    } else {
      await expect(page.getByTestId("capital-net")).toBeVisible();
      if (scene === "first-closed") {
        await expect(page.getByTestId("capital-composition")).toHaveAttribute(
          "data-point-count",
          "1",
        );
        await expect(page.getByTestId("capital-change-list")).toHaveCount(0);
      }
      if (scene === "partial") {
        await expect(page.getByText("Данные временно недоступны").first()).toBeVisible();
        await expect(page.getByTestId("capital-composition")).toBeVisible();
        for (const group of await page.getByTestId("capital-holding-group").all()) {
          if (!(await group.evaluate((element) => (element as HTMLDetailsElement).open)))
            await group.locator(":scope > summary").click();
        }
        await expect(page.getByTestId("capital-holding-cash-701")).toBeVisible();
        await expect(page.getByTestId("capital-holding-deposit-601")).toBeVisible();
        await expect(page.getByTestId("capital-holding-position-501")).toHaveCount(0);
        await expect(page.getByTestId("capital-pair-21")).toHaveCount(0);
      }
    }
    await assertBounded(page);
    await capture(page, testInfo, `ui-v2-capital-${scene}`);
    expect(evidence.unexpected).toEqual([]);
    expect(evidence.errors).toEqual([]);
  });
}

test("ui-v2 Capital interactions: filters, windows and native navigation preserve semantics", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Interaction proof once");
  const evidence = await installCapitalApi(page);
  await page.goto(`/v2/capital?month=${uiV2CapitalPreviousMonthId}&step=actual_payouts`);
  await expect(page.getByTestId("capital-net")).toBeVisible();
  await page.getByRole("button", { name: "3 мес" }).click();
  await expect(page.getByTestId("capital-composition")).toHaveAttribute("data-point-count", "3");
  await page.getByTestId("capital-class-stock").getByRole("button").click();
  await expect(page.getByText("Фильтр: Акции")).toBeVisible();
  await expect(page.getByTestId("capital-holding-position-501")).toBeVisible();
  await page.getByRole("button", { name: "Сбросить" }).click();
  await page.getByTestId("capital-bucket-account:1").click();
  await expect(page.getByTestId("capital-holding-deposit-601")).not.toBeVisible();
  await page.getByTestId("capital-bucket-account:1").click();
  await expect(page.getByTestId("capital-holding-deposit-601")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Открыть этот раздел в предыдущем интерфейсе →" }),
  ).toHaveCount(0);
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
    if (await fulfillMonthPlate(route)) return;
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
    } else if (url.pathname === "/api/analytics/passive-income") {
      json = makeUiV2PassiveHistory();
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
  await expect(page.getByRole("heading", { level: 1, name: "Все месяцы" })).toBeVisible();
  await expect(page.getByTestId("reports-row-91")).toContainText("Закрыт");
  await expect(page.getByTestId("reports-row-91")).toContainText("2 803 900 ₽");
  await expect(page.getByTestId("reports-row-90")).toContainText("2 761 300 ₽");
  await expect(page.getByTestId("reports-row-90")).toContainText("15 600 ₽");
  await expect(page.getByTestId("reports-row-12")).toContainText("Черновик");
  await expect(page.getByTestId("reports-row-87")).toContainText("Ноябрь 2030");
  await expect(
    page.getByTestId("reports-row-91").getByRole("link", { name: "Открыть" }),
  ).toHaveAttribute("href", "/v2/close?month=91");
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
  expect(archiveLayout.cellCount).toBe(5);
  expect(archiveLayout.tableLayout).toBe("fixed");
  expect(archiveLayout.actionGap).toBeGreaterThanOrEqual(12);
  expect(archiveLayout.widths.every((width) => width > 0)).toBe(true);
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-reports-archive-desktop");
  expect(evidence.reads.every((read) => read.startsWith("GET "))).toBe(true);
  // The list reuses the same capital and passive income readers as the overview.
  expect([...new Set(evidence.reads.map((read) => read.split(" ")[1]))].sort()).toEqual([
    "/api/analytics/capital-composition",
    "/api/analytics/passive-income?reporting_month_id=91",
    "/api/months",
  ]);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("@viewport-owned ui-v2 months table fits 720px at desktop widths and zoom", async ({
  page,
}, testInfo) => {
  const evidence = await installReportsApi(page);
  await page.goto("/v2/data/months");
  await expect(page.getByTestId("reports-row-91")).toContainText("2 803 900 ₽");
  const table = page.getByTestId("months-table");
  await table.evaluate((element) => {
    element.parentElement!.style.maxWidth = "720px";
  });
  for (const [width, zoom] of [
    [1024, 1],
    [1280, 1],
    [1280, 1.25],
    [1440, 1],
    [1440, 1.25],
    [1920, 1],
    [1920, 1.25],
  ]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate((value) => {
      document.documentElement.style.zoom = String(value);
    }, zoom);
    const overflow = await table.evaluate(
      (element) =>
        [...element.querySelectorAll("th, td")].filter(
          (cell) => cell.scrollWidth > cell.clientWidth + 1,
        ).length,
    );
    expect(overflow).toBe(0);
    await expect(page.getByTestId("reports-row-90")).toContainText("15 600 ₽");
    await assertBounded(page);
    await capture(page, testInfo, `months-${width}-${zoom}`);
  }
  expect(evidence.errors).toEqual([]);
  expect(evidence.unexpected).toEqual([]);
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
    missing_account_ids: [2, 3],
  };
  await page.goto("/v2/reports");
  const row = page.getByTestId(`reports-row-${uiV2CapitalPreviousMonthId}`);
  await expect(row).toContainText("2 761 300 ₽");
  await expect(row).toContainText("неполный");
  await expect(page.getByText(/Неполный капитал — итог известных записей/)).toHaveCount(1);
  const overlap = await row.evaluate((element) => {
    const cells = element.querySelectorAll("td");
    return cells[1].scrollWidth > cells[1].clientWidth + 1;
  });
  expect(overlap).toBe(false);
  await assertBounded(page);
  await capture(page, testInfo, "issue-538-archive-partial");
  expect(evidence.errors).toEqual([]);
  expect(evidence.unexpected).toEqual([]);
});

for (const scene of ["no-closed", "first-closed", "money-error"] as const) {
  test(`ui-v2 reports archive state ${scene}: honest partial result`, async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "1440x900", "State evidence captured once");
    const evidence = await installReportsApi(page, scene);
    await page.goto("/v2/reports");
    if (scene === "no-closed") {
      await expect(page.getByTestId("reports-row-12")).toContainText("Черновик");
      await expect(page.getByTestId("reports-row-91")).toHaveCount(0);
    } else if (scene === "first-closed") {
      await expect(page.getByTestId("reports-row-91")).toContainText("2 803 900 ₽");
      await expect(page.getByText("отчёта нет")).toHaveCount(0);
    } else {
      await expect(page.getByText(/Часть сумм недоступна/)).toBeVisible();
      await expect(page.getByTestId("months-table")).not.toContainText("2 761 300 ₽");
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
  await expect(page.getByTestId("report-debts")).toHaveText("−390 000 ₽");
  await expect(page.getByTestId("report-class-cash")).toContainText("751 300 ₽");
  await expect(page.getByTestId("report-history")).toBeVisible();
  await expect(page.locator('[data-highlight-key="2031-05"]')).toHaveCount(1);
  await expect(page.getByTestId("report-neighbour-previous")).toHaveAttribute(
    "href",
    "/v2/reports/89",
  );
  await expect(page.getByTestId("report-neighbour-next")).toHaveAttribute("href", "/v2/reports/91");
  await expect(page.getByRole("heading", { name: "Где изменились суммы" })).toHaveCount(0);
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
  await expect(page.getByTestId("portfolio-coverage-note")).toContainText(
    "Частично: нет снимка счёта: Синтетический старый вклад",
  );
  await assertBounded(page);
  await capture(page, testInfo, "issue-538-report-partial");
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
  const period = page.getByRole("group", { name: "Период истории", exact: true });
  await expect(period.getByRole("button", { name: "12 месяцев" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-report-contextual-window-12");

  await period.getByRole("button", { name: "3 месяца" }).click();
  await expect(period.getByRole("button", { name: "3 месяца" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(period.getByRole("button", { name: "12 месяцев" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
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
