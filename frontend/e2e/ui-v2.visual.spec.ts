import fs from "node:fs";
import path from "node:path";

import { expect, type Page, test, type TestInfo } from "@playwright/test";

import type { MonthCloseWorkflow } from "../src/api/monthCloseWorkflow";
import { makeUiV2Workflow, uiV2Months } from "../src/test/uiV2Fixtures";
import { syntheticApiResponse } from "./visual-fixtures";

type Scene = "draft" | "blocked" | "closed" | "empty" | "error" | "unavailable" | "zero";

async function installApi(page: Page, scene: Scene = "draft", allowLegacy = false) {
  const state = {
    delayMonth: 0,
    workflowError: scene === "error",
    workflow: makeUiV2Workflow({
      blocked: scene === "blocked",
      unavailable: scene === "unavailable",
      zeroIncome: scene === "zero",
    }),
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
    reads.push(`${request.method()} ${url.pathname}`);
    if (request.method() !== "GET") {
      unexpected.push(`${request.method()} ${url.pathname}`);
      await route.abort();
      return;
    }
    let body: unknown;
    let status = 200;
    if (url.pathname === "/api/health") body = { status: "ok", version: "synthetic" };
    else if (url.pathname === "/api/months") body = scene === "empty" ? [] : uiV2Months;
    else if (/^\/api\/months\/(12|91)\/close-workflow$/.test(url.pathname)) {
      if (url.pathname.includes(`/${state.delayMonth}/`))
        await new Promise((resolve) => setTimeout(resolve, 900));
      body = url.pathname.includes("/91/") ? makeUiV2Workflow({ monthId: 91 }) : state.workflow;
      status = state.workflowError ? 503 : 200;
    } else if (allowLegacy) {
      const response = syntheticApiResponse(url, request.method(), "content");
      if (response) {
        await route.fulfill({ status: response.status ?? 200, json: response.json });
        return;
      }
      unexpected.push(`${request.method()} ${url.pathname}`);
    } else unexpected.push(`${request.method()} ${url.pathname}`);
    await route.fulfill({
      status,
      json:
        status === 200
          ? (body ?? {})
          : { error: { code: "synthetic_error", message: "Synthetic failure", details: [] } },
    });
  });
  return { state, reads, unexpected, errors };
}

async function assertBounded(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
  const clipped = await page
    .locator("#v2-main button, #v2-main select, #v2-main a")
    .evaluateAll((elements) =>
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

for (const scene of [
  "draft",
  "blocked",
  "closed",
  "empty",
  "error",
  "unavailable",
  "zero",
] as const) {
  test(`ui-v2 ${scene}: bounded, explicit state and read-only network`, async ({
    page,
  }, testInfo) => {
    const evidence = await installApi(page, scene);
    await page.goto(scene === "closed" ? "/v2?month=91" : "/v2");
    const headings = {
      empty: "Начни с первого месяца",
      error: "Не удалось получить состояние месяца",
      unavailable: "Итоги пока недоступны",
    };
    if (scene in headings) {
      await expect(
        page.getByRole("heading", { name: headings[scene as keyof typeof headings] }),
      ).toBeVisible();
      await expect(page.getByTestId("v2-capital")).toHaveCount(0);
    } else {
      await expect(page.getByTestId("v2-capital")).toBeVisible();
      await expect(page.getByTestId("v2-primary-action")).toHaveAttribute(
        "href",
        scene === "closed"
          ? "/months/91/close#next_month_outlook"
          : scene === "blocked"
            ? "/months/12/close#readiness"
            : "/months/12/close#alfa_baseline",
      );
      await expect(page.getByTestId("v2-blockers")).toHaveText(scene === "blocked" ? "1" : "0");
      if (scene === "zero") await expect(page.getByTestId("v2-passive-actual")).toHaveText("0 ₽");
      if (scene === "draft") {
        // The action, not only the KPI grid, must be visible without scrolling on desktop.
        const action = await page.getByTestId("v2-primary-action").boundingBox();
        expect(action).not.toBeNull();
        expect((action?.y ?? 9999) + (action?.height ?? 0)).toBeLessThan(
          page.viewportSize()?.height ?? 0,
        );
      }
    }
    await assertBounded(page);
    await capture(page, testInfo, `ui-v2-${scene}`);
    expect(evidence.unexpected).toEqual([]);
    expect(evidence.errors).toEqual([]);
  });
}

test("ui-v2 keyboard, step focus, v1 handoff and return", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== "1440x900",
    "One interaction proof; layout covered in every desktop project",
  );
  const evidence = await installApi(page, "draft", true);
  await page.goto("/v2?month=12");
  await expect(page.getByTestId("v2-capital")).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "К содержанию" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#v2-main")).toBeFocused();
  const reads = evidence.reads.length;
  await page.getByTestId("v2-step-market_quotes").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#v2-action")).toBeFocused();
  expect(evidence.reads).toHaveLength(reads);
  await expect(page).toHaveURL(/month=12&step=market_quotes$/);
  await page.getByTestId("v2-primary-action").click();
  await expect(page).toHaveURL(/\/months\/12\/close#market_quotes$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/v2\?month=12&step=market_quotes$/);
  await expect(page.getByTestId("v2-capital")).toBeVisible();
  expect(
    evidence.reads.filter((read) => read === "GET /api/months/12/close-workflow").length,
  ).toBeGreaterThan(1);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 slow month switch, back/forward, reload and retry never mix periods", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Stateful interaction proof once");
  const evidence = await installApi(page);
  await page.goto("/v2?month=12");
  await expect(page.getByTestId("v2-capital")).toHaveText("2 846 500 ₽");
  evidence.state.delayMonth = 91;
  await page.getByLabel("Отчётный месяц").selectOption("91");
  await expect(page.getByText("Обновляем состояние выбранного месяца…")).toBeVisible();
  await expect(page.getByTestId("v2-capital")).toHaveCount(0);
  await capture(page, testInfo, "ui-v2-loading");
  await expect(page.getByTestId("v2-capital")).toHaveText("2 803 900 ₽");
  await page.goBack();
  await expect(page.getByTestId("v2-capital")).toHaveText("2 846 500 ₽");
  await page.goForward();
  await expect(page.getByTestId("v2-capital")).toHaveText("2 803 900 ₽");
  await page.reload();
  await expect(page.getByLabel("Отчётный месяц")).toHaveValue("91");
  await expect(page.getByTestId("v2-capital")).toHaveText("2 803 900 ₽");
  evidence.state.workflowError = true;
  await page.getByLabel("Отчётный месяц").selectOption("12");
  await expect(page.getByRole("alert")).toContainText("Не удалось получить состояние месяца");
  await expect(page.getByTestId("v2-capital")).toHaveCount(0);
  evidence.state.workflowError = false;
  await page.getByRole("button", { name: "Повторить загрузку" }).click();
  await expect(page.getByTestId("v2-capital")).toHaveText("2 846 500 ₽");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 narrow viewport, large numbers and long labels remain operable", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "1440x900",
    "390px evidence stored alongside reference desktop",
  );
  const evidence = await installApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2?month=12");
  await expect(page.getByTestId("v2-capital")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-narrow");
  const workflow: MonthCloseWorkflow = makeUiV2Workflow();
  if (workflow.final_review.available)
    workflow.final_review.kpis.liquid_capital_net.amount = "9876543210123.45";
  workflow.steps[1].title =
    "Проверить состав портфеля и соответствие всех сохранённых позиций выбранной дате снимка";
  evidence.state.workflow = workflow;
  await page.reload();
  await expect(page.getByTestId("v2-capital")).toContainText("9 876 543 210 123,45 ₽");
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-narrow-long-content");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 invalid period makes no guessed workflow request", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Invalid URL behavior once");
  const evidence = await installApi(page);
  await page.goto("/v2?month=999");
  await expect(page.getByRole("heading", { name: "Месяц по ссылке не найден" })).toBeVisible();
  expect(evidence.reads.some((read) => read.includes("close-workflow"))).toBe(false);
  await capture(page, testInfo, "ui-v2-invalid-month");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});
