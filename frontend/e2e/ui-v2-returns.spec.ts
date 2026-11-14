import fs from "node:fs";
import path from "node:path";
import { expect, type Page, type Route, test } from "@playwright/test";
import {
  april,
  basketFixture,
  contextFixture,
  detailFixture,
  longHistoryContext,
  longHistoryOverview,
  longHistoryPeriods,
  may,
  overviewFixture,
} from "../src/ui-v2/returns/fixtures";
import { instrumentCardFixture, overallFixture } from "../src/ui-v2/returns/overallFixtures";
import { fulfillMonthPlate } from "./visual-fixtures";

async function fulfillReturnsNeighbour(route: Route) {
  const url = new URL(route.request().url());
  if (url.pathname === "/api/returns/context") {
    expect(route.request().method()).toBe("GET");
    await route.fulfill({ json: contextFixture });
    return true;
  }
  if (url.pathname === "/api/returns/overview") {
    expect(route.request().method()).toBe("GET");
    await route.fulfill({
      json: overviewFixture(url.searchParams.get("scope") ?? undefined, {
        start: url.searchParams.get("start") ?? may.start,
        end: url.searchParams.get("end") ?? may.end,
      }),
    });
    return true;
  }
  return false;
}

for (const provisional of [false, true]) {
  test(`B9 annual portfolio rate (provisional=${provisional}) and account filter fit desktop zoom @viewport-owned`, async ({
    page,
  }, info) => {
    const body = overallFixture();
    const annual = {
      pnl: body.overall.pnl,
      rate: {
        ...body.overall.rate,
        value: "0.125",
        estimate: true,
        reason_codes: [
          provisional
            ? "overall_short_holding_provisional"
            : "overall_small_unknown_assumed_internal",
        ],
        method: "portfolio_inception_xirr",
      },
      first_operation_date: "2028-01-01",
      valuation_date: "2030-12-31",
      weighted_holding_days: provisional ? "253" : "500",
      eligibility_basis: "capital_weighted_holding_days" as const,
    };
    body.annual_return = {
      portfolio: annual,
      accounts: [
        {
          ...annual,
          scope: body.source_accounts[0].scope,
          rate: provisional
            ? { ...annual.rate, value: "0.1558" }
            : { ...annual.rate, value: null, reason_codes: ["overall_source_proof_stale"] },
        },
      ],
    };
    await page.route(
      (url) => url.pathname.startsWith("/api/"),
      async (route) => {
        if (await fulfillMonthPlate(route)) return;
        expect(route.request().method()).toBe("GET");
        await route.fulfill({ json: body });
      },
    );
    for (const zoom of [1, 1.25]) {
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.goto("/v2/returns");
      await page.evaluate((scale) => {
        document.documentElement.style.zoom = String(scale);
      }, zoom);
      const rate = page.getByRole("region", { name: "Годовая доходность" });
      await expect(rate).toContainText("12,5");
      await expect(rate).toContainText("годовых, с");
      if (provisional) {
        await expect(rate).toContainText("≈12,5%");
        await expect(rate).toContainText(
          "деньги вложены в среднем 8 мес. — процент пока предварительный",
        );
      } else await expect(rate).toContainText("Оценка: нераспознанные операции менее 100 ₽");
      await rate.screenshot({ path: info.outputPath(`b9-annual-${zoom}.png`) });
      await page
        .getByRole("button", {
          name: body.source_accounts[0].account_link?.label ?? body.source_accounts[0].label,
          exact: true,
        })
        .click();
      if (provisional) {
        await expect(rate).toContainText("≈15,6%");
        await expect(rate).toContainText("деньги вложены в среднем 8 мес.");
        await rate.screenshot({ path: info.outputPath(`b9-account-${zoom}.png`) });
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
        ).toBe(true);
        continue;
      }
      await expect(rate).toHaveCount(0);
      const reason = page.getByText(
        "Годовая доходность пока неизвестна: подтверждение истории счёта требует проверки.",
        { exact: true },
      );
      await expect(reason).toBeVisible();
      await expect(page.getByText("overall_source_proof_stale", { exact: true })).toHaveCount(0);
      await reason.screenshot({ path: info.outputPath(`b9-unknown-${zoom}.png`) });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
    }
  });
}

test("paper aggregate, open filter and result split fit 720px at desktop zoom @viewport-owned", async ({
  page,
}, info) => {
  const body = overallFixture();
  const card = instrumentCardFixture();
  const metric = (value: string | null) => ({
    value,
    status: "supported" as const,
    reason_codes: [],
    assumptions: [],
  });
  const rate = (method: "simple_return" | "xirr") => ({
    ...metric("0.125"),
    method,
    annualized: method === "xirr",
    invested_kopecks: "100000000",
    start_date: "2028-01-01",
    end_date: "2030-01-01",
    holding_days: 731,
    weighted_holding_days: "731.00",
  });
  const aggregate = {
    pnl: metric("12500000"),
    realized_result: metric("10000000"),
    unrealized_result: metric("2500000"),
    current_value: metric("102500000"),
    is_open: true,
    position_reason_codes: [],
    simple_return: rate("simple_return"),
    xirr: rate("xirr"),
  };
  body.instruments = [
    { ...body.instruments[0], aggregate },
    {
      ...body.instruments[1],
      name: "Проданная бумага",
      aggregate: {
        ...aggregate,
        is_open: false,
        current_value: metric("0"),
        unrealized_result: metric("0"),
        realized_result: metric("12500000"),
      },
    },
  ];
  card.aggregate = aggregate;
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      if (await fulfillMonthPlate(route)) return;
      expect(route.request().method()).toBe("GET");
      await route.fulfill({
        json: new URL(route.request().url()).pathname.endsWith("instrument-card") ? card : body,
      });
    },
  );
  for (const zoom of [1, 1.25]) {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/v2/returns?split=1");
    await page.evaluate((scale) => {
      document.documentElement.style.zoom = String(scale);
    }, zoom);
    const table = page.getByRole("table", { name: "Все бумаги", exact: true });
    await expect(table.getByText("Учебная акция", { exact: true })).toBeVisible();
    await expect(table).toContainText("Зафикс.");
    await expect(table.getByText("Проданная бумага")).toHaveCount(0);
    const geometry = await table.evaluate((element) => {
      const parent = element.parentElement;
      if (!parent) throw new Error("No table parent");
      parent.style.maxWidth = "720px";
      return {
        client: parent.clientWidth,
        scroll: parent.scrollWidth,
        overflow: [...element.querySelectorAll("td")]
          .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
          .map((cell) => cell.textContent),
      };
    });
    expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1);
    expect(geometry.overflow).toEqual([]);
    await table.screenshot({ path: info.outputPath(`position-split-${zoom}.png`) });
    await table.getByRole("link", { name: "Учебная акция", exact: true }).click();
    const result = page.getByRole("region", { name: "Разложение результата" });
    await expect(result.getByLabel("Подробнее: Зафиксировано", { exact: true })).toBeVisible();
    await expect(result.getByLabel("Подробнее: В цене", { exact: true })).toBeVisible();
    await result.screenshot({ path: info.outputPath(`position-card-${zoom}.png`) });
    await page.getByRole("button", { name: "К доходности", exact: true }).click();
    await expect(page.getByRole("checkbox", { name: "Разложение результата" })).toBeChecked();
    await page.getByRole("combobox", { name: "Позиции", exact: true }).selectOption("sold");
    await expect(table.getByText("Проданная бумага")).toBeVisible();
    await expect(table.getByText("Учебная акция", { exact: true })).toHaveCount(0);
  }
});

async function install(page: Page, extendedHistory = false) {
  const calls: string[] = [];
  const state = { error: false, unavailable: false };
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      if (await fulfillMonthPlate(route)) return;
      const request = route.request();
      const url = new URL(request.url());
      calls.push(`${request.method()} ${url.pathname}`);
      expect(request.method()).toBe("GET");
      const scope = url.searchParams.get("scope") ?? "source:SYNTH-A";
      const period = {
        start: url.searchParams.get("start") ?? may.start,
        end: url.searchParams.get("end") ?? may.end,
      };
      if (url.pathname === "/api/returns/context")
        await route.fulfill({ json: extendedHistory ? longHistoryContext : contextFixture });
      else if (url.pathname === "/api/returns/basket")
        await route.fulfill({
          json: basketFixture(period, url.searchParams.get("categories") ?? undefined),
        });
      else if (url.pathname === "/api/returns/overview") {
        const body = extendedHistory
          ? longHistoryOverview(scope, period)
          : overviewFixture(scope, period);
        if (!scope.startsWith("source:")) {
          body.instruments = [];
          body.instrument_reason_codes = ["accepted_instrument_breakdown_unavailable"];
          body.selected.pnl = {
            ...body.selected.pnl,
            value: null,
            reason_codes: ["not_computable_external_flows_incomplete"],
          };
          body.selected.rate = {
            ...body.selected.rate,
            value: null,
            reason_codes: ["not_computable_external_flows_incomplete"],
          };
          body.selected.coupons = {
            ...body.selected.coupons,
            value: null,
            reason_codes: ["accepted_income_breakdown_unavailable"],
          };
          body.selected.dividends = {
            ...body.selected.dividends,
            value: null,
            reason_codes: ["accepted_income_breakdown_unavailable"],
          };
        }
        if (state.unavailable) {
          body.selected.pnl.value = null;
          body.selected.pnl.reason_codes = ["missing_endpoint"];
        }
        await route.fulfill({
          status: state.error ? 503 : 200,
          json: state.error ? {} : body,
        });
      } else if (url.pathname === "/api/returns/instrument")
        await route.fulfill({
          json: detailFixture(scope, period, url.searchParams.get("isin") ?? undefined),
        });
      else if (url.pathname === "/api/returns/overall")
        await route.fulfill({ json: overallFixture() });
      else if (!(await fulfillReturnsNeighbour(route)))
        await route.fulfill({ status: 404, json: {} });
    },
  );
  return { calls, state };
}

test("ui-v2 returns: URL, chart, both accounts, short tops, lazy sales and retry @viewport-owned", async ({
  page,
}) => {
  const { calls, state } = await install(page);
  await page.goto("/v2/returns?scope=source:SYNTH-A");
  await expect(page.getByRole("region", { name: "Результат периода" })).toBeVisible();
  await expect(page).toHaveURL(/start=2030-04-30&end=2030-05-31/);
  await expect(page.getByRole("link", { name: "Доходность", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(calls.filter((c) => c.endsWith("/instrument"))).toHaveLength(0);
  const tops = page.getByRole("region", { name: "Лидеры и отстающие" });
  await expect(tops.locator("ol li")).toHaveCount(3);
  await expect(tops.locator('li strong[data-tone="positive"]')).toHaveCount(2);
  await expect(tops.locator('li strong[data-tone="negative"]')).toHaveCount(1);
  await expect(tops.locator("ol li").first()).toContainText("Северные технологии");
  await expect(tops.getByRole("button", { name: "%", exact: true })).toHaveCount(0);
  await page
    .getByRole("table", { name: "Бумаги за период" })
    .getByRole("button", { name: /Горизонт — проданная бумага/ })
    .click();
  await expect(page.getByText("Количество: 10 → 0")).toBeVisible();
  await page.getByText("Сделки и выплаты (1)", { exact: true }).click();
  await expect(page.getByText("Продажа", { exact: true })).toBeVisible();
  // React's development StrictMode may abort and repeat the first mounted GET.
  expect(calls.filter((c) => c.endsWith("/instrument")).length).toBeGreaterThanOrEqual(1);
  await page
    .getByRole("group", { name: "История результата в рублях" })
    .getByRole("button", { name: /апр.*2030/ })
    .click();
  await expect(page).toHaveURL(/start=2030-03-31&end=2030-04-30/);
  await expect(page.getByRole("region", { name: "Лидеры и отстающие" })).toContainText(
    "31.03.2030 — 30.04.2030",
  );
  await page
    .getByRole("group", { name: "Счета" })
    .getByRole("button", { name: "Учебный счёт Б", exact: true })
    .click();
  await expect(page.getByRole("region", { name: "Результат периода" })).toContainText("−1 750 ₽");
  await page.reload();
  await expect(
    page
      .getByRole("group", { name: "Счета" })
      .getByRole("button", { name: "Учебный счёт Б", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.goBack();
  await expect(
    page
      .getByRole("group", { name: "Счета" })
      .getByRole("button", { name: "Учебный счёт А", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page).toHaveURL(new RegExp(`start=${april.start}&end=${april.end}`));
  state.error = true;
  await page.getByRole("button", { name: "Обновить" }).click();
  await expect(page.getByRole("alert")).toContainText("Не удалось загрузить");
  await expect(page.getByRole("region", { name: "Результат периода" })).toHaveCount(0);
  state.error = false;
  await page.getByRole("button", { name: "Повторить" }).click();
  await expect(page.getByRole("region", { name: "Результат периода" })).toBeVisible();
  // Intentional retired URL: assert compatibility redirect, not ordinary navigation.
  await page.goto(
    "/v2/capital/monthly-returns?source_account=SYNTH-B&bond_period=2030-04-01#bond-slice",
  );
  await expect(page).toHaveURL(
    /\/v2\/returns\/account\?.*scope=source%3ASYNTH-B.*start=2030-03-31.*#returns-instruments/,
  );
  await expect(page.getByRole("region", { name: "Результат периода" })).toBeVisible();
});

test("ui-v2 returns: absent legacy period remains history through Reload and Back @viewport-owned", async ({
  page,
}) => {
  await install(page);
  await page.goto("/v2/returns?scope=source:SYNTH-A");
  await expect(page.getByRole("region", { name: "Результат периода" })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`start=${may.start}&end=${may.end}`));
  // Intentional retired URL: assert compatibility redirect, not ordinary navigation.
  await page.goto(
    "/v2/capital/monthly-returns?source_account=SYNTH-A&bond_isin=RU000A000002#bond-slice",
  );
  const expectHistory = async () => {
    await expect(page).toHaveURL(
      /isin=RU000A000002.*start=2030-03-31&end=2030-05-31#returns-instruments/,
    );
    await expect(page.getByText("Количество: 10 → 0")).toBeVisible();
    await expect(page).toHaveURL(/start=2030-03-31&end=2030-05-31/);
    await expect(page.getByRole("region", { name: "Результат периода" })).toContainText(
      "31.03.2030 — 31.05.2030",
    );
    await expect(page.getByRole("region", { name: "Лидеры и отстающие" })).toContainText(
      "31.03.2030 — 31.05.2030",
    );
  };
  await expectHistory();
  await page.reload();
  await expectHistory();
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`start=${may.start}&end=${may.end}`));
});

test("ui-v2 returns: 24-month selection stays visible and synchronized through load Back Reload @viewport-owned", async ({
  page,
}, testInfo) => {
  await install(page, true);
  await page.goto("/v2/returns?scope=source:SYNTH-A");
  await expect(page.getByRole("region", { name: "Результат периода" })).toBeVisible();
  const history = page.getByRole("region", { name: "Результат по месяцам" });
  const chart = history.getByRole("group", { name: "История результата в рублях" });
  await expect(chart.getByRole("button")).toHaveCount(12);
  await history.getByRole("button", { name: "Более ранние месяцы" }).click();
  let release = () => {};
  let requested = false;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    (url) =>
      url.pathname === "/api/returns/overview" && url.searchParams.get("end") === "2029-01-31",
    async (route) => {
      requested = true;
      await gate;
      await route.fallback();
    },
  );
  await chart.getByRole("button", { name: /янв.*2029/ }).click();
  await expect.poll(() => requested).toBe(true);
  await expect(page.getByRole("region", { name: "Результат периода" })).toHaveCount(0);
  release();
  const expectSelection = async (
    index: number,
    name: RegExp,
    pnl: string,
    loss: string,
    coupons: string,
    dividends: string,
  ) => {
    const p = longHistoryPeriods[index];
    const dates = `${p.start.split("-").reverse().join(".")} — ${p.end.split("-").reverse().join(".")}`;
    await expect(page).toHaveURL(new RegExp(`start=${p.start}&end=${p.end}`));
    const card = page.getByRole("region", { name: "Результат периода" });
    await expect(card).toContainText(dates);
    await expect(card).toContainText(pnl);
    await expect(page.getByRole("region", { name: "Полученные купоны" })).toContainText(coupons);
    await expect(page.getByRole("region", { name: "Полученные дивиденды" })).toContainText(
      dividends,
    );
    await expect(chart.getByRole("button", { name })).toHaveAttribute("aria-pressed", "true");
    await expect(chart.getByRole("button")).toHaveCount(12);
    await expect(history.getByRole("table")).toBeVisible();
    await expect(history.getByRole("row", { name })).toContainText(pnl);
    const instruments = page.getByRole("region", { name: "По инструментам" });
    await expect(instruments.getByRole("row").filter({ hasText: "RU000A000001" })).toContainText(
      pnl,
    );
    const tops = page.getByRole("region", { name: "Лидеры и отстающие" });
    await expect(tops).toContainText(dates);
    await expect(tops.locator("ol").first()).toContainText(pnl);
    await expect(tops.locator("ol")).toContainText(loss);
  };
  await expectSelection(0, /янв.*2029/, "+100 ₽", "−50 ₽", "1 ₽", "2 ₽");
  await history.getByRole("button", { name: "Более поздние месяцы" }).click();
  await chart.getByRole("button", { name: /янв.*2030/ }).click();
  await expectSelection(12, /янв.*2030/, "+1 300 ₽", "−650 ₽", "13 ₽", "26 ₽");
  await page.goBack();
  await expectSelection(0, /янв.*2029/, "+100 ₽", "−50 ₽", "1 ₽", "2 ₽");
  await page.reload();
  await expectSelection(0, /янв.*2029/, "+100 ₽", "−50 ₽", "1 ₽", "2 ₽");
  await history
    .getByRole("table")
    .getByRole("button", { name: /февр.*2029/ })
    .click();
  await expectSelection(1, /февр.*2029/, "+200 ₽", "−100 ₽", "2 ₽", "4 ₽");
  await page.goBack();
  await expectSelection(0, /янв.*2029/, "+100 ₽", "−50 ₽", "1 ₽", "2 ₽");
  const directory = path.resolve(".visual-audit", testInfo.project.name);
  fs.mkdirSync(directory, { recursive: true });
  await page.screenshot({
    path: path.join(directory, "returns-history-24-months.png"),
    fullPage: true,
  });
});

test("ui-v2 returns: nine desktop size and zoom screenshots @viewport-owned", async ({
  browser,
}, testInfo) => {
  test.setTimeout(120000);
  const directory = path.resolve(".visual-audit", testInfo.project.name);
  fs.mkdirSync(directory, { recursive: true });
  for (const width of [1280, 1440, 1920]) {
    for (const zoom of [1, 1.25, 1.5]) {
      // Browser zoom equivalent: CSS viewport shrinks, device pixels scale up.
      // Unlike CSS zoom or pinch zoom, media queries see the scaled viewport.
      const context = await browser.newContext({
        viewport: { width: Math.round(width / zoom), height: Math.round(1000 / zoom) },
        deviceScaleFactor: zoom,
        locale: "ru-RU",
        reducedMotion: "reduce",
      });
      const page = await context.newPage();
      const { state } = await install(page);
      await page.goto("/v2/returns?scope=source:SYNTH-A");
      await expect(page.getByRole("heading", { name: "По инструментам" })).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      const overflow = await page
        .locator("main")
        .evaluate(
          (main) =>
            [...main.querySelectorAll("td, th, section, input, select")].filter(
              (e) => e.scrollWidth > e.clientWidth + 1,
            ).length,
        );
      expect(overflow).toBe(0);
      await expect(page.locator("main")).not.toContainText(
        /financial_authority|source_reference|manifest_digest/,
      );
      await page.screenshot({
        path: path.join(directory, `returns-${width}-${zoom * 100}.png`),
        fullPage: true,
        animations: "disabled",
      });
      if (width === 1280 && zoom === 1.5) {
        state.unavailable = true;
        await page.getByRole("button", { name: "Обновить" }).click();
        await page.getByText("Подробнее о данных", { exact: true }).click();
        const info = page.getByLabel("Подробнее: Результат периода", { exact: true });
        await info.focus();
        await page.keyboard.press("Enter");
        const explanation = page
          .getByText("Не хватает стоимости на границе периода.", { exact: true })
          .first();
        await expect(explanation).toBeVisible();
        await expect(page.getByRole("region", { name: "Результат периода" })).toContainText(
          "+1,7%",
        );
        await page.screenshot({ path: path.join(directory, "returns-null-info-1280-150.png") });
        const box = await explanation.boundingBox();
        const main = await page.locator("main").boundingBox();
        expect(box).not.toBeNull();
        expect(box?.x).toBeGreaterThanOrEqual(main?.x ?? 0);
        expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(Math.round(width / zoom));
      }
      await context.close();
    }
  }
});

test("returns accepted basis and category keyboard controls @viewport-owned", async ({
  page,
}, testInfo) => {
  const { calls } = await install(page);
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/v2/returns/account?scope=portfolio&diagnostics=performance");
    await expect(
      page
        .getByRole("group", { name: "Счета" })
        .getByRole("button", { name: "Общий портфель", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("combobox", { name: "Представление" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Обзор", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Моя доходность" })).toHaveCount(0);
    await page
      .getByText("Дополнительная диагностика портфеля за выбранный период", { exact: true })
      .focus();
    await page.keyboard.press("Enter");
    const checkbox = page.getByRole("checkbox", { name: "ИИС", exact: true });
    await expect(checkbox).toBeChecked();
    await checkbox.focus();
    await expect(checkbox).toBeFocused();
    await expect(checkbox).toHaveCSS("appearance", "none");
    await expect(checkbox).toHaveCSS("outline-style", "solid");
    await page.screenshot({ path: testInfo.outputPath(`returns-accepted-focus-${width}.png`) });
    await page.keyboard.press("Space");
    await expect(checkbox).not.toBeChecked();
    await expect(page).toHaveURL(/categories=brokerage%2Cdeposits%2Cgold/);
    await page.goBack();
    await expect(checkbox).toBeChecked();
    await page.goto("/v2/returns/account?scope=source:SYNTH-A");
    await expect(
      page
        .getByRole("group", { name: "Счета" })
        .getByRole("button", { name: "Учебный счёт А", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("region", { name: "Результат периода" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({ path: testInfo.outputPath(`returns-statements-${width}.png`) });
  }
  expect(calls.every((call) => call.startsWith("GET "))).toBe(true);
});

test("ui-v2 returns leaders: long names and exact amounts stay aligned @viewport-owned", async ({
  page,
}, testInfo) => {
  const body = overallFixture();
  const original = body.instruments[0];
  const cases = [
    [
      "RU000A001001",
      "Облигация Северный учебный инфраструктурный проект выпуск двадцать один",
      "95123456",
    ],
    ["RU000A001002", "Акции Учебные технологии и длинное название предприятия", "8500000"],
    ["RU000A001003", "Фонд Международный учебный диверсифицированный портфель", "1234567"],
    ["RU000A001004", "Облигация Учебные транспортные системы серия двадцать пять", "-87654321"],
    ["RU000A001005", "Акции Экспериментальная промышленная корпорация", "-7654321"],
    ["RU000A001006", "Фонд Учебный рынок", "-98765"],
  ];
  body.gold.targets = [];
  body.gold.snapshots = [];
  body.instruments = cases.map(([isin, name, value]) => ({
    ...original,
    isin,
    name,
    accounts: [{ ...original.accounts[0], pnl: { ...original.accounts[0].pnl, value } }],
  }));
  const calls: string[] = [];
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      if (await fulfillMonthPlate(route)) return;
      const request = route.request();
      calls.push(`${request.method()} ${new URL(request.url()).pathname}`);
      expect(request.method()).toBe("GET");
      if (await fulfillReturnsNeighbour(route)) return;
      expect(new URL(request.url()).pathname).toBe("/api/returns/overall");
      await route.fulfill({ json: body });
    },
  );
  for (const width of [1440, 1100]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/v2/returns");
    const leaders = page.getByRole("region", { name: "Вклад инструментов" });
    await expect(leaders.locator("ol")).toHaveCount(1);
    await expect(leaders.locator("li")).toHaveCount(6);
    const zeroPositions = await leaders.locator("li > span").evaluateAll((tracks) =>
      tracks.map((track) => {
        const bounds = track.getBoundingClientRect();
        return bounds.x + bounds.width / 2;
      }),
    );
    expect(Math.max(...zeroPositions) - Math.min(...zeroPositions)).toBeLessThan(1);
    const problems = await leaders.locator("li").evaluateAll((items) =>
      items.flatMap((item) => {
        const link = item.querySelector("a");
        const amount = item.querySelector("strong");
        const rank = item.querySelector("span");
        if (!link || !amount || !rank) return ["missing row column"];
        const nameBox = link.getBoundingClientRect();
        const amountBox = amount.getBoundingClientRect();
        const rowBox = item.getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(amount);
        return [
          ...(range.getClientRects().length !== 1 ? ["amount wrapped"] : []),
          ...(nameBox.right > amountBox.left - 5 ? ["name overlaps amount"] : []),
          ...(Math.abs(amountBox.right - rowBox.right) > 1 ? ["amount not right aligned"] : []),
          ...(amountBox.right > rowBox.right + 1 ? ["row overflow"] : []),
        ];
      }),
    );
    expect(problems).toEqual([]);
    const firstLink = leaders.getByRole("link").first();
    await firstLink.focus();
    await expect(firstLink).toBeFocused();
    await expect(firstLink).toHaveAttribute("href", /\/v2\/returns\/instrument\/RU000A001001/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await leaders.screenshot({ path: testInfo.outputPath(`returns-leaders-${width}.png`) });
  }
  // A single supported side uses the entire card, without an empty second block.
  body.instruments = body.instruments.slice(0, 3);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/v2/returns");
  const single = page.getByRole("region", { name: "Вклад инструментов" });
  await expect(single.locator("ol")).toHaveCount(1);
  await expect(single.locator("li")).toHaveCount(3);
  await expect(single.getByText("Наибольший убыток", { exact: true })).toHaveCount(0);
  const widths = await single.evaluate((element) => ({
    panel: element.getBoundingClientRect().width,
    list: element.querySelector("ol")?.getBoundingClientRect().width ?? 0,
  }));
  expect(widths.list).toBeGreaterThan(widths.panel * 0.9);
  await single.screenshot({ path: testInfo.outputPath("returns-leaders-single-1440.png") });
  expect(calls.length).toBeGreaterThanOrEqual(3);
  expect(
    calls.every((call) =>
      [
        "GET /api/returns/overall",
        "GET /api/returns/context",
        "GET /api/returns/overview",
      ].includes(call),
    ),
  ).toBe(true);
});

for (const retired of ["performance", "monthly-returns", "monthly-result", "statement-return"]) {
  test(`retired ${retired}: Returns navigation @viewport-owned`, async ({ page }) => {
    await page.route(
      (url) => url.pathname.startsWith("/api/"),
      async (route) => {
        if (await fulfillMonthPlate(route)) return;
        expect(route.request().method()).toBe("GET");
        if (await fulfillReturnsNeighbour(route)) return;
        expect(new URL(route.request().url()).pathname).toBe("/api/returns/overall");
        await route.fulfill({ json: overallFixture() });
      },
    );
    await page.goto(`/v2/capital/${retired}`);
    await expect(page).toHaveURL(/\/v2\/returns$/);
    const nav = page.getByRole("navigation", { name: "Основная навигация" });
    const active = nav.getByRole("link", { name: "Доходность", exact: true });
    await expect(active).toHaveAttribute("aria-current", "page");
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
    await expect(page.getByRole("link", { name: "История и результаты" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Доход и цели", exact: true })).toHaveCount(0);
  });
}

test("ui-v2 instrument return restores table scroll and screen titles @viewport-owned", async ({
  page,
}) => {
  const body = overallFixture();
  await page.setViewportSize({ width: 1280, height: 700 });
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      if (await fulfillMonthPlate(route)) return;
      const url = new URL(route.request().url());
      expect(route.request().method()).toBe("GET");
      if (url.pathname === "/api/returns/overall") await route.fulfill({ json: body });
      else if (url.pathname === "/api/returns/instrument-card")
        await route.fulfill({
          json: instrumentCardFixture(url.searchParams.get("isin") ?? undefined),
        });
      else if (!(await fulfillReturnsNeighbour(route)))
        await route.fulfill({ status: 404, json: {} });
    },
  );
  await page.goto("/v2/returns");
  await expect(page).toHaveTitle("Доходность — Finance");
  const table = page.getByRole("table", { name: "Все бумаги" });
  const link = table.getByRole("link").first();
  await link.scrollIntoViewIfNeeded();
  const position = await page.evaluate(() => window.scrollY);
  expect(position).toBeGreaterThan(100);
  await link.click();
  await expect(page).toHaveTitle("Инструмент — Finance");
  await expect(page.getByRole("table", { name: "Инструмент по счетам" })).toBeVisible();
  await expect(page.locator("table:not([aria-label]):not(:has(caption))")).toHaveCount(0);
  await expect(page.locator("thead th:not([scope=col])")).toHaveCount(0);
  await page.getByRole("button", { name: /К доходности/ }).click();
  await expect(table).toBeVisible();
  await expect(page).toHaveTitle("Доходность — Finance");
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeCloseTo(position, 0);
});

test("Returns sidebar parent and AA contrast @viewport-owned", async ({ page }) => {
  await install(page);
  for (const destination of [
    "/v2/returns/account?scope=source:SYNTH-A",
    "/v2/returns/instrument/RU000A000001",
  ]) {
    await page.goto(destination);
    const nav = page.getByRole("navigation", { name: "Основная навигация" });
    const active = nav.getByRole("link", { name: "Доходность", exact: true });
    await expect(active).toHaveAttribute("aria-current", "page");
    // The route can expose aria-current before its stylesheet has been applied.
    // Wait for rendered colors, retaining the actual AA contrast assertion.
    const readColors = () =>
      active.evaluate((element) => {
        const style = getComputedStyle(element);
        const luminance = (value: string) => {
          const channels = (value.match(/\d+(?:\.\d+)?/g) ?? [])
            .slice(0, 3)
            .map(Number)
            .map((v) => {
              const channel = v / 255;
              return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
            });
          return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
        };
        const text = luminance(style.color);
        const background = luminance(style.backgroundColor);
        const sibling = element.parentElement?.querySelector('a:not([aria-current="page"])');
        return {
          contrast: (Math.max(text, background) + 0.05) / (Math.min(text, background) + 0.05),
          background: style.backgroundColor,
          inactiveBackground: sibling ? getComputedStyle(sibling).backgroundColor : null,
          marker: style.boxShadow,
        };
      });
    await expect.poll(async () => (await readColors()).contrast).toBeGreaterThanOrEqual(4.5);
    const colors = await readColors();
    expect(colors.background).not.toBe(colors.inactiveBackground);
    expect(colors.marker).not.toBe("none");
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
  }
});

test("ui-v2 returns instrument results: separate accounts, assumptions and narrow layout @viewport-owned", async ({
  page,
}, testInfo) => {
  const overall = overallFixture();
  const card = instrumentCardFixture();
  const first = overall.instruments[0].accounts[0];
  first.pnl.value = "0";
  first.rate = { ...first.rate, value: null, reason_codes: ["missing_endpoint"] };
  const detail = card.accounts[0].detail;
  if (!detail) throw new Error("Synthetic instrument detail missing");
  detail.analysis.assumptions = ["face_value_assumed"];
  if (!card.accounts[0].clean) throw new Error("Synthetic clean detail missing");
  card.accounts[0].clean.pnl.assumptions = ["face_value_assumed"];
  const calls: string[] = [];
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      if (await fulfillMonthPlate(route)) return;
      const url = new URL(route.request().url());
      expect(route.request().method()).toBe("GET");
      calls.push(url.pathname);
      const scope = url.searchParams.get("scope") ?? "source:SYNTH-A";
      const period = {
        start: url.searchParams.get("start") ?? may.start,
        end: url.searchParams.get("end") ?? may.end,
      };
      const body =
        url.pathname === "/api/returns/overall"
          ? overall
          : url.pathname === "/api/returns/instrument-card"
            ? card
            : url.pathname === "/api/returns/context"
              ? contextFixture
              : url.pathname === "/api/returns/overview"
                ? overviewFixture(scope, period)
                : null;
      await route.fulfill({ status: body ? 200 : 404, json: body ?? {} });
    },
  );
  let cardReads = 0;
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/v2/returns");
    const instruments = page.getByRole("region", { name: /^Все бумаги/ });
    const rows = instruments.getByRole("row").filter({ hasText: "Учебная акция" });
    const a = instruments.getByRole("row", { name: /^Учебный счёт А/ });
    const b = instruments.getByRole("row", { name: /^Учебный счёт Б/ });
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText("неполный");
    await expect(a).toContainText("0 ₽");
    await expect(a.getByRole("cell").nth(1)).toHaveText("—");
    await expect(b).toContainText("−4 ₽");
    await expect(rows.locator("details")).toHaveCount(0);
    expect(calls.filter((call) => call.endsWith("instrument-card"))).toHaveLength(cardReads);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await instruments.screenshot({
      path: testInfo.outputPath(`instrument-results-overview-${width}.png`),
    });
    await rows.getByRole("link", { name: "Учебная акция", exact: true }).click();
    const accounts = page.getByRole("region", { name: "Позиции и результат по счетам" });
    await expect(accounts).toContainText("+12 ₽");
    cardReads = calls.filter((call) => call.endsWith("instrument-card")).length;
    await expect(accounts).toContainText("−4 ₽");
    await expect(accounts).toContainText("30.04.2030 — 31.05.2030");
    await expect(accounts).toContainText("31.03.2030 — 30.04.2030");
    await accounts.getByText("Подробнее о расчёте по счетам", { exact: true }).click();
    const resultInfo = accounts.getByLabel("Подробнее: Результат инструмента").first();
    await resultInfo.click();
    await expect(resultInfo.locator("..")).toContainText("Номинал сделки принят с допущением");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await accounts.screenshot({
      path: testInfo.outputPath(`instrument-results-card-${width}.png`),
    });
    await page.getByRole("button", { name: "К доходности", exact: true }).click();
    await expect(instruments).toBeVisible();
    await page.goto("/v2/returns/account?scope=source:SYNTH-A");
    const missing = page.getByRole("row").filter({ hasText: "Учебная облигация" });
    await expect(missing).toContainText("—");
    await expect(missing.locator("details")).toHaveCount(0);
    await page.getByText("Подробнее о бумагах", { exact: true }).click();
    await expect(
      page.getByText("Не хватает стоимости на границе периода.", { exact: true }),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
  }
});

test("ui-v2 Returns table fits 720px with wide fonts, separate accounts and compact rows @viewport-owned", async ({
  page,
}, info) => {
  const body = overallFixture();
  const template = body.instruments[0];
  body.instruments = Array.from({ length: 12 }, (_, index) => ({
    ...template,
    isin: `RU000A00${String(index).padStart(4, "0")}`,
    name: `Учебная инфраструктурная бумага с длинным названием ${index}`,
    accounts: template.accounts.map((account) => ({
      ...account,
      native_period: true,
      pnl: {
        ...account.pnl,
        value: String(12345678900 - index),
        reason_codes: index === 0 ? ["clean_partial_result"] : [],
      },
      coupons: { ...account.coupons, value: "1234567890" },
      dividends: { ...account.dividends, value: "2345678901" },
    })),
  }));
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      if (await fulfillMonthPlate(route)) return;
      expect(route.request().method()).toBe("GET");
      await route.fulfill({ json: body });
    },
  );
  for (const width of [1024, 1280, 1440, 1920])
    for (const zoom of [1, 1.25]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/v2/returns?show=all&sort=pnl-desc");
      await page.evaluate((scale) => {
        document.documentElement.style.zoom = String(scale);
      }, zoom);
      await page.addStyleTag({ content: ":root { --f-num: Arial; --f-ui: Arial; }" });
      const table = page.getByRole("table", { name: "Все бумаги", exact: true });
      await expect(table.getByRole("row")).toHaveCount(37);
      const geometry = await table.evaluate((element) => {
        const parent = element.parentElement;
        if (!parent) throw new Error("Missing table container");
        parent.style.maxWidth = "720px";
        const rows = [...element.querySelectorAll("tbody tr")];
        return {
          table: element.getBoundingClientRect().width,
          client: parent.clientWidth,
          scroll: parent.scrollWidth,
          rowHeights: rows.map(
            (row) =>
              row.getBoundingClientRect().height / Number(document.documentElement.style.zoom),
          ),
          overlaps: rows.flatMap((row) =>
            [...row.querySelectorAll("td")]
              .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
              .map((cell) => cell.textContent),
          ),
        };
      });
      expect(geometry.table / zoom).toBeLessThanOrEqual(720.5);
      expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1);
      expect(Math.max(...geometry.rowHeights)).toBeLessThanOrEqual(48);
      expect(geometry.overlaps).toEqual([]);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      await table.screenshot({ path: info.outputPath(`returns-table-${width}-${zoom}.png`) });
    }
});

test("ui-v2 instrument tables fit 720px and keep long purchase histories collapsed @viewport-owned", async ({
  page,
}, info) => {
  const card = instrumentCardFixture();
  for (const account of card.accounts)
    if (account.clean) {
      account.clean.simple_return = {
        value: "0.1025",
        status: "supported",
        reason_codes: [],
        assumptions: [],
        method: "simple_return",
        annualized: false,
        invested_kopecks: "100000",
        start_date: "2029-01-01",
        end_date: "2030-05-31",
        holding_days: 515,
        weighted_holding_days: "515",
      };
    }
  if (card.accounts[0].clean) card.accounts[0].clean.pnl.status = "partial";
  card.summary.pnl.reason_codes = ["clean_partial_result"];
  for (const account of card.accounts)
    account.purchases = Array.from({ length: 12 }, (_, index) => ({
      id: `synthetic-${account.scope}-${index}`,
      date: "2030-05-01",
      settlement_date: "2030-05-02",
      quantity: "10",
      remaining_quantity: "0",
      cost_kopecks: "12345678901",
      sale_proceeds_kopecks: "12456789012",
      value_kopecks: "0",
      price_result_kopecks: "111111111",
      return_fraction: "0.009",
      status: "supported",
      reason_codes: [],
    }));
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      if (await fulfillMonthPlate(route)) return;
      expect(route.request().method()).toBe("GET");
      expect(new URL(route.request().url()).pathname).toBe("/api/returns/instrument-card");
      await route.fulfill({ json: card });
    },
  );
  for (const width of [1024, 1280, 1440, 1920])
    for (const zoom of [1, 1.25]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/v2/returns/instrument/RU000A000002");
      await page.evaluate((scale) => {
        document.documentElement.style.zoom = String(scale);
      }, zoom);
      await page.addStyleTag({ content: ":root { --f-num: Arial; --f-ui: Arial; }" });
      const purchases = page.getByRole("region", { name: "Результат сохранённых покупок" });
      await expect(purchases.getByRole("table")).toHaveCount(2);
      for (const table of await purchases.getByRole("table").all())
        await expect(table.getByRole("row")).toHaveCount(6);
      const accountTable = page
        .getByRole("region", { name: "Позиции и результат по счетам" })
        .getByRole("table");
      const accountBox = await accountTable.boundingBox();
      if (width === 1440 && zoom === 1) {
        expect(accountBox).not.toBeNull();
        expect((accountBox?.y ?? 900) + (accountBox?.height ?? 0)).toBeLessThanOrEqual(900);
        await expect(accountTable).toContainText("+10,3%");
      }
      const tables = [
        page.getByRole("region", { name: "Позиции и результат по счетам" }).getByRole("table"),
        ...(await purchases.getByRole("table").all()),
      ];
      for (const table of tables) {
        const geometry = await table.evaluate((element) => {
          const parent = element.parentElement;
          if (!parent) throw new Error("Missing table container");
          parent.style.maxWidth = "720px";
          return {
            client: parent.clientWidth,
            scroll: parent.scrollWidth,
            cells: [...element.querySelectorAll("td, th")]
              .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
              .map((cell) => cell.textContent),
          };
        });
        expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1);
        expect(geometry.cells).toEqual([]);
      }
      if (width === 1440 && zoom === 1)
        expect(
          await page.locator("main").evaluate((element) => element.getBoundingClientRect().height),
        ).toBeLessThanOrEqual(2700);
      await page.screenshot({
        path: info.outputPath(`instrument-tables-${width}-${zoom}.png`),
        fullPage: true,
      });
    }
});

test("canonical security name and gold FIFO parts remain visible with exact tooltips", async ({
  page,
}, info) => {
  const body = overallFixture();
  body.instruments[0].name = "Long source label (SYN)";
  body.instruments[0].short_name = "Короткая бумага";
  const metric = (value: string | null) => ({
    ...body.gold.snapshots[0].market_value,
    value,
    method: "clean_gold_fifo",
    estimate: true,
  });
  body.gold.snapshots[0].market_value = metric("80000");
  body.gold.snapshots[0].cost_basis = metric("60000");
  body.gold.histories = [
    {
      account_id: 10,
      instrument_id: 20,
      label: "Учебное золото",
      revision: 1,
      amount_basis: "actual",
      tax_treatment: "not_provided",
      source_kind: "owner_manual_gold_history",
      authority: "owner_attestation",
      currentness: "current",
      period: may,
      valuation_date: may.end,
      valuation_status: "closed",
      total_result: metric("30000"),
      realized_result: metric("10000"),
      unrealized_result: metric("20000"),
      buy_amount: metric("100000"),
      sale_amount: metric("50000"),
      separate_fees: metric(null),
      reason_codes: [],
    },
  ];
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      if (await fulfillMonthPlate(route)) return;
      expect(route.request().method()).toBe("GET");
      await route.fulfill({ json: body });
    },
  );
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/v2/returns");
  await page.getByRole("searchbox", { name: "Поиск" }).fill("Короткая");
  await expect(page.getByRole("link", { name: "Короткая бумага", exact: true })).toBeVisible();
  await expect(page.getByText("Long source label (SYN)", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("table", { name: "Все бумаги", exact: true })).toContainText(
    body.instruments[0].isin,
  );
  const gold = page.getByRole("region", { name: "Золото", exact: true });
  await expect(gold.locator("dt").filter({ hasText: "Зафиксировано" })).toBeVisible();
  await expect(gold.locator("dt").filter({ hasText: "В цене" })).toBeVisible();
  await expect(gold.locator("dd[title]").nth(0)).toHaveText(/\+100\s*₽/);
  await expect(gold.locator("dd[title]").nth(1)).toHaveText(/\+200\s*₽/);
  await gold.screenshot({ path: info.outputPath("gold-fifo-parts.png") });
  await gold.getByLabel("Подробнее: Зафиксировано", { exact: true }).click();
  await expect(
    page.getByText(
      "Выручка продаж минус FIFO-стоимость проданных граммов. Комиссии и налоги исключены.",
      { exact: true },
    ),
  ).toBeVisible();
});
