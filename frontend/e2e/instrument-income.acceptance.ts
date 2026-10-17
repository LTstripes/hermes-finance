import { expect, test } from "@playwright/test";

test("known net payout API→desktop: supported source, tax NULL, exited stock, gap and selector reset", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const accounts = await (await request.get("/api/accounts")).json();
  const instruments = await (await request.get("/api/instruments")).json();
  const account = accounts.find((a: { name: string }) => a.name === "Synthetic account");
  const empty = accounts.find((a: { name: string }) => a.name === "Synthetic empty payout account");
  const bond = instruments.find((i: { instrument_type: string }) => i.instrument_type === "bond");
  const stock = instruments.find((i: { instrument_type: string }) => i.instrument_type === "stock");
  const params = `account_id=${account.id}&t0=2029-12-31&t1=2030-01-31`;
  const api = await (await request.get(`/api/instruments/${bond.id}/cash-income?${params}`)).json();
  expect(api.known_booked_net.coupon).toBe("120.00");
  expect(api.events[0].tax).toBeNull();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(
    `/v2/capital/performance?start=2029-12-31&end=2030-01-31&scope=account&account_id=${account.id}&view=accounts`,
  );
  const block = page.getByRole("region", { name: "Известные выплаты по бумаге" });
  await block.getByRole("button", { name: "Выбрать бумагу и период" }).click();
  await expect(block.getByRole("button", { name: "Прочитать выплаты" })).toBeDisabled();
  await block.getByLabel("Бумага выплат").selectOption(String(bond.id));
  await block.getByRole("button", { name: "Прочитать выплаты" }).click();
  await expect(block.getByText("Источник подтверждён", { exact: true })).toBeVisible();
  await expect(block.getByText(/купоны 120,00 ₽; дивиденды Неизвестно/)).toBeVisible();
  await block.getByText(/Детали записи ICF/).click();
  await expect(block.getByText(/налог: Неизвестно/)).toBeVisible();
  await block.scrollIntoViewIfNeeded();
  await block.screenshot({ path: info.outputPath("known-coupon-1440.png") });
  await block.getByLabel("Бумага выплат").selectOption(String(stock.id));
  await expect(block.getByTestId("known-payouts-result")).toHaveCount(0);
  await block.getByRole("button", { name: "Прочитать выплаты" }).click();
  await expect(block.getByText(/дивиденды 120,00 ₽/)).toBeVisible();
  await block.getByLabel("Счёт выплат").selectOption(String(empty.id));
  await expect(block.getByTestId("known-payouts-result")).toHaveCount(0);
  await block.getByRole("button", { name: "Прочитать выплаты" }).click();
  await expect(block.getByText(/Это не подтверждает нулевой доход/)).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await block.screenshot({ path: info.outputPath("known-payout-gap-1280-125.png") });
  expect(errors).toEqual([]);
});
