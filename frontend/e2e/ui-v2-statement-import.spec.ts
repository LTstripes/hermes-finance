import { expect, type Page, test } from "@playwright/test";

import {
  makeUiV2Workflow,
  uiV2Accounts,
  uiV2Instruments,
  uiV2Months,
} from "../src/test/uiV2Fixtures";

const statementMonth = uiV2Months.find((row) => row.id === 12);
if (!statementMonth) throw new Error("Synthetic statement month is missing");

const SYNTHETIC_PDF = Buffer.from(
  "%PDF-1.4\n% synthetic statement fixture for issue 567; no real data\n%%EOF\n",
  "utf8",
);

function money(amount: string) {
  return { amount, currency: "RUB" };
}

const statementInspect = {
  document_sha256: "synthetic-document-sha",
  status: "applicable",
  rows: [
    {
      status: "matched",
      provider_account_ref: "synthetic-broker",
      isin: "RU000SYNTH01",
      event_kind: "coupon",
      record_date: "2031-08-03",
      event_date: "2031-08-10",
      reason: null,
    },
  ],
  warnings: [],
  reason: null,
};

const statementPreparation = {
  provider: "alfa_pdf",
  document_sha256: "synthetic-document-sha",
  status: "applicable",
  warnings: [],
  reason: null,
  rows: [
    {
      status: "matched",
      duplicate_class: null,
      provider_account_ref: "synthetic-broker",
      expected_hermes_account_id: 3,
      expected_hermes_instrument_id: 11,
      natural_identity: "synthetic-row-1",
      material_fingerprint: "synthetic-fp-1",
      expected_candidate_ids: [],
      candidates: [],
      isin: "RU000SYNTH01",
      event_kind: "coupon",
      record_date: "2031-08-03",
      event_date: "2031-08-10",
      quantity: "10",
      per_unit: "10.00",
      gross_amount: "12450.00",
      gross_currency: "RUB",
      tax_amount: "1618.50",
      tax_available: true,
      tax_rate: "13.00",
      net_amount: "10831.50",
      net_currency: "RUB",
      reason: null,
    },
  ],
};

const appliedFlow = {
  id: 501,
  reporting_month_id: 12,
  account_id: 3,
  instrument_id: 11,
  flow_type: "coupon",
  event_date: "2031-08-10",
  gross_amount: money("12450.00"),
  tax_amount: money("1618.50"),
  commission_amount: money("0.00"),
  net_amount: money("10831.50"),
  currency: "RUB",
  source: "alfa_pdf",
  notes: null,
  statement_link: {
    applied_statement_event_id: 91,
    link_mode: "statement_created",
    status: "active",
  },
};

// One synthetic two-month ("spanning") document: August 2031 + September 2031.
const spanningInspect = {
  ...statementInspect,
  rows: [
    statementInspect.rows[0],
    {
      ...statementInspect.rows[0],
      record_date: "2031-09-03",
      event_date: "2031-09-10",
    },
  ],
};

const spanningPreparation = {
  ...statementPreparation,
  rows: [
    statementPreparation.rows[0],
    {
      ...statementPreparation.rows[0],
      natural_identity: "synthetic-row-2",
      material_fingerprint: "synthetic-fp-2",
      record_date: "2031-09-03",
      event_date: "2031-09-10",
    },
  ],
};

type ApiRecorder = {
  posts: string[];
  gets: string[];
  errors: string[];
  applySelections: string[];
};

type StatementApiOptions = { spanning?: boolean };

function readSelections(body: string | null): Array<{
  natural_identity: string;
  material_fingerprint: string;
}> {
  const match = /name="selections"\r?\n\r?\n([\s\S]*?)\r?\n/.exec(body ?? "");
  if (!match) {
    return [];
  }
  try {
    return JSON.parse(match[1]) as Array<{
      natural_identity: string;
      material_fingerprint: string;
    }>;
  } catch {
    return [];
  }
}

async function installStatementApi(
  page: Page,
  options: StatementApiOptions = {},
): Promise<ApiRecorder> {
  const record: ApiRecorder = { posts: [], gets: [], errors: [], applySelections: [] };
  const inspectFixture = options.spanning ? spanningInspect : statementInspect;
  const prepareFixture = options.spanning ? spanningPreparation : statementPreparation;
  page.on("pageerror", (error) => record.errors.push(error.message));
  // Record at the network layer so an explicitly overridden route still shows
  // what the page actually tried to send.
  page.on("request", (sent) => {
    const url = new URL(sent.url());
    if (!url.pathname.startsWith("/api/")) return;
    if (sent.method() === "POST") record.posts.push(`POST ${url.pathname}`);
    if (sent.method() === "GET") record.gets.push(`GET ${url.pathname}`);
  });
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const pathname = url.pathname;
      if (request.method() === "GET" && pathname === "/api/months") {
        await route.fulfill({ json: uiV2Months });
        return;
      }
      const monthMatch = /^\/api\/months\/(\d+)$/.exec(pathname);
      if (request.method() === "GET" && monthMatch) {
        const found = uiV2Months.find((row) => row.id === Number(monthMatch[1]));
        if (found) {
          await route.fulfill({ json: found });
          return;
        }
      }
      const readinessMatch = /^\/api\/months\/(\d+)\/close-readiness$/.exec(pathname);
      if (request.method() === "GET" && readinessMatch) {
        const found = uiV2Months.find((row) => row.id === Number(readinessMatch[1]));
        if (found) {
          await route.fulfill({
            json: {
              year: found.year,
              month: found.month,
              status: found.status,
              snapshot_date: found.snapshot_date,
              source: found.source,
              can_close: false,
              items: [],
            },
          });
          return;
        }
      }
      const refreshMatch = /^\/api\/months\/(\d+)\/payout-refresh-status$/.exec(pathname);
      if (request.method() === "GET" && refreshMatch) {
        await route.fulfill({
          json: {
            reporting_month_id: Number(refreshMatch[1]),
            positions_changed: 0,
            items: [],
          },
        });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/accounts") {
        await route.fulfill({ json: uiV2Accounts });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/instruments") {
        await route.fulfill({ json: uiV2Instruments });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/positions") {
        await route.fulfill({ json: [] });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/payouts/calendar") {
        await route.fulfill({ json: [] });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/expected-flows") {
        await route.fulfill({ json: [] });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/months/12/close-workflow") {
        await route.fulfill({ json: makeUiV2Workflow({ monthId: 12 }) });
        return;
      }
      if (request.method() === "GET" && pathname === "/api/investment-flows") {
        await route.fulfill({
          json: url.searchParams.get("month_id") === "12" ? [appliedFlow] : [],
        });
        return;
      }
      if (request.method() === "POST" && pathname === "/api/statement-import/inspect") {
        await route.fulfill({ json: inspectFixture });
        return;
      }
      if (request.method() === "POST" && pathname === "/api/statement-import/prepare") {
        await route.fulfill({ json: prepareFixture });
        return;
      }
      if (request.method() === "POST" && pathname === "/api/statement-import/apply") {
        // Answer only what was actually submitted: a month-scoped native
        // workspace must never send the September row of a spanning document.
        const body = await request.postDataBuffer();
        const selections = readSelections(body ? body.toString("utf8") : null);
        record.applySelections = selections.map((row) => row.natural_identity);
        await route.fulfill({
          json: {
            success: true,
            selected_count: selections.length,
            items: selections.map((row, index) => ({
              action: "created",
              applied_statement_event_id: 91 + index,
              investment_cash_flow_id: 501,
              natural_identity: row.natural_identity,
              material_fingerprint: row.material_fingerprint,
              revision_id: 92 + index,
            })),
            error_code: null,
            message: null,
          },
        });
        return;
      }
      await route.fulfill({
        status: 404,
        json: {
          error: { code: "fixture_missing", message: "Synthetic route missing", details: [] },
        },
      });
    },
  );
  return record;
}

async function assertNoPageOverflow(page: Page) {
  const report = await page.evaluate(() => {
    const limit = window.innerWidth;
    const offenders: string[] = [];
    for (const element of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      const rect = element.getBoundingClientRect();
      if (rect.width > 0 && rect.right > limit + 1) {
        offenders.push(
          `${element.tagName.toLowerCase()}${element.className ? `.${element.className}` : ""} right=${Math.round(rect.right)} width=${Math.round(rect.width)}`,
        );
      }
    }
    return {
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: limit,
      offenders: offenders.slice(0, 15),
    };
  });
  expect(report.scrollWidth, JSON.stringify(report, null, 2)).toBeLessThanOrEqual(
    report.innerWidth + 1,
  );
}

async function prepareStatement(page: Page) {
  await page.setInputFiles("#statement-file", {
    name: "synthetic-statement.pdf",
    mimeType: "application/pdf",
    buffer: SYNTHETIC_PDF,
  });
  await page.getByRole("button", { name: "Проверить отчёт" }).click();
  await expect(
    page.getByRole("cell", { name: "synthetic-broker", exact: true }).first(),
  ).toBeVisible();
  await page.getByLabel("Alfa-счёт synthetic-broker").selectOption("3");
  await page.getByLabel("Инструмент для RU000SYNTH01").selectOption("11");
  await page.getByRole("button", { name: "Подготовить к импорту" }).click();
  await expect(page.getByText("Новая строка").first()).toBeVisible();
  await page.getByRole("checkbox", { name: "Выбрать строку 1" }).check();
}

for (const viewport of [
  { name: "desktop", width: 1366, height: 900 },
  { name: "390px", width: 390, height: 844 },
]) {
  test(`native statement import ${viewport.name}: inspect/prepare/cancel/apply + readback`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const api = await installStatementApi(page);
    await page.goto("/v2/data/payouts?month=12");

    await expect(page.getByRole("heading", { level: 1, name: "Выплаты" })).toBeVisible();
    await expect(page.locator("#statement-import")).toBeVisible();
    // No file or provider action happens on mount.
    expect(api.posts).toEqual([]);
    await assertNoPageOverflow(page);
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-statement-mount.png`),
      fullPage: true,
    });

    // Selecting a file alone performs no request either.
    await page.setInputFiles("#statement-file", {
      name: "synthetic-statement.pdf",
      mimeType: "application/pdf",
      buffer: SYNTHETIC_PDF,
    });
    expect(api.posts).toEqual([]);

    await prepareStatement(page);
    expect(api.posts).toEqual([
      "POST /api/statement-import/inspect",
      "POST /api/statement-import/prepare",
    ]);
    // Inspect and prepare never write imported facts.
    expect(api.posts.filter((call) => call.startsWith("POST /api/investment-flows"))).toHaveLength(
      0,
    );
    // The prepared rows table scrolls inside its own container.
    const wrapOverflowX = await page
      .locator(".statement-import .table-wrap")
      .first()
      .evaluate((element) => getComputedStyle(element).overflowX);
    expect(wrapOverflowX).toBe("auto");
    await assertNoPageOverflow(page);
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-statement-prepare.png`),
      fullPage: true,
    });

    // Keyboard: open the confirm dialog, cancel it, and prove no write.
    const applyButton = page.getByRole("button", { name: "Применить выбранные строки" });
    await applyButton.focus();
    await expect(applyButton).toBeFocused();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-statement-confirm.png`),
      fullPage: true,
    });
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    expect(api.posts.filter((call) => call === "POST /api/statement-import/apply")).toHaveLength(0);

    // Keyboard confirm publishes success only after the exact-month reread.
    await applyButton.focus();
    await page.keyboard.press("Enter");
    await expect(dialog).toBeVisible();
    const confirmButton = dialog.getByRole("button", { name: "Подтвердить и применить" });
    await confirmButton.focus();
    await expect(confirmButton).toBeFocused();
    await page.keyboard.press("Enter");

    await expect(page.getByText(/Импортировано строк: 1/)).toBeVisible();
    expect(api.posts.filter((call) => call === "POST /api/statement-import/apply")).toHaveLength(1);
    expect(api.posts.filter((call) => call.startsWith("POST /api/investment-flows"))).toHaveLength(
      0,
    );
    expect(api.gets).toContain("GET /api/investment-flows");
    await expect(page.getByText(/не подтверждён повторной загрузкой/)).toHaveCount(0);
    await assertNoPageOverflow(page);
    expect(api.errors).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-statement-applied.png`),
      fullPage: true,
    });
  });

  test(`native statement import ${viewport.name}: stale month context cannot publish`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const api = await installStatementApi(page);
    await page.goto("/v2/data/payouts?month=12");
    await expect(page.locator("#statement-import")).toBeVisible();

    await prepareStatement(page);
    expect(api.posts).toHaveLength(2);

    // Switching the explicit month retires the prepared document.
    await page.getByLabel("Отчётный месяц").selectOption("91");
    await expect(page.getByRole("heading", { level: 1, name: "Выплаты" })).toBeVisible();
    await expect(page.getByText("Новая строка")).toHaveCount(0);
    expect(api.posts.filter((call) => call === "POST /api/statement-import/apply")).toHaveLength(0);
    expect(api.errors).toEqual([]);
    await assertNoPageOverflow(page);
  });

  test(`native statement import ${viewport.name}: ambiguous apply failure needs a fresh prepare`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const api = await installStatementApi(page);
    await page.goto("/v2/data/payouts?month=12");
    await expect(page.locator("#statement-import")).toBeVisible();
    await prepareStatement(page);

    await page.route("**/api/statement-import/apply", (route) => route.abort());
    await page.getByRole("button", { name: "Применить выбранные строки" }).click();
    await page.getByRole("button", { name: "Подтвердить и применить" }).click();

    // An ambiguous network result is never a success and never keeps a
    // replayable preparation behind.
    await expect(page.getByText(/результат неизвестен/)).toBeVisible();
    await expect(page.getByText(/Импортировано строк/)).toHaveCount(0);
    await expect(page.getByText("Новая строка")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Применить выбранные строки" })).toHaveCount(0);

    // Safe retry: a fresh explicit prepare of the same document restores a
    // reviewable, still-not-applied state.
    await page.unroute("**/api/statement-import/apply");
    await page.getByRole("button", { name: "Подготовить к импорту" }).click();
    await expect(page.getByText("Новая строка")).toBeVisible();
    expect(api.posts.filter((call) => call === "POST /api/statement-import/apply")).toHaveLength(1);
    expect(api.errors).toEqual([]);
  });
}

test("native spanning document: only the explicit month can be submitted", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const api = await installStatementApi(page, { spanning: true });
  await page.goto("/v2/data/payouts?month=12");
  await expect(page.locator("#statement-import")).toBeVisible();
  await prepareStatement(page);

  const checkboxes = page.getByRole("checkbox");
  await expect(checkboxes).toHaveCount(2);
  await expect(checkboxes.nth(0)).toBeEnabled();
  await expect(checkboxes.nth(1)).toBeDisabled();
  await expect(page.getByText(/строка относится к другому отчётному месяцу/)).toBeVisible();
  await expect(page.getByText("не применяется в этом месяце")).toBeVisible();

  await page.getByRole("button", { name: "Выбрать все готовые" }).click();
  await expect(checkboxes.nth(0)).toBeChecked();
  await expect(checkboxes.nth(1)).not.toBeChecked();

  await page.getByRole("button", { name: "Применить выбранные строки" }).click();
  await page.getByRole("button", { name: "Подтвердить и применить" }).click();

  await expect(page.getByText(/Импортировано строк: 1/)).toBeVisible();
  expect(api.applySelections).toEqual(["synthetic-row-1"]);
  expect(api.errors).toEqual([]);
});

test("legacy panel stays unconstrained across a spanning document", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  const api = await installStatementApi(page, { spanning: true });
  await page.goto("/payouts");
  await expect(page.getByRole("heading", { level: 1, name: "Автовыплаты" })).toBeVisible();
  await expect(page.locator("#statement-import")).toBeVisible();
  await prepareStatement(page);

  const checkboxes = page.getByRole("checkbox");
  await expect(checkboxes).toHaveCount(2);
  await expect(checkboxes.nth(0)).toBeEnabled();
  await expect(checkboxes.nth(1)).toBeEnabled();
  await expect(page.getByText(/строка относится к другому отчётному месяцу/)).toHaveCount(0);

  await page.getByRole("button", { name: "Выбрать все готовые" }).click();
  await expect(checkboxes.nth(0)).toBeChecked();
  await expect(checkboxes.nth(1)).toBeChecked();

  await page.getByRole("button", { name: "Применить выбранные строки" }).click();
  await page.getByRole("button", { name: "Подтвердить и применить" }).click();

  await expect(page.getByText(/Импортировано строк: 2/)).toBeVisible();
  expect(api.applySelections).toEqual(["synthetic-row-1", "synthetic-row-2"]);
  expect(api.errors).toEqual([]);
});

test("v2 Close actual_payouts routes to the native statement-import anchor and back", async ({
  page,
}) => {
  const api = await installStatementApi(page);
  await page.goto("/v2/close?month=12&step=actual_payouts");
  const chooseFile = page.getByRole("link", { name: "Выбрать выписку с выплатами" });
  await expect(chooseFile).toHaveAttribute(
    "href",
    "/v2/data/payouts?month=12&from=monthly-close-v2&step=actual_payouts&monthId=12#statement-import",
  );
  await chooseFile.focus();
  await expect(chooseFile).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(
    /\/v2\/data\/payouts\?month=12&from=monthly-close-v2&step=actual_payouts&monthId=12#statement-import$/,
  );
  await expect(page.locator("#statement-import")).toBeVisible();
  await expect(page.getByLabel("PDF отчёта Alfa")).toBeVisible();
  expect(api.posts).toEqual([]);

  const backToClose = page.getByRole("link", { name: "Вернуться к закрытию" });
  await expect(backToClose).toHaveAttribute("href", "/v2/close?month=12&step=actual_payouts");
  await backToClose.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/v2\/close\?month=12&step=actual_payouts$/);
  await expect(page.getByRole("heading", { level: 1, name: /Закрытие месяца/ })).toBeVisible();
  expect(api.errors).toEqual([]);
});
