import fs from "node:fs";
import path from "node:path";
import { expect, type Page, test } from "@playwright/test";
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
import { overallFixture } from "../src/ui-v2/returns/overallFixtures";

async function install(page: Page, extendedHistory = false) {
  const calls: string[] = [];
  const state = { error: false, unavailable: false };
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
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
      else await route.fulfill({ status: 404, json: {} });
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
  await expect(tops.locator("ol").nth(0).locator("li")).toHaveCount(2);
  await expect(tops.locator("ol").nth(1).locator("li")).toHaveCount(1);
  await tops.getByRole("button", { name: "%", exact: true }).click();
  await expect(tops.locator("ol").first().locator("li").first()).toContainText("Горизонт");
  await page.getByRole("button", { name: /Горизонт — проданная бумага/ }).click();
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
  await page.getByRole("combobox", { name: "Счёт" }).selectOption("source:SYNTH-B");
  await expect(page.getByRole("region", { name: "Результат периода" })).toContainText("−1 750,25");
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Счёт" })).toHaveValue("source:SYNTH-B");
  await page.goBack();
  await expect(page.getByRole("combobox", { name: "Счёт" })).toHaveValue("source:SYNTH-A");
  await expect(page.getByRole("combobox", { name: "Период" })).toHaveValue(
    `${april.start}/${april.end}`,
  );
  state.error = true;
  await page.getByRole("button", { name: "Обновить" }).click();
  await expect(page.getByRole("alert")).toContainText("Не удалось загрузить");
  await expect(page.getByRole("region", { name: "Результат периода" })).toHaveCount(0);
  state.error = false;
  await page.getByRole("button", { name: "Повторить" }).click();
  await expect(page.getByRole("region", { name: "Результат периода" })).toBeVisible();
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
  await expect(page.getByRole("combobox", { name: "Период" })).toHaveValue(
    `${may.start}/${may.end}`,
  );
  await page.goto(
    "/v2/capital/monthly-returns?source_account=SYNTH-A&bond_isin=RU000A000002#bond-slice",
  );
  const expectHistory = async () => {
    await expect(page).toHaveURL(
      /isin=RU000A000002.*start=2030-03-31&end=2030-05-31#returns-instruments/,
    );
    await expect(page.getByText("Количество: 10 → 0")).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Период" })).toHaveValue(
      "2030-03-31/2030-05-31",
    );
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
  await expect(page.getByRole("combobox", { name: "Период" })).toHaveValue(
    `${may.start}/${may.end}`,
  );
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
    await expect(page.getByRole("combobox", { name: "Период" })).toHaveValue(`${p.start}/${p.end}`);
    const card = page.getByRole("region", { name: "Результат периода" });
    await expect(card).toContainText(dates);
    await expect(card).toContainText(pnl);
    await expect(page.getByRole("region", { name: "Полученные купоны" })).toContainText(coupons);
    await expect(page.getByRole("region", { name: "Полученные дивиденды" })).toContainText(
      dividends,
    );
    await expect(chart.getByRole("button", { name })).toHaveAttribute("aria-pressed", "true");
    await expect(chart.getByRole("button")).toHaveCount(12);
    if (!(await history.getByRole("table").isVisible()))
      await history.getByText("Месяцы таблицей", { exact: true }).click();
    await expect(history.getByRole("row", { name })).toContainText(pnl);
    const instruments = page.getByRole("region", { name: "По инструментам" });
    await expect(instruments.getByRole("row").filter({ hasText: "RU000A000001" })).toContainText(
      pnl,
    );
    const tops = page.getByRole("region", { name: "Лидеры и отстающие" });
    await expect(tops).toContainText(dates);
    await expect(tops.locator("ol").first()).toContainText(pnl);
    await expect(tops.locator("ol").last()).toContainText(loss);
  };
  await expectSelection(0, /янв.*2029/, "+100 ₽", "−50 ₽", "1 ₽", "2 ₽");
  await page
    .getByRole("combobox", { name: "Период" })
    .selectOption(`${longHistoryPeriods[12].start}/${longHistoryPeriods[12].end}`);
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
        const info = page.getByLabel("Подробнее: Результат периода", { exact: true });
        await info.focus();
        await page.keyboard.press("Enter");
        const explanation = info.locator("..").locator("div").first();
        await expect(explanation).toContainText("Не хватает стоимости на границе периода");
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
    await page.goto("/v2/returns/account?scope=portfolio");
    await expect(page.getByRole("combobox", { name: "Счёт" })).toHaveValue("portfolio");
    await expect(page.getByRole("combobox", { name: "Представление" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Открыть отчёты месяцев" })).toBeVisible();
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
    await expect(page.getByRole("combobox", { name: "Счёт" })).toHaveValue("source:SYNTH-A");
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
      const request = route.request();
      calls.push(`${request.method()} ${new URL(request.url()).pathname}`);
      expect(request.method()).toBe("GET");
      expect(new URL(request.url()).pathname).toBe("/api/returns/overall");
      await route.fulfill({ json: body });
    },
  );
  for (const width of [1440, 1100]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/v2/returns");
    const leaders = page.getByRole("region", { name: "Лидеры и отстающие" });
    await expect(leaders.locator("ol")).toHaveCount(2);
    await expect(leaders.locator("li")).toHaveCount(6);
    const groups = leaders.locator("h3");
    const positive = await groups.nth(0).boundingBox();
    const negative = await groups.nth(1).boundingBox();
    if (!positive || !negative) throw new Error("Missing leaders groups");
    if (width === 1440) {
      expect(Math.abs(positive.width - negative.width)).toBeLessThan(1);
      expect(Math.abs(positive.y - negative.y)).toBeLessThan(1);
      expect(negative.x).toBeGreaterThan(positive.x + positive.width);
    } else {
      expect(Math.abs(positive.x - negative.x)).toBeLessThan(1);
      expect(negative.y).toBeGreaterThan(positive.y + positive.height);
    }
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
  const single = page.getByRole("region", { name: "Лидеры и отстающие" });
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
  expect(calls.every((call) => call === "GET /api/returns/overall")).toBe(true);
});
