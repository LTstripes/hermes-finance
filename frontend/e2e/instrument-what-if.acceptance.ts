import { expect, test } from "@playwright/test";

test("source-backed hypothetical stock HPR API/desktop parity and invalidation", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const instruments = await (await request.get("/api/instruments")).json();
  const stock = instruments.find((i: { instrument_type: string }) => i.instrument_type === "stock");
  const bond = instruments.find((i: { instrument_type: string }) => i.instrument_type === "bond");
  const query = "account_id=1&t0=2030-01-31&t1=2030-02-28&request_nonce=desktop";
  const chosen =
    "&no_unobserved_movements=true&no_unobserved_payouts=true&no_other_costs_or_taxes=true";
  const path = `/api/instruments/${stock.id}/conditional-return`;
  const api = await (await request.get(`${path}?${query}${chosen}`)).json();
  expect(api.hard_blockers).toEqual([]);
  expect(api.hypothetical_result.conditional_result).toBe("50.00");
  expect(api.hypothetical_result.conditional_period_fraction).toBe("0.05");
  expect(api.hypothetical_result.conditional_period_percent).toBe("5");
  expect(api.actual_instrument_return).toBeNull();
  expect(api.accepted_known.trades.dependency_fingerprint).toBeNull();
  const blocked = await (
    await request.get(`/api/instruments/${bond.id}/conditional-return?${query}${chosen}`)
  ).json();
  expect(blocked.hard_blockers).toContain("bond_dirty_basis_source_unproven");
  expect(blocked.hypothetical_result.conditional_result).toBeNull();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(
    "/v2/capital/performance?start=2030-01-31&end=2030-02-28&scope=account&account_id=1&view=accounts",
  );
  const parent = page.getByRole("region", { name: "Известные выплаты по бумаге", exact: true });
  await parent.getByRole("button", { name: "Выбрать бумагу и период" }).click();
  await parent.getByLabel("Бумага выплат").selectOption(String(stock.id));
  const panel = parent.getByRole("region", { name: "Условный результат бумаги", exact: true });
  const calculate = panel.getByRole("button", { name: "Рассчитать условный результат" });
  for (const checkbox of await panel.getByRole("checkbox").all())
    await expect(checkbox).not.toBeChecked();
  await calculate.focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByText(/Выбраны не все три допущения/)).toBeVisible();
  await expect(panel.getByText(/Условно:/)).toHaveCount(0);
  // Keyboard Space opts into each distinct choice; Enter evaluates fresh.
  for (const checkbox of await panel.getByRole("checkbox").all()) {
    await checkbox.focus();
    await page.keyboard.press("Space");
  }
  await calculate.focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByText("Условно: +50,00 ₽ / +5% за период")).toBeVisible();
  await expect(panel.getByText("Фактическая доходность пока недоступна")).toBeVisible();
  await panel.screenshot({ path: info.outputPath("what-if-stock-1440.png") });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel.screenshot({ path: info.outputPath("what-if-stock-1280-125.png") });
  await panel.getByRole("checkbox").nth(1).uncheck();
  await expect(panel.getByText(/Условно:/)).toHaveCount(0);
  await panel.getByRole("checkbox").nth(1).check();
  let release!: () => void;
  const held = new Promise<void>((r) => {
    release = r;
  });
  await page.route(`**${path}?**`, async (route) => {
    const response = await route.fetch();
    await held;
    await route.fulfill({ response }).catch((error) => {
      if (!String(error).includes("Route is already handled")) throw error;
    });
  });
  await calculate.click();
  await expect(panel.getByRole("status")).toBeVisible();
  await parent.getByLabel("Счёт выплат").selectOption("2");
  await parent.getByLabel("Счёт выплат").selectOption("1");
  release();
  await page.unroute(`**${path}?**`);
  await expect(panel.getByText(/Условно:/)).toHaveCount(0);
  for (const checkbox of await panel.getByRole("checkbox").all()) await checkbox.check();
  await calculate.click();
  await expect(panel.getByText(/Условно:/)).toBeVisible();
  await page.route(`**${path}?**`, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"detail":"synthetic unavailable"}',
    }),
  );
  await calculate.click();
  await expect(panel.getByRole("alert")).toHaveText(/Не удалось проверить сценарий/);
  await expect(panel.getByText(/Условно:/)).toHaveCount(0);
  await page.unroute(`**${path}?**`);
  await parent.getByLabel("Бумага выплат").selectOption(String(bond.id));
  for (const checkbox of await panel.getByRole("checkbox").all()) await checkbox.check();
  await calculate.click();
  await expect(panel.getByText(/bond_dirty_basis_source_unproven/)).toBeVisible();
  await expect(panel.getByText(/Условно:/)).toHaveCount(0);
  await panel.screenshot({ path: info.outputPath("what-if-bond-blocked-1280-125.png") });
  expect(errors).toEqual([]);
});
