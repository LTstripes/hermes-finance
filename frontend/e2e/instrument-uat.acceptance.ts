import { expect, test } from "@playwright/test";

test("isolated production UAT entry makes only allowed GETs and reuses canonical readers", async ({
  page,
  request,
}, info) => {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("request", (r) => requests.push(`${r.method()} ${r.url()}`));
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  const instruments = await (await request.get("/api/instruments")).json();
  const stock = instruments.find((r: { instrument_type: string }) => r.instrument_type === "stock");
  const bond = instruments.find((r: { instrument_type: string }) => r.instrument_type === "bond");
  const query = "account_id=1&t0=2030-01-31&t1=2030-02-28";
  for (const endpoint of [
    "cash-income",
    "eod-observations",
    "known-trades",
    "conditional-return",
  ]) {
    const response = await request.get(
      `/api/instruments/${stock.id}/${endpoint}?${query}&request_nonce=synthetic`,
    );
    expect(response.status()).toBe(200);
    expect(response.headers()["cache-control"]).toBe("no-store");
  }
  for (const path of [
    "/api/months",
    "/api/settings",
    "/api/quotes/refresh",
    "/v2/capital/performance",
    "/index.html",
  ]) {
    expect((await request.get(path)).status()).toBe(404);
  }
  expect((await request.post("/api/accounts", { data: { name: "forbidden" } })).status()).toBe(405);
  await page.goto("/");
  await page.getByRole("button", { name: "Выбрать бумагу и период" }).click();
  await page.getByLabel("Счёт выплат").selectOption("1");
  await page.getByLabel("Бумага выплат").selectOption(String(stock.id));
  await page.getByLabel("Выплаты после даты").fill("2030-01-31");
  await page.getByLabel("Выплаты по дату").fill("2030-02-28");
  await page.getByRole("button", { name: "Прочитать оценки и выплаты" }).click();
  await expect(page.getByTestId("known-payouts-result")).toContainText("150,00");
  const panel = page.getByRole("region", { name: "Условный результат бумаги", exact: true });
  for (const cb of await panel.getByRole("checkbox").all()) {
    await expect(cb).not.toBeChecked();
    await cb.focus();
    await page.keyboard.press("Space");
  }
  await panel.getByRole("button", { name: "Рассчитать условный результат" }).focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByText("Условно: +50,00 ₽ / +5% за период")).toBeVisible();
  await expect(panel.getByText("Фактическая доходность пока недоступна")).toBeVisible();
  await page.screenshot({ path: info.outputPath("instrument-uat-1440.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("instrument-uat-1280-125.png"), fullPage: true });
  await page.getByLabel("Счёт выплат").selectOption("2");
  await page.getByLabel("Счёт выплат").selectOption("1");
  await expect(panel.getByText(/Условно:/)).toHaveCount(0);
  for (const cb of await panel.getByRole("checkbox").all()) await expect(cb).not.toBeChecked();
  for (const cb of await panel.getByRole("checkbox").all()) await cb.check();
  await panel.getByRole("button", { name: "Рассчитать условный результат" }).click();
  await expect(panel.getByText(/Условно:/)).toBeVisible();
  await page.route("**/conditional-return?**", (route) =>
    route.fulfill({
      status: 503,
      body: '{"detail":"synthetic unavailable"}',
      contentType: "application/json",
    }),
  );
  await panel.getByRole("button", { name: "Рассчитать условный результат" }).click();
  await expect(panel.getByRole("alert")).toContainText("Не удалось проверить сценарий");
  await expect(panel.getByText(/Условно:/)).toHaveCount(0);
  await page.unroute("**/conditional-return?**");
  await page.getByLabel("Бумага выплат").selectOption(String(bond.id));
  for (const cb of await panel.getByRole("checkbox").all()) await cb.check();
  await panel.getByRole("button", { name: "Рассчитать условный результат" }).click();
  await expect(panel.getByText(/bond_dirty_basis_source_unproven/)).toBeVisible();
  await expect(panel.getByText(/Условно:/)).toHaveCount(0);
  await expect(page.getByRole("link")).toHaveCount(0);
  for (const record of requests) {
    const [method, url] = record.split(" ");
    expect(method).toBe("GET");
    const target = new URL(url);
    expect(target.origin).toBe("http://127.0.0.1:18868");
    expect(target.pathname).toMatch(
      /^\/$|^\/assets\/[\w.-]+\.(js|css)$|^\/api\/(accounts|instruments)$|^\/api\/instruments\/\d+\/(eod-observations|known-trades|conditional-return)$/,
    );
  }
  expect(errors).toEqual([]);
});
