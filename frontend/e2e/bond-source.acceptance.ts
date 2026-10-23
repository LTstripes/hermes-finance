import { expect, test } from "@playwright/test";

test("two-account bond desktop: reported holdings, linked coupons, eligible estimates, unknown NKD and reload", async ({
  page,
  request,
}, info) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const before = await (await request.get("/api/synthetic-bond-state")).json();
  const errors: string[] = [];
  const mutations: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (r) => {
    if (!["GET", "HEAD"].includes(r.method())) mutations.push(`${r.method()} ${r.url()}`);
  });
  await page.goto(
    "/v2/capital/monthly-returns?source_account=7654321&bond_period=2030-05-01#bond-slice",
  );
  const panel = page.getByRole("region", { name: "Облигации: позиции, сделки и купоны" });
  await expect(panel.getByText("7654321-000", { exact: true })).toBeVisible();
  const first = withinTable();
  function withinTable() {
    return panel.getByRole("table", { name: "Облигации выбранного счёта и периода" });
  }
  await expect(first.getByRole("cell", { name: "2", exact: true })).toBeVisible();
  await expect(first.getByRole("cell", { name: /2.010,00/ })).toBeVisible();
  await expect(panel.getByText(/Сделок в выбранном интервале нет/)).toBeVisible();
  await expect(panel.getByRole("region", { name: "Условная оценка по выписке" })).toContainText(
    "40,00 ₽",
  );
  await expect(panel.getByRole("table", { name: "Купоны по строкам источников" })).toContainText(
    "Сохранённая связь с инструментом",
  );
  const native = await (
    await request.get(
      "/api/source-returns/instruments?source_account=7654321&opening_date=2030-04-30&closing_date=2030-05-31",
    )
  ).json();
  const bond = native.instruments.find((row: { isin: string }) => row.isin === "RU000A000001");
  expect(native.financial_authority).toBe("none");
  expect(bond.analysis.pnl.value).toBeNull();
  expect(bond.analysis.modified_dietz.value).toBeNull();
  expect(bond.analysis.statement_estimate.pnl.value).toBe(4000);
  await panel.screenshot({ path: info.outputPath("bond-no-trade-1440.png") });

  await page.getByLabel("Счёт в выписке", { exact: true }).selectOption("8765432");
  await panel.getByLabel("Период облигаций").selectOption("2030-05-01");
  await expect(panel.getByText("8765432-000", { exact: true })).toBeVisible();
  await expect(withinTable().getByRole("cell", { name: "8", exact: true })).toBeVisible();
  await expect(panel.getByRole("table", { name: "Сделки по строкам источников" })).toContainText(
    "% от номинала",
  );
  await expect(panel.getByRole("region", { name: "Условная оценка по выписке" })).toContainText(
    "55,00 ₽",
  );
  await page.reload();
  await expect(page.getByLabel("Счёт в выписке", { exact: true })).toHaveValue("8765432");
  await expect(panel.getByLabel("Период облигаций")).toHaveValue("2030-05-01");
  await expect(withinTable().getByRole("cell", { name: "8", exact: true })).toBeVisible();
  await panel.getByLabel("Период облигаций").selectOption("2030-06-01");
  await expect(panel.getByRole("region", { name: "Условная оценка по выписке" })).toHaveCount(0);
  await expect(panel.getByText("Условная оценка недоступна", { exact: true })).toBeVisible();
  await expect(panel.getByRole("table", { name: "Сделки по строкам источников" })).toContainText(
    "Не учтено в расчёте",
  );
  await panel.getByText("Полнота и происхождение", { exact: true }).click();
  await expect(panel.getByText(/Выписка #/).first()).toBeVisible();
  await panel.screenshot({ path: info.outputPath("bond-nkd-gap-1440.png") });
  await page.goBack();
  await expect(panel.getByLabel("Период облигаций")).toHaveValue("2030-05-01");
  await expect(panel.getByRole("region", { name: "Условная оценка по выписке" })).toBeVisible();
  expect(await (await request.get("/api/synthetic-bond-state")).json()).toEqual(before);
  expect(mutations).toEqual([]);
  expect(errors).toEqual([]);
});
