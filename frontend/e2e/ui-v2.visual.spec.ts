import fs from "node:fs";
import path from "node:path";

import { expect, type Page, test, type TestInfo } from "@playwright/test";

import {
  makeUiV2CapitalHistory,
  makeUiV2Comparison,
  makeUiV2Goals,
  makeUiV2PassiveHistory,
  makeUiV2Workflow,
  uiV2Months,
} from "../src/test/uiV2Fixtures";

type Scene = "normal" | "no-closed" | "first-closed" | "zero" | "passive-error";

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
    "/months/12/close#alfa_baseline",
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
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-home-desktop");
  expect(evidence.reads.every((read) => read.startsWith("GET "))).toBe(true);
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
  await page.getByRole("button", { name: "3 закрытых отчёта" }).click();
  await expect(page.getByText(/последние 3 закрытых отчёта/i)).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Вернуться к текущему интерфейсу →" }),
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
