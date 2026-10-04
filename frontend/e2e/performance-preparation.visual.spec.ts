import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { classReturnsFixture } from "../src/test/classReturnsFixture";

for (const width of [390, 1366]) {
  for (const scenario of ["values", "evidence", "xirr-only"] as const) {
    test(`ui-v2 class returns ${scenario} keyboard and layout ${width}px @viewport-owned`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const start = "2031-05-31";
      const end = "2031-07-31";
      const reads: string[] = [];
      const unexpected: string[] = [];
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.route("**/api/**", async (route) => {
        const url = new URL(route.request().url());
        if (!url.pathname.startsWith("/api/")) {
          await route.continue();
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
        reads.push(assetClass);
        expect(url.searchParams.get("start_date")).toBe(start);
        expect(url.searchParams.get("end_date")).toBe(end);
        const row = classReturnsFixture(assetClass, start, end);
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
    });
  }
}

for (const width of [390, 1366]) {
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
