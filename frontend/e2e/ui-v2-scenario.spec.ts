import { expect, type Page, test } from "@playwright/test";
import {
  MONTHS,
  equityEnvelope,
  depositEnvelope,
  inflationEnvelope,
  fxEnvelope,
} from "../src/test/scenarioLabFixtures";

const months = [
  { id: 2, year: 2030, month: 6, status: "draft", snapshot_date: "2030-06-12", source: "manual" },
  { id: 1, year: 2030, month: 5, status: "closed", snapshot_date: "2030-05-12", source: "manual" },
];

function result(monthId: number) {
  const month = months.find((item) => item.id === monthId) ?? months[1];
  return {
    contract_version: "r07-09-v1",
    calculation_version: "r07-09-v1",
    shock_schema_version: "v1",
    reporting_month: month,
    base_fingerprint: "synthetic-base",
    semantic_fingerprint: "synthetic-scenario",
    normalized_shock_input: { shock_type: "equity_drawdown", drawdown_pct: "10" },
    normalized_target_scope: {},
    assumptions: ["dividends_unchanged", "no_provider_network"],
    base: {
      liquid_assets: "10000.00",
      liquid_capital_net: "9000.00",
      per_position: {
        "1": {
          account_id: 1,
          instrument_id: 1,
          instrument_type: "stock",
          market_value: "10000.00",
        },
      },
    },
    stressed: {
      liquid_assets: "9000.00",
      liquid_capital_net: "8000.00",
      per_position: {
        "1": { account_id: 1, instrument_id: 1, instrument_type: "stock", market_value: "9000.00" },
      },
    },
    impact: {
      known_scope_impact: "-1000.00",
      liquid_assets_delta: "-1000.00",
      liquid_capital_net_delta: "-1000.00",
      per_position: { "1": { applicability: "applied", delta: "-1000.00", reason_codes: [] } },
    },
    row_applicability: {},
    metric_support: { liquid_assets: { status: "supported", reason_codes: [] } },
    coverage: {
      applied: 1,
      not_applicable: 0,
      unknown: 0,
      total_positions: 1,
      eligible_positions: 1,
    },
    affected_canonical_refs: {},
    warnings: [],
    generated_at: null,
    presentation_metadata: {
      instrument_names: { "1": "Синтетическая акция" },
      account_names: { "1": "Тестовый счёт" },
    },
  };
}

test("ui-v2 scenarios: all four results fit desktop widths and zoom @viewport-owned", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  const envelopes = {
    equity_drawdown: equityEnvelope(),
    deposit_rate_assumption: depositEnvelope(),
    inflation_real_value: inflationEnvelope(),
    fx_translation_shock: fxEnvelope(),
  };
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname === "/api/months") return route.fulfill({ json: MONTHS });
      if (request.method() === "POST" && pathname === "/api/months/1/scenario-lab") {
        const type = Object.keys(request.postDataJSON().shock)[0] as keyof typeof envelopes;
        return route.fulfill({ json: envelopes[type] });
      }
      return route.fulfill({ status: 404, json: {} });
    },
  );
  const choices = [
    ["Падение акций", "Размер просадки акций, %"],
    ["Ставка по вкладам", "Гипотетическая годовая ставка по вкладам, %"],
    ["Инфляция и реальная стоимость", "Годовая инфляция, %"],
    ["Валютный шок", "Изменение стоимости в отчёте, %"],
  ];
  for (const [scenario, parameter] of choices) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/v2/income/scenario-lab?month=1");
    await page.getByRole("radio", { name: new RegExp(`^${scenario}`) }).check();
    await expect(page.getByRole("button", { name: "Скачать расчёт (JSON)" })).toHaveCount(0);
    await expect(page.locator("button:disabled")).toHaveCount(0);
    await page.getByRole("textbox", { name: parameter }).fill("10");
    await page.getByRole("button", { name: "Рассчитать сценарий" }).click();
    const answer = page.locator(".scenario-lab__answer");
    await expect(answer).toBeVisible();
    expect((await answer.boundingBox())?.y).toBeLessThan(500);
    for (const width of [1024, 1280, 1440, 1920]) {
      for (const zoom of [1, 1.25]) {
        await page.setViewportSize({ width, height: 900 });
        await page.evaluate((value) => {
          document.documentElement.style.zoom = String(value);
        }, zoom);
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
          ),
        ).toBe(true);
        for (const table of await page.locator("table:visible").all()) {
          expect(
            await table.evaluate((element) => element.scrollWidth <= element.clientWidth + 1),
          ).toBe(true);
        }
        await page.screenshot({
          path: testInfo.outputPath(`${scenario}-${width}-${zoom}.png`),
          fullPage: true,
        });
      }
    }
    await page.evaluate(() => {
      document.documentElement.style.zoom = "1";
    });
  }
});

async function installSyntheticApi(page: Page) {
  const calls: string[] = [];
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      calls.push(`${request.method()} ${pathname}`);
      if (request.method() === "GET" && pathname === "/api/months") {
        await route.fulfill({ json: months });
      } else if (
        request.method() === "POST" &&
        /^\/api\/months\/[12]\/scenario-lab$/.test(pathname)
      ) {
        await route.fulfill({ json: result(Number(pathname.split("/")[3])) });
      } else {
        await route.fulfill({
          status: 404,
          json: { error: { code: "missing_synthetic_fixture", details: [] } },
        });
      }
    },
  );
  return calls;
}

for (const viewport of [{ name: "desktop", width: 1366, height: 900 }]) {
  test(`native Scenario Lab ${viewport.name}: deep link, calculate, keyboard, back and refresh`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const calls = await installSyntheticApi(page);
    await page.goto("/v2/income/scenario-lab?month=2");
    await expect(page.getByRole("heading", { level: 1, name: "Доход и планы" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Отчётный месяц" })).toHaveValue("2");
    expect(calls.filter((call) => call.includes("scenario-lab"))).toHaveLength(0);
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-controls.png`),
      fullPage: true,
    });

    await page.getByRole("textbox", { name: "Размер просадки акций, %" }).fill("10");
    await page.getByRole("textbox", { name: "Размер просадки акций, %" }).press("Tab");
    await expect(page.getByRole("button", { name: "Рассчитать сценарий" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Падение акций" })).toBeVisible();
    await expect(page.getByText("Синтетическая акция")).toBeVisible();
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-result.png`),
      fullPage: true,
    });

    await page.getByRole("combobox", { name: "Отчётный месяц" }).selectOption("1");
    await expect(page).toHaveURL(/month=1$/);
    await expect(page.getByRole("heading", { name: "Падение акций" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Скачать расчёт (JSON)" })).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("combobox", { name: "Отчётный месяц" })).toHaveValue("1");
    await page.goBack();
    await expect(page.getByRole("combobox", { name: "Отчётный месяц" })).toHaveValue("2");
    await page.goto("/v2/income/scenario-lab?month=bad");
    await expect(page.getByRole("alert")).toContainText("недействителен");
    await expect(page.getByRole("button", { name: "Рассчитать сценарий" })).toBeEnabled();
    await page.getByRole("button", { name: "Рассчитать сценарий" }).click();
    await expect(page.getByText("Выберите отчётный месяц.", { exact: true })).toBeVisible();
  });
}
