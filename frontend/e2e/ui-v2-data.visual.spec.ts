import fs from "node:fs";
import path from "node:path";

import { expect, type Page, type TestInfo, test } from "@playwright/test";

import { makeUiV2Freshness, makeUiV2ProviderCapabilities } from "../src/test/uiV2DataFixtures";
import {
  makeUiV2Workflow,
  uiV2Accounts,
  uiV2Instruments,
  uiV2Months,
} from "../src/test/uiV2Fixtures";
import { fulfillMonthPlate, syntheticApiResponse } from "./visual-fixtures";

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

async function installDataApi(page: Page) {
  const unexpected: string[] = [];
  const reads: string[] = [];
  const posts: string[] = [];
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
    const line = `${request.method()} ${url.pathname}`;
    if (request.method() === "GET") reads.push(line);
    if (request.method() === "POST") posts.push(line);
    let json: unknown;
    let status = 200;
    if (
      ["/api/health", "/api/backups", "/api/settings"].includes(url.pathname) ||
      /^\/api\/tax-brackets\/\d+$/.test(url.pathname)
    ) {
      const response = syntheticApiResponse(url, request.method(), "content");
      if (!response) throw new Error(`Missing settings fixture: ${line}`);
      json = response.json;
      status = response.status ?? 200;
    } else if (url.pathname === "/api/months") {
      json = uiV2Months;
    } else if (url.pathname === "/api/months/12/freshness-provenance") {
      json = makeUiV2Freshness(uiV2Months[1]);
    } else if (url.pathname === "/api/months/91/freshness-provenance") {
      json = makeUiV2Freshness(uiV2Months[0]);
    } else if (url.pathname === "/api/market-data/providers/capabilities") {
      json = makeUiV2ProviderCapabilities();
    } else if (url.pathname === "/api/months/12/close-workflow") {
      json = makeUiV2Workflow();
    } else if (
      request.method() === "GET" &&
      ((url.pathname === "/api/broker-months" && url.search === "?reporting_month_id=12") ||
        (url.pathname === "/api/broker-months/intakes" &&
          ["?reporting_month_id=12&include_unbound=true", "?include_unbound=true"].includes(
            url.search,
          )))
    ) {
      json = [];
    } else if (/^\/api\/instruments\/\d+\/market-mapping$/.test(url.pathname)) {
      const instrumentId = Number(url.pathname.split("/")[3]);
      json = {
        instrument_id: instrumentId,
        state: instrumentId === 10 ? "mapped" : "unmapped",
        identity:
          instrumentId === 10
            ? {
                provider: "t_invest",
                provider_instrument_id: "SYNTHETIC-UID-001",
                provider_venue_id: null,
              }
            : null,
        instrument_isin: null,
        legacy_moex_secid: null,
      };
    } else if (url.pathname === "/api/broker-identity-mappings") {
      json = [
        {
          mapping_id: 20,
          provider: "alfa_pro",
          subject_kind: "account",
          provider_identity: "SYNTHETIC-ACCOUNT-001",
          hermes_target_id: 1,
          status: "effective",
          observed_isin: null,
          confirmed_at: "2031-08-31T12:00:00Z",
          source_as_of: null,
          captured_at: null,
          predecessor_mapping_id: null,
          successor_mapping_id: null,
          revoked_at: null,
          revoke_reason: null,
        },
      ];
    } else if (url.pathname === "/api/accounts") {
      json = uiV2Accounts;
    } else if (url.pathname === "/api/instruments") {
      json = uiV2Instruments;
    } else if (request.method() !== "GET") {
      unexpected.push(line);
      await route.abort();
      return;
    } else {
      unexpected.push(line);
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
  return { errors, posts, reads, unexpected };
}

async function installFilesApi(page: Page, hasBackups = true) {
  const unexpected: string[] = [];
  const posts: string[] = [];
  const errors: string[] = [];
  const backup = {
    id: "synthetic-backup-2031-12-28",
    name: "synthetic-finance-visual-audit.db",
    created_at: "2031-12-28T12:00:00+00:00",
    size_bytes: 987654321,
    source_database: { name: "synthetic-finance.db", size_bytes: 987654321 },
  };
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["127.0.0.1", "localhost"].includes(url.hostname)) {
      unexpected.push(`external: ${url.origin}`);
    }
  });
  await page.route("**/api/**", async (route) => {
    if (await fulfillMonthPlate(route)) return;
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) {
      await route.continue();
      return;
    }
    const line = `${request.method()} ${url.pathname}`;
    if (request.method() === "POST") posts.push(line);
    if (request.method() === "GET" && url.pathname === "/api/months") {
      await route.fulfill({ status: 200, json: uiV2Months });
      return;
    }
    if (request.method() === "GET" && url.pathname === "/api/backups") {
      await route.fulfill({ status: 200, json: hasBackups ? [backup] : [] });
      return;
    }
    unexpected.push(line);
    await route.fulfill({
      status: 404,
      json: { error: { code: "synthetic_missing", message: "Missing fixture", details: [] } },
    });
  });
  return { errors, posts, unexpected, backup };
}

test("Settings sidebar remains visible and scrolls independently on a short desktop", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "One desktop ownership check");
  await installDataApi(page);
  await page.setViewportSize({ width: 1440, height: 320 });
  await page.goto("/v2/data");
  await expect(page.getByTestId("freshness-clocks")).toBeVisible();
  const sidebar = page.locator("aside");
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  const box = await sidebar.boundingBox();
  expect(box).not.toBeNull();
  // Fractional document heights may round sticky containment by half a CSS pixel.
  expect(Math.abs(box?.y ?? Number.POSITIVE_INFINITY)).toBeLessThanOrEqual(1);
  expect(box?.height).toBe(320);
  expect(await sidebar.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(
    true,
  );
  await sidebar.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect(sidebar.getByRole("link", { name: /Рабочий месяц/ })).toBeInViewport();
  const main = await page.locator("#v2-main").boundingBox();
  expect(main && box && main.x >= box.x + box.width).toBeTruthy();
  await assertBounded(page);
});

test("ui-v2 Data sources desktop: freshness clocks and handoff stay bounded", async ({
  page,
}, testInfo) => {
  const evidence = await installDataApi(page);
  await page.goto("/v2/data");
  await expect(page.getByRole("heading", { name: "Источники и актуальность" })).toBeVisible();
  await expect(page.getByTestId("data-month-context")).toContainText("Август 2031");
  await expect(page.getByTestId("freshness-clocks")).toBeVisible();
  await expect(page.getByTestId("freshness-family-market_quotes")).toBeVisible();
  await expect(page.getByRole("link", { name: "Настройки", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-data-sources-desktop");
  expect(evidence.posts).toEqual([]);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 settings overview stays bounded at desktop widths and zoom @viewport-owned", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Viewport matrix captured once");
  const evidence = await installDataApi(page);
  for (const [width, zoom] of [
    [1024, 1],
    [1280, 1],
    [1280, 1.25],
    [1440, 1],
    [1440, 1.25],
    [1920, 1],
    [1920, 1.25],
  ]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/v2/data/overview?month=12");
    await expect(page.getByText(/Версия 0.7.0-synthetic/)).toBeVisible();
    await page.evaluate((value) => {
      document.documentElement.style.zoom = String(value);
    }, zoom);
    await assertBounded(page);
    await expect(page.locator("#v2-main h2")).toHaveCount(5);
    await capture(page, testInfo, `settings-overview-${width}-${zoom}`);
  }
  expect(evidence.posts).toEqual([]);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Data navigation keeps native Close context through keyboard, back and refresh", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Navigation evidence captured once");
  const evidence = await installDataApi(page);
  const sourcePath = "/v2/data?month=12&from=monthly-close-v2&step=readiness&monthId=12";
  const intakePath =
    "/v2/data/source-intake?month=12&from=monthly-close-v2&step=readiness&monthId=12";
  await page.goto(sourcePath);
  await expect(page.getByTestId("data-month-context")).toContainText("Август 2031");
  await expect(page.getByRole("link", { name: "Экспорт и копии" })).toHaveAttribute(
    "href",
    "/v2/data/files?month=12&from=monthly-close-v2&step=readiness&monthId=12",
  );
  await expect(page.getByRole("link", { name: "Настройки", exact: true }).first()).toHaveAttribute(
    "href",
    "/v2/data/overview",
  );
  await expect(page.getByRole("link", { name: "Диагностика", exact: true })).toHaveCount(0);
  const appPath = "/v2/data/app?month=12&from=monthly-close-v2&step=readiness&monthId=12";
  await page.getByRole("link", { name: "Приложение", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${appPath.replaceAll("?", "\\?")}$`));
  await page.getByRole("link", { name: "Диагностика", exact: true }).click();
  const intake = page.getByRole("link", { name: "Разбор источника" });
  await intake.focus();
  await expect(intake).toBeFocused();
  await intake.press("Enter");
  await expect(page).toHaveURL(new RegExp(`${intakePath.replaceAll("?", "\\?")}$`));
  await expect(page.getByRole("heading", { level: 1, name: "Разбор источника" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Разбор источника" })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`${appPath.replaceAll("?", "\\?")}#diagnostics$`));
  await page.getByRole("link", { name: "Источники данных", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${sourcePath.replaceAll("?", "\\?")}#diagnostics$`));
  await expect(page.getByRole("link", { name: "Открыть закрытие месяца →" })).toHaveAttribute(
    "href",
    "/v2/close?month=12&step=readiness",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-navigation-desktop");
  await Promise.all([
    page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        response.request().method() === "GET" &&
        url.pathname === "/api/months/12/close-workflow" &&
        response.status() === 200
      );
    }),
    page.getByRole("link", { name: "Открыть закрытие месяца →" }).press("Enter"),
  ]);
  await expect(page).toHaveURL(/\/v2\/close\?month=12&step=readiness$/);
  await expect(page.getByRole("heading", { level: 1, name: "Август 2031" })).toBeVisible();
  expect(evidence.posts).toEqual([]);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Catalogs desktop: accounts, instruments and mappings stay bounded", async ({
  page,
}, testInfo) => {
  const evidence = await installDataApi(page);
  await page.goto("/v2/data/catalogs");
  await expect(page.getByRole("heading", { name: "Справочники и сопоставления" })).toBeVisible();
  await expect(page.getByTestId("catalog-accounts")).toBeVisible();
  await expect(page.getByText("Синтетический брокерский счёт", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: /Инструменты/ }).click();
  await expect(page.getByText("Синтетическая акция", { exact: true })).toBeVisible();
  await expect(page.getByTestId("catalog-mapping-identity-10")).toContainText("SYNTHETIC-UID-001");
  await page.getByRole("tab", { name: /Постоянные сопоставления/ }).click();
  await expect(page.getByText("SYNTHETIC-ACCOUNT-001", { exact: true })).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-data-catalogs-desktop");
  expect(evidence.posts).toEqual([]);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Files desktop: exports and irreversible restore remain separated", async ({
  page,
}, testInfo) => {
  const evidence = await installFilesApi(page);
  await page.goto("/v2/data/files");
  await expect(page.getByRole("heading", { name: "Экспорт и копии" })).toBeVisible();
  await expect(page.getByTestId("files-exports")).toBeVisible();
  await expect(page.getByTestId("files-backups")).toBeVisible();
  await expect(page.getByText("Необратимо")).toHaveCount(0);
  await expect(page.getByText(evidence.backup.name)).toBeVisible();
  await expect(page.getByText("Технические выгрузки").locator("..")).not.toHaveAttribute("open");

  await expect(page.getByRole("menuitem")).toHaveCount(0);
  await page.getByRole("button", { name: `Действия с копией ${evidence.backup.name}` }).click();
  await page
    .getByRole("menuitem", { name: `Восстановить резервную копию ${evidence.backup.name}` })
    .click();
  await expect(page.getByRole("alertdialog")).toContainText(
    `Выбрана копия: ${evidence.backup.name}`,
  );
  await expect(page.getByRole("alertdialog")).toContainText("Это необратимое действие");
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-data-files-restore-confirmation-desktop");
  expect(evidence.posts).toEqual([]);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("@viewport-owned Export and copies fit desktop zoom and 720px content", async ({
  page,
}, testInfo) => {
  for (const hasBackups of [false, true]) {
    await page.unroute("**/api/**");
    const evidence = await installFilesApi(page, hasBackups);
    await page.goto("/v2/data/files");
    await expect(page.getByRole("heading", { level: 1, name: "Экспорт и копии" })).toBeVisible();
    if (!hasBackups) {
      await expect(page.getByTestId("files-no-backups")).toBeVisible();
      await expect(page.getByTestId("files-backups")).not.toContainText(/восстановлен|необратимо/i);
    } else {
      await expect(page.getByRole("table", { name: "Резервные копии" })).toBeVisible();
      await expect(page.getByLabel("Месяц отчёта")).toHaveValue("91");
    }
    for (const width of [1024, 1280, 1440, 1920]) {
      for (const zoom of [1, 1.25]) {
        await page.setViewportSize({ width, height: 900 });
        await page.evaluate((value) => {
          document.documentElement.style.zoom = String(value);
        }, zoom);
        await assertBounded(page);
        const create = await page
          .getByRole("button", { name: "Создать копию", exact: true })
          .boundingBox();
        expect(create && create.x >= 0 && create.x + create.width <= width).toBeTruthy();
        if (width === 1280 && zoom === 1.25)
          await capture(page, testInfo, `export-${hasBackups ? "copies" : "empty"}-1280-zoom125`);
      }
    }
    await page.evaluate(() => {
      document.documentElement.style.zoom = "1";
      const content = document.querySelector<HTMLElement>('[data-testid="data-files-page"]');
      if (content) content.style.width = "720px";
    });
    expect(
      await page
        .getByTestId("files-backups")
        .evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);
    expect(evidence.posts).toEqual([]);
    expect(evidence.unexpected).toEqual([]);
    expect(evidence.errors).toEqual([]);
  }
});
