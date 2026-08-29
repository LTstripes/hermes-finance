import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { type AuditState, syntheticApiResponse } from "./visual-fixtures";

type AuditRoute = {
  slug: string;
  path: string;
  prepare?: (page: Page) => Promise<void>;
};

const routes: AuditRoute[] = [
  { slug: "dashboard", path: "/" },
  { slug: "analytics", path: "/analytics" },
  { slug: "risk-allocation", path: "/analytics/risk-allocation" },
  { slug: "freshness", path: "/freshness" },
  {
    slug: "reconciliation",
    path: "/reconciliation",
    prepare: async (page) => {
      await page.getByLabel("Отчётный месяц").selectOption("12");
      await page.getByRole("button", { name: "Проверить снимок" }).click();
      await expect(
        page.getByRole("heading", { name: "Сверка без изменений данных" }),
      ).toBeVisible();
    },
  },
  { slug: "months", path: "/months" },
  { slug: "month-positions", path: "/months/12?section=positions" },
  { slug: "payouts", path: "/payouts" },
  {
    slug: "accounts-instruments",
    path: "/accounts",
    prepare: async (page) => {
      await page.getByRole("button", { name: "Инструменты" }).click();
      await expect(
        page.getByText("Синтетическая облигация", { exact: false }).first(),
      ).toBeVisible();
    },
  },
  { slug: "goals", path: "/goals" },
  { slug: "tax-iis-planner", path: "/tax-iis-planner" },
  { slug: "export", path: "/export" },
  { slug: "settings", path: "/settings" },
];

const forbiddenVisibleCopy = [
  /salary_tax_history_incomplete/i,
  /tax_brackets_unavailable/i,
  /issuer_not_persisted/i,
  /currency_not_persisted/i,
  /maturity_not_persisted/i,
  /broker_identity_not_persisted/i,
  /bank_identity_not_persisted/i,
  /instrument_mapping_unresolved/i,
  /mapping_unresolved/i,
  /\bowner-facing\b/i,
  /\bbackend\b/i,
  /\bread-only\b/i,
  /\bcomparison-only\b/i,
  /\bas_of_date\b/i,
  /\bfingerprint\b/i,
  /\bgross YTD\b/i,
  /\bmarginal\b/i,
  /\bsource_kind\b/i,
  /\bsource_id\b/i,
  /\baccount_id\b/i,
  /\binstrument_id\b/i,
  /\bmatched\b/i,
  /\bdiffers\b/i,
  /\bmissing_local\b/i,
  /\bmissing_provider\b/i,
];

async function installSyntheticApi(page: Page, state: AuditState = "content", delayMonths = false) {
  const unhandled: string[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }
    if (delayMonths && url.pathname === "/api/months") {
      await new Promise((resolve) => setTimeout(resolve, 1_500));
    }
    const response = syntheticApiResponse(url, request.method(), state);
    if (!response) {
      unhandled.push(`${request.method()} ${url.pathname}${url.search}`);
      await route.fulfill({
        status: 501,
        contentType: "application/json",
        json: {
          error: {
            code: "missing_visual_fixture",
            message: "Для этого synthetic audit запроса нет fixture.",
            details: [],
          },
        },
      });
      return;
    }
    await route.fulfill({
      status: response.status ?? 200,
      contentType: "application/json",
      json: response.json,
    });
  });
  return unhandled;
}

async function collectLayoutIssues(page: Page) {
  return page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const pageOverflow = Math.max(
      0,
      document.documentElement.scrollWidth - viewportWidth,
      document.body.scrollWidth - viewportWidth,
    );
    const escaped: string[] = [];
    const clippedControls: string[] = [];
    const selector = ".panel, .state-block, button, input, select, textarea";
    for (const element of document.querySelectorAll<HTMLElement>(selector)) {
      const style = getComputedStyle(element);
      if (style.display === "none" || style.visibility === "hidden") continue;
      if (element.closest(".table-wrap")) continue;
      const rect = element.getBoundingClientRect();
      if (rect.width > 0 && (rect.left < -1 || rect.right > viewportWidth + 1)) {
        const identity =
          element.getAttribute("aria-label") || element.textContent?.trim() || element.tagName;
        escaped.push(identity.slice(0, 120));
      }
      if (
        element.matches("button, input, select, textarea") &&
        (element.scrollWidth > element.clientWidth + 1 ||
          element.scrollHeight > element.clientHeight + 1)
      ) {
        const identity =
          element.getAttribute("aria-label") || element.textContent?.trim() || element.tagName;
        clippedControls.push(identity.slice(0, 120));
      }
    }
    const localTableEscapes = Array.from(document.querySelectorAll<HTMLElement>(".table-wrap"))
      .filter((wrapper) => {
        const rect = wrapper.getBoundingClientRect();
        return rect.left < -1 || rect.right > viewportWidth + 1;
      })
      .map((wrapper) => wrapper.textContent?.trim().slice(0, 120) || "table-wrap");
    const overflowCandidates = Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .filter((element) => {
        const style = getComputedStyle(element);
        if (style.display === "none" || style.visibility === "hidden") return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.right > viewportWidth + 1 && !element.closest(".table-wrap");
      })
      .slice(0, 12)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return `${element.tagName.toLowerCase()}.${element.className} right=${Math.round(rect.right)}`;
      });
    return { pageOverflow, escaped, clippedControls, localTableEscapes, overflowCandidates };
  });
}

async function assertAuditState(page: Page, unhandled: string[], pageErrors: string[]) {
  const layout = await collectLayoutIssues(page);
  expect(unhandled, "Every frontend API request must use an explicit synthetic fixture").toEqual(
    [],
  );
  expect(pageErrors, "The audited page must not throw runtime errors").toEqual([]);
  expect(
    layout.pageOverflow,
    `The document must not scroll horizontally. Candidates: ${layout.overflowCandidates.join(", ")}`,
  ).toBeLessThanOrEqual(1);
  expect(layout.escaped, "Panels and controls must stay inside the viewport").toEqual([]);
  expect(layout.clippedControls, "Controls must not clip their visible labels").toEqual([]);
  expect(
    layout.localTableEscapes,
    "Table scroll containers must remain inside their panels",
  ).toEqual([]);

  const visibleCopy = await page.locator("body").innerText();
  for (const forbidden of forbiddenVisibleCopy) {
    expect
      .soft(visibleCopy, `Visible owner-facing copy must not match ${forbidden}`)
      .not.toMatch(forbidden);
  }
}

for (const route of routes) {
  test(`${route.slug}: synthetic layout and owner copy`, async ({ page }, testInfo) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const unhandled = await installSyntheticApi(page);
    await page.goto(route.path);
    await expect(page.locator("h1").first()).toBeVisible();
    if (route.prepare) await route.prepare(page);
    await page.waitForTimeout(150);
    await assertAuditState(page, unhandled, pageErrors);

    const screenshotDir = path.resolve(".visual-audit", testInfo.project.name);
    fs.mkdirSync(screenshotDir, { recursive: true });
    await page.screenshot({
      path: path.join(screenshotDir, `${route.slug}.png`),
      fullPage: true,
      animations: "disabled",
    });
  });
}

test("loading, empty and error states stay bounded", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "State evidence is captured once at 1440×900");
  const screenshotDir = path.resolve(".visual-audit", testInfo.project.name);
  fs.mkdirSync(screenshotDir, { recursive: true });

  let unhandled = await installSyntheticApi(page, "content", true);
  await page.goto("/months");
  await expect(page.getByText("Загружаем отчётные месяцы…")).toBeVisible();
  await assertAuditState(page, unhandled, []);
  await page.screenshot({
    path: path.join(screenshotDir, "state-loading.png"),
    fullPage: true,
    animations: "disabled",
  });

  const emptyPage = await page.context().newPage();
  unhandled = await installSyntheticApi(emptyPage, "empty");
  await emptyPage.goto("/months");
  await expect(emptyPage.getByText(/Пока нет периодов/)).toBeVisible();
  await assertAuditState(emptyPage, unhandled, []);
  await emptyPage.screenshot({
    path: path.join(screenshotDir, "state-empty.png"),
    fullPage: true,
    animations: "disabled",
  });
  await emptyPage.close();

  const errorPage = await page.context().newPage();
  unhandled = await installSyntheticApi(errorPage, "error");
  await errorPage.goto("/months");
  await expect(errorPage.getByText("Не удалось загрузить", { exact: true })).toBeVisible();
  await assertAuditState(errorPage, unhandled, []);
  await errorPage.screenshot({
    path: path.join(screenshotDir, "state-error.png"),
    fullPage: true,
    animations: "disabled",
  });
  await errorPage.close();
});
