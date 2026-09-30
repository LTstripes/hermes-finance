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
    if (url.pathname === "/api/months") {
      json = uiV2Months;
    } else if (url.pathname === "/api/months/12/freshness-provenance") {
      json = makeUiV2Freshness(uiV2Months[1]);
    } else if (url.pathname === "/api/months/91/freshness-provenance") {
      json = makeUiV2Freshness(uiV2Months[0]);
    } else if (url.pathname === "/api/market-data/providers/capabilities") {
      json = makeUiV2ProviderCapabilities();
    } else if (url.pathname === "/api/months/12/close-workflow") {
      json = makeUiV2Workflow();
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
    } else if (url.pathname === "/api/months/12/broker-reconciliation-preview") {
      if (request.method() !== "POST") {
        unexpected.push(`${request.method()} ${url.pathname}`);
        await route.abort();
        return;
      }
      json = {
        reporting_month_id: 12,
        provider: "alfa_pro",
        status: "applicable",
        read_only: true,
        eligible_for_apply: false,
        stale: false,
        snapshot_status: "complete",
        compatibility_state: "compatible",
        compatibility_fingerprint: "a".repeat(64),
        snapshot_fingerprint: "b".repeat(64),
        source_as_of: "2031-08-30T12:00:00+00:00",
        captured_at: "2031-08-30T12:05:00+00:00",
        month_status: "draft",
        month_closed: false,
        accounts: [],
        instruments: [],
        rows: [],
        cash: [],
        warnings: [],
        diagnostics: {
          schema_version: "alfa-pro-diagnostics/v1",
          provider: "alfa_pro",
          snapshot_status: "complete",
          eligible_for_apply: false,
          compatibility_state: "compatible",
          compatibility_fingerprint: "a".repeat(64),
          api_doc_version: "synthetic",
          observed_alfa_pro_version: null,
          observed_api_version: null,
          observed_protocol_version: null,
          protocol_family: "router-v1",
          layout_family: "snapshot-v2.1",
          capabilities: [],
          failure_class: "none",
          failure_codes: [],
          entity_status: [],
          entity_counts: [],
          observed_fields: [],
          safe_artifact: true,
          raw_payload_saved: false,
          private_values_included: false,
          credentials_included: false,
        },
        diagnostic_report: "synthetic",
        error_code: null,
        message: null,
      };
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

async function installFilesApi(page: Page) {
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
      await route.fulfill({ status: 200, json: [backup] });
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

test("ui-v2 Data sources desktop: freshness clocks and handoff stay bounded", async ({
  page,
}, testInfo) => {
  const evidence = await installDataApi(page);
  await page.goto("/v2/data");
  await expect(page.getByRole("heading", { name: "Источники и актуальность" })).toBeVisible();
  await expect(page.getByTestId("data-month-context")).toContainText("Август 2031");
  await expect(page.getByTestId("freshness-clocks")).toBeVisible();
  await expect(page.getByTestId("freshness-family-market_quotes")).toBeVisible();
  await expect(page.getByRole("link", { name: "Данные", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-data-sources-desktop");
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
  const reconciliationPath =
    "/v2/data/reconciliation?month=12&from=monthly-close-v2&step=readiness&monthId=12";
  await page.goto(sourcePath);
  await expect(page.getByTestId("data-month-context")).toContainText("Август 2031");
  await expect(page.getByRole("link", { name: "Экспорт и копии" })).toHaveAttribute(
    "href",
    "/v2/data/files",
  );
  await expect(page.getByRole("link", { name: "Диагностика" })).toHaveAttribute(
    "href",
    "/v2/data/app#diagnostics",
  );
  const reconciliation = page.getByRole("link", { name: "Сверка портфеля" });
  await reconciliation.focus();
  await expect(reconciliation).toBeFocused();
  await reconciliation.press("Enter");
  await expect(page).toHaveURL(new RegExp(`${reconciliationPath.replaceAll("?", "\\?")}$`));
  await expect(page.getByTestId("reconciliation-idle")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("reconciliation-idle")).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`${sourcePath.replaceAll("?", "\\?")}$`));
  await expect(page.getByRole("link", { name: "Открыть закрытие месяца →" })).toHaveAttribute(
    "href",
    "/v2/close?month=12&step=readiness",
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-navigation-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-navigation-narrow");
  await page.getByRole("link", { name: "Открыть закрытие месяца →" }).press("Enter");
  await expect(page).toHaveURL(/\/v2\/close\?month=12&step=readiness$/);
  await expect(page.getByRole("heading", { name: /Закрытие месяца/ })).toBeVisible();
  expect(evidence.posts).toEqual([]);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Data sources narrow: chips and stacked clocks remain operable", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "390px evidence stored with reference desktop");
  const evidence = await installDataApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2/data");
  await expect(page.getByTestId("freshness-clocks")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-data-sources-narrow");
  expect(evidence.posts).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Data reconciliation: no provider call on mount; preview only on click", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "Reconciliation proof captured once");
  const evidence = await installDataApi(page);
  await page.goto("/v2/data/reconciliation");
  await expect(page.getByTestId("reconciliation-idle")).toBeVisible();
  await expect(page.getByTestId("reconciliation-safety-note")).toContainText(
    "Сверка только показывает различия и ничего не сохраняет",
  );
  expect(evidence.posts).toEqual([]);
  await page.getByRole("button", { name: "Проверить снимок" }).click();
  await expect(page.getByTestId("reconciliation-result")).toBeVisible();
  await expect(page.getByText("eligible_for_apply", { exact: false })).toHaveCount(0);
  expect(evidence.posts).toEqual(["POST /api/months/12/broker-reconciliation-preview"]);
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-data-reconciliation-desktop");
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Data reconciliation narrow: owner copy and action stay bounded", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "390px evidence stored with reference desktop");
  const evidence = await installDataApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2/data/reconciliation");
  await expect(page.getByTestId("reconciliation-idle")).toBeVisible();
  await expect(page.getByTestId("reconciliation-safety-note")).toContainText(
    "Данные брокера запрашиваются только после нажатия",
  );
  expect(evidence.posts).toEqual([]);
  await page.getByRole("button", { name: "Проверить снимок" }).click();
  await expect(page.getByTestId("reconciliation-result")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-data-reconciliation-narrow");
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

test("ui-v2 Catalogs narrow: catalog controls remain operable", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "390px evidence stored with reference desktop");
  const evidence = await installDataApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2/data/catalogs");
  await expect(page.getByTestId("catalog-accounts")).toBeVisible();
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-data-catalogs-narrow");
  expect(evidence.posts).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Files desktop: exports and irreversible restore remain separated", async ({
  page,
}, testInfo) => {
  const evidence = await installFilesApi(page);
  await page.goto("/v2/data/files");
  await expect(page.getByRole("heading", { name: "Файлы" })).toBeVisible();
  await expect(page.getByTestId("files-exports")).toBeVisible();
  await expect(page.getByTestId("files-backups")).toBeVisible();
  await expect(page.getByText("Необратимо")).toBeVisible();
  await expect(page.getByText(evidence.backup.name)).toBeVisible();
  await expect(
    page.getByText("Дополнительные / технические выгрузки").locator(".."),
  ).not.toHaveAttribute("open");

  await page
    .getByRole("button", { name: `Восстановить резервную копию ${evidence.backup.name}` })
    .click();
  await expect(page.getByRole("alertdialog")).toContainText(
    `Выбрана копия: ${evidence.backup.name}`,
  );
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-data-files-restore-confirmation-desktop");
  expect(evidence.posts).toEqual([]);
  expect(evidence.unexpected).toEqual([]);
  expect(evidence.errors).toEqual([]);
});

test("ui-v2 Files narrow: mutation gate and backup cards stay operable", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "1440x900", "390px evidence stored with reference desktop");
  const evidence = await installFilesApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2/data/files");
  await expect(page.getByTestId("files-exports")).toBeVisible();
  await expect(page.getByTestId("files-backups")).toBeVisible();
  await page
    .getByRole("button", { name: `Восстановить резервную копию ${evidence.backup.name}` })
    .click();
  await expect(page.getByRole("alertdialog")).toContainText("Это необратимое действие");
  await assertBounded(page);
  await capture(page, testInfo, "ui-v2-data-files-restore-confirmation-narrow");
  expect(evidence.posts).toEqual([]);
  expect(evidence.errors).toEqual([]);
});
