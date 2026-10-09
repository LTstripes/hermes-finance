import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { classReturnsFixture } from "../src/test/classReturnsFixture";

for (const width of [1366]) {
  for (const scenario of ["values", "evidence", "xirr-only"] as const) {
    test(`ui-v2 class returns ${scenario} keyboard and layout ${width}px @viewport-owned`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const start = "2031-05-31";
      const end = "2031-07-31";
      const presetStart = "2031-06-30";
      const reads: string[] = [];
      const presetReads: string[] = [];
      const unexpected: string[] = [];
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.route("**/api/**", async (route) => {
        const url = new URL(route.request().url());
        if (!url.pathname.startsWith("/api/")) {
          await route.continue();
          return;
        }
        if (url.pathname === "/api/months" && route.request().method() === "GET") {
          await route.fulfill({
            json: [start, presetStart, end].map((date, index) => ({
              id: index + 1,
              year: 2031,
              month: Number(date.slice(5, 7)),
              snapshot_date: date,
              status: "closed",
              source: "manual",
            })),
          });
          return;
        }
        if (
          url.pathname !== "/api/performance/class-returns" ||
          route.request().method() !== "GET"
        ) {
          unexpected.push(`${route.request().method()} ${url.pathname}`);
          await route.fulfill({ json: [] });
          return;
        }
        const assetClass = url.searchParams.get("asset_class") as string;
        const requestedStart = url.searchParams.get("start_date") as string;
        reads.push(assetClass);
        expect([start, presetStart]).toContain(requestedStart);
        if (requestedStart === presetStart) presetReads.push(assetClass);
        expect(url.searchParams.get("end_date")).toBe(end);
        const row = classReturnsFixture(assetClass, requestedStart, end);
        if (scenario === "values") {
          if (assetClass === "stock") row.xirr.value = row.twrr.value = "0";
          if (assetClass === "bond") row.xirr.value = row.twrr.value = "-2.75";
        } else if (scenario === "evidence" && assetClass !== "deposit") {
          const code =
            assetClass === "stock"
              ? "no_crossing_coverage_missing_or_ambiguous"
              : assetClass === "bond"
                ? "no_crossing_material_changed"
                : "not_computable_xirr_root_ambiguity";
          if (assetClass !== "gold") {
            row.eligibility_status = "unavailable";
            row.evidence_reason_codes = [code];
            row.coverage_state = assetClass === "bond" ? "invalidated" : "unknown";
            if (assetClass === "stock") row.coverage_provenance = [];
          }
          for (const kind of ["twrr", "xirr"] as const)
            Object.assign(row[kind], {
              availability: "not_computable",
              quality: "unavailable",
              value: null,
              reason_source: assetClass === "gold" ? "solver" : "evidence",
              reason_codes: [code],
            });
        } else if (scenario === "xirr-only" && assetClass === "stock") {
          Object.assign(row.twrr, {
            availability: "not_computable",
            quality: "unavailable",
            value: null,
            reason_source: "solver",
            reason_codes: ["not_computable_twrr_zero_or_negative_denominator"],
          });
        }
        await route.fulfill({ json: row });
      });
      await page.goto(
        `/v2/capital/performance?start=${start}&end=${end}&scope=portfolio&view=classes`,
      );
      const stock = page.getByTestId("class-return-stock");
      const bond = page.getByTestId("class-return-bond");
      const gold = page.getByTestId("class-return-gold");
      const deposit = page.getByTestId("class-return-deposit");
      await expect(deposit).toContainText("Расчёт не поддерживается");
      await expect(page.getByRole("button", { name: "1 мес." })).toBeEnabled();
      await expect(page.getByRole("button", { name: "3 мес." })).toBeDisabled();
      await expect(page.getByRole("button", { name: "12 мес." })).toBeDisabled();
      await expect(page.getByRole("button", { name: "С начала года" })).toBeDisabled();
      await expect(page.getByRole("button", { name: "Вся история" })).toBeEnabled();
      if (scenario === "values") {
        await expect(stock).toContainText("0,00%");
        await expect(bond).toContainText("−2,75%");
      } else if (scenario === "evidence") {
        await expect(stock).toContainText("Подтверждения неполны");
        await expect(bond).toContainText("Подтверждения изменены или отозваны");
        await expect(gold).toContainText("Ограничение расчётного метода");
      } else {
        await expect(stock).toContainText("+10,12%");
        await expect(stock).toContainText("Доходность не определена");
      }
      const classes = page.getByRole("button", { name: "По классам", exact: true });
      await classes.focus();
      await page.keyboard.press("Enter");
      await expect(classes).toBeFocused();
      await expect(classes).toHaveAttribute("aria-pressed", "true");
      const expand = stock.getByRole("button", { name: /Акции$/ });
      await expand.focus();
      await page.keyboard.press("Enter");
      await expect(expand).toBeFocused();
      await expect(expand).toHaveAttribute("aria-expanded", "true");
      await expect(page.getByText("Запрошенный период").first()).toBeVisible();
      await expect(page.getByRole("table")).toBeVisible();
      await expect(page.getByRole("rowheader")).toHaveCount(4);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      ).toBe(true);
      expect(
        await page
          .getByRole("table")
          .evaluate((table) => table.scrollWidth <= table.clientWidth + 1),
      ).toBe(true);
      // StrictMode may abort/restart the same read during the initial mount.
      expect([...new Set(reads)].sort()).toEqual(["bond", "deposit", "gold", "stock"]);
      expect(unexpected).toEqual([]);
      expect(errors).toEqual([]);
      const dir = path.resolve(".visual-audit", testInfo.project.name);
      fs.mkdirSync(dir, { recursive: true });
      await page.screenshot({
        path: path.join(dir, `ui-v2-class-returns-${scenario}-${width}.png`),
        fullPage: true,
      });
      await page.keyboard.press("Enter");
      await expect(expand).toHaveAttribute("aria-expanded", "false");
      await expect(expand).toBeFocused();
      if (scenario === "values") {
        const preset = page.getByRole("button", { name: "1 мес." });
        await preset.focus();
        await page.keyboard.press("Enter");
        await expect
          .poll(() => [...new Set(presetReads)].sort())
          .toEqual(["bond", "deposit", "gold", "stock"]);
        const params = new URL(page.url()).searchParams;
        expect(params.get("start")).toBe(presetStart);
        expect(params.get("end")).toBe(end);
        expect(params.get("view")).toBe("classes");
        expect(params.get("scope")).toBe("portfolio");
        expect(params.has("account_id")).toBe(false);
        await expect(page.getByTestId("performance-detail-period")).toContainText(
          "30.06.2031 — 31.07.2031",
        );
        expect(unexpected).toEqual([]);
        expect(errors).toEqual([]);
      }
    });
  }
}

for (const width of [1366]) {
  test(`Owner preparation keyboard and layout ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const start = "2030-05-01";
    const end = "2030-05-31";
    const metric = (kind: string) => ({
      metric: kind,
      scope: "account",
      account_id: 1,
      performance_currency: "RUB",
      value: null,
      value_unit: "percentage_points",
      annualized: kind === "xirr",
      availability: "not_computable",
      quality: "not_computable",
      reason_codes: [],
      period: { start_date: start, end_date: end },
    });
    const writes: string[] = [];
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith("/api/")) {
        await route.continue();
        return;
      }
      if (route.request().method() !== "GET") {
        writes.push(url.pathname);
        await route.fulfill({ status: 409, json: { detail: "synthetic stale save" } });
        return;
      }
      let json: unknown = [];
      if (url.pathname === "/api/accounts")
        json = [
          {
            id: 1,
            name: "Синтетический инвестиционный счёт для проверки длинного названия",
            account_type: "brokerage",
            status: "active",
            include_in_returns: false,
          },
        ];
      if (url.pathname === "/api/months") json = [];
      if (url.pathname === "/api/performance/readiness")
        json = {
          schema_version: 1,
          scope: "account",
          account_id: 1,
          start_date: start,
          end_date: end,
          performance_currency: "RUB",
          xirr: metric("xirr"),
          twrr: metric("twrr"),
          diagnostics: [],
          evidence: {
            scope_membership: { account_ids: [1], missing_or_ambiguous_account_ids: [1] },
            cash_boundary_coverage: { account_ids: [], missing_or_incomplete_account_ids: [] },
            in_kind_boundary_coverage: { account_ids: [] },
          },
        };
      if (url.pathname === "/api/performance/preparation")
        json = {
          account_id: 1,
          start_date: start,
          end_date: end,
          evidence_token: "synthetic",
          flows: [],
          transfer_links: [],
          cash_coverages: [],
          in_kind_coverages: [],
          movements: [],
          cash_balances: [],
          months: [{ id: 4, period_start: start, period_end: end, status: "draft" }],
        };
      if (url.pathname === "/api/performance/membership")
        json = {
          account_id: 1,
          start_date: start,
          end_date: end,
          scope: "account",
          rows: [],
          identity: "synthetic-history",
          form_token: "synthetic-form",
          readiness: {
            scope: "account",
            account_id: 1,
            start_date: start,
            end_date: end,
            xirr: metric("xirr"),
            twrr: metric("twrr"),
          },
        };
      await route.fulfill({ json });
    });
    await page.goto(
      `/v2/capital/performance?start=${start}&end=${end}&scope=account&account_id=1&prepare_account=1&prepare_reason=cash_history#performance-preparation`,
    );
    const add = page.getByRole("button", { name: "Добавить операцию" });
    await expect(add).toBeVisible();
    await add.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByLabel("Сумма операции")).toBeVisible();
    await page.getByLabel("Отчёт операции").selectOption("4");
    await page.getByLabel("Дата операции").fill("2030-05-12");
    await page.getByLabel("Сумма операции").fill("123.45");
    await expect(page.getByRole("button", { name: "Сохранить операцию" })).toBeDisabled();
    await page.getByLabel(/Я проверил.*дату, счёт, сумму/).check();
    await expect(page.getByRole("button", { name: "Сохранить операцию" })).toBeDisabled();
    await page.getByLabel("Счёт операции").selectOption("1");
    await expect(page.getByLabel(/Я проверил.*дату, счёт, сумму/)).not.toBeChecked();
    await page.getByLabel(/Я проверил.*дату, счёт, сумму/).check();
    await expect(page.getByRole("button", { name: "Сохранить операцию" })).toBeEnabled();
    const addInterval = page.getByRole("button", { name: "Добавить явный интервал" });
    await addInterval.focus();
    await page.keyboard.press("Enter");
    await page.getByLabel("Начало", { exact: true }).fill(start);
    await page.getByLabel("Конец включительно").fill(end);
    await expect(
      page.getByRole("button", { name: "Подтвердить изменение участия" }),
    ).toBeDisabled();
    await page.getByRole("combobox", { name: "Участие", exact: true }).selectOption("excluded");
    await page.getByLabel(/Я проверил.*полный набор/).check();
    await expect(page.getByRole("button", { name: "Подтвердить изменение участия" })).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
    const dir = path.resolve(".visual-audit", testInfo.project.name);
    fs.mkdirSync(dir, { recursive: true });
    await page.screenshot({
      path: path.join(dir, `performance-preparation-${width}.png`),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Сохранить операцию" }).click();
    await expect(page.getByText(/Форма устарела/)).toBeVisible();
    expect(writes).toEqual(["/api/external-flows"]);
  });
}

for (const width of [1366]) {
  test(`ui-v2 class Owner preparation keyboard and lifecycle ${width}px @viewport-owned`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const start = "2030-01-31";
    const end = "2030-02-28";
    let identity: string | null = null;
    let coverage: Record<string, unknown> | null = null;
    let closed = false;
    const writes: string[] = [];
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (!url.pathname.startsWith("/api/")) {
        await route.continue();
        return;
      }
      const method = request.method();
      if (url.pathname === "/api/months") {
        await route.fulfill({
          json: [start, end].map((date, i) => ({
            id: i + 1,
            year: 2030,
            month: i + 1,
            snapshot_date: date,
            status: closed ? "closed" : "draft",
            source: "manual",
          })),
        });
      } else if (url.pathname === "/api/performance/class-returns") {
        const cls = url.searchParams.get("asset_class") as string;
        const row = classReturnsFixture(cls, start, end);
        if (cls !== "deposit" && !closed) {
          row.eligibility_status = "unavailable";
          row.coverage_state = coverage ? "complete" : "unknown";
          row.evidence_reason_codes = identity
            ? ["reporting_month_not_closed"]
            : ["historical_class_unknown", "reporting_month_not_closed"];
          for (const kind of ["xirr", "twrr"] as const)
            Object.assign(row[kind], {
              availability: "not_computable",
              quality: "unavailable",
              value: null,
              reason_source: "evidence",
              reason_codes: row.evidence_reason_codes,
            });
        }
        await route.fulfill({ json: row });
      } else if (url.pathname === "/api/accounts") {
        await route.fulfill({ json: [{ id: 3, name: "Synthetic Broker" }] });
      } else if (url.pathname === "/api/instruments") {
        await route.fulfill({
          json: [{ id: 4, name: "Synthetic Security", instrument_type: "bond" }],
        });
      } else if (url.pathname === "/api/positions" || url.pathname === "/api/positions/7") {
        if (method === "PATCH") {
          expect(request.headers()["if-match"]).toBe("2030-03-01T00:00:00");
          expect(request.postDataJSON()).toEqual({ historical_instrument_type: "stock" });
          identity = "stock";
          writes.push("C1");
        }
        const position = {
          id: 7,
          reporting_month_id: 1,
          account_id: 3,
          instrument_id: 4,
          historical_instrument_type: identity,
          updated_at: identity ? "2030-03-02T00:00:00" : "2030-03-01T00:00:00",
        };
        await route.fulfill({
          json:
            method === "PATCH"
              ? position
              : url.searchParams.get("month_id") === "1"
                ? [position]
                : [],
        });
      } else if (url.pathname === "/api/class-evidence/coverages") {
        if (method === "POST") {
          const body = request.postDataJSON();
          expect(body).toMatchObject({
            asset_class: "stock",
            covered_from: start,
            covered_to: end,
            coverage_state: "complete",
            opening_inventory_complete: true,
            closing_inventory_complete: true,
          });
          coverage = { ...body, id: 5, revision: 1 };
          writes.push("coverage");
        }
        await route.fulfill({ json: method === "POST" ? coverage : coverage ? [coverage] : [] });
      } else {
        if (method !== "GET") writes.push(`unexpected ${method} ${url.pathname}`);
        await route.fulfill({ json: [] });
      }
    });
    await page.goto(
      `/v2/capital/performance?start=${start}&end=${end}&scope=portfolio&view=classes`,
    );
    const prepare = page.locator("summary", { hasText: "Подготовить подтверждения классов" });
    await prepare.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("historical_class_unknown", { exact: true }).last()).toBeVisible();
    await page.getByText("Исторический класс C1: все наблюдаемые строки интервала").click();
    await expect(page.getByText(/Позиция 7 · Synthetic Broker · Synthetic Security/)).toBeVisible();
    await expect(page.getByText(/Не подтверждён \/ неизвестно/)).toBeVisible();
    const identitySelect = page.getByRole("combobox", {
      name: "Исторический класс позиции 7",
      exact: true,
    });
    await identitySelect.focus();
    await identitySelect.selectOption("stock");
    await page.getByLabel("Я сверил(а) исторический класс позиции 7 с источником").check();
    const saveIdentity = page.getByRole("button", { name: "Сохранить C1 позиции 7" });
    await saveIdentity.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText(/Данные перечитаны/)).toBeVisible();
    await expect(page.getByText(/Данные перечитаны/)).toBeFocused();
    const saveCoverage = page.getByRole("button", { name: "Сохранить подтверждение класса" });
    await expect(saveCoverage).toBeDisabled();
    await page
      .getByRole("combobox", { name: "Состояние подтверждения", exact: true })
      .selectOption("complete");
    await page.getByLabel(/пересечений границы класса/).check();
    await page.getByLabel(/Полный состав класса на начало/).check();
    await page.getByLabel(/Полный состав класса на конец/).check();
    await page
      .getByLabel("Подтверждаю выбранное состояние и обе декларации состава", { exact: true })
      .check();
    await saveCoverage.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText(/Исправление \/ отзыв подтверждения 5 · версия 1/)).toBeVisible();
    await expect(saveCoverage).toBeDisabled();
    // The existing month lifecycle owns Close; this UI only rereads its committed outcome.
    closed = true;
    await page.getByRole("button", { name: "Перечитать подготовку класса" }).click();
    await expect(page.getByTestId("class-return-stock")).toContainText("+10,12%");
    await expect(page.getByText(/Сначала явно откройте все CLOSED/)).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Сохранить подтверждение класса" }),
    ).toBeDisabled();
    expect(writes).toEqual(["C1", "coverage"]);
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    const dir = path.resolve(".visual-audit", testInfo.project.name);
    fs.mkdirSync(dir, { recursive: true });
    await page.screenshot({
      path: path.join(dir, `ui-v2-class-owner-preparation-${width}.png`),
      fullPage: true,
    });
  });
}
