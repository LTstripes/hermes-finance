import { expect, test } from "@playwright/test";

test("exact EOD observations and known payouts remain separate on desktop", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const instruments = await (await request.get("/api/instruments")).json();
  const bond = instruments.find((i: { instrument_type: string }) => i.instrument_type === "bond");
  const stock = instruments.find((i: { instrument_type: string }) => i.instrument_type === "stock");
  const query = "account_id=1&t0=2030-01-31&t1=2030-02-28";
  const api = await (
    await request.get(`/api/instruments/${bond.id}/eod-observations?${query}`)
  ).json();
  expect(api.opening.market_value).toBe("1000.00");
  expect(api.closing.market_value).toBe("950.00");
  expect(api.known_payouts.known_booked_net.coupon).toBe("120.00");
  expect(api.comparable).toBeNull();
  expect(api.observed_position_value_difference).toBeNull();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(
    "/v2/capital/performance?start=2030-01-31&end=2030-02-28&scope=account&account_id=1&view=accounts",
  );
  const panel = page.getByRole("region", { name: "Известные выплаты по бумаге", exact: true });
  await panel.getByRole("button", { name: "Выбрать бумагу и период" }).click();
  await expect(panel.getByRole("button", { name: "Прочитать оценки и выплаты" })).toBeDisabled();
  await panel.getByLabel("Бумага выплат").selectOption(String(bond.id));
  await panel.getByRole("button", { name: "Прочитать оценки и выплаты" }).focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByTestId("instrument-eod-result")).toBeVisible();
  const eod = panel.getByRole("region", { name: "Наблюдаемые EOD-оценки" });
  await expect(eod.getByText("1000,00 ₽", { exact: true })).toBeVisible();
  await expect(eod.getByText("950,00 ₽", { exact: true })).toBeVisible();
  await expect(panel.getByText(/купоны 120,00 ₽; дивиденды Неизвестно/)).toBeVisible();
  await expect(eod.getByText("Полная доходность RUB/% пока недоступна.")).toBeVisible();
  await expect(panel.getByText(/70,00 ₽|7,00%|7%/)).toHaveCount(0);
  await eod.getByText("Происхождение EOD").first().click();
  await expect(eod.getByText(/Подтверждение: eod-open/)).toBeVisible();
  await panel.screenshot({ path: info.outputPath("eod-bond-coupon-1440.png") });
  await panel.getByLabel("Бумага выплат").selectOption(String(stock.id));
  await expect(panel.getByTestId("instrument-eod-result")).toHaveCount(0);
  await expect(panel.getByTestId("known-payouts-result")).toHaveCount(0);
  await panel.getByRole("button", { name: "Прочитать оценки и выплаты" }).click();
  await expect(eod.getByText("900,00 ₽", { exact: true })).toBeVisible();
  await expect(panel.getByText(/дивиденды 120,00 ₽/)).toBeVisible();
  await expect(
    eod.getByText(
      /Разница наблюдаемых стоимостей позиции: -100,00 ₽. Это не прибыль и не доходность/,
    ),
  ).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel.screenshot({ path: info.outputPath("eod-stock-dividend-1280-125.png") });
  await panel.getByLabel("Выплаты по дату").fill("2030-02-27");
  await expect(panel.getByTestId("instrument-eod-result")).toHaveCount(0);
  await panel.getByRole("button", { name: "Прочитать оценки и выплаты" }).click();
  await expect(eod.getByText(/На эту точную дату нет сохранённой позиции/)).toBeVisible();
  await expect(eod.getByText(/Разница наблюдаемых стоимостей позиции/)).toHaveCount(0);
  await panel.screenshot({ path: info.outputPath("eod-exact-date-gap-1280-125.png") });
  expect(errors).toEqual([]);
});
