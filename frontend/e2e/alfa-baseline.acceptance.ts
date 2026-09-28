import { expect, test } from "@playwright/test";

test("synthetic real-backend: cancel, stale, apply/readback, desktop and 390px keyboard", async ({
  page,
  request,
}, info) => {
  let writes = 0;
  let providerReads = 0;
  page.on("request", (req) => {
    if (req.url().includes("broker-baseline-apply")) writes += 1;
    if (req.url().includes("broker-snapshot-preview")) providerReads += 1;
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(
    "/v2/data/alfa-baseline?month=1&from=monthly-close-v2&monthId=1&step=alfa_baseline#synthetic",
  );
  await expect(page.getByRole("heading", { name: "Текущий базовый срез" })).toBeVisible();
  expect(providerReads).toBe(0);
  const before = await (await request.get("/api/positions?month_id=1")).json();
  expect(before[0].quantity).toMatch(/^9(?:\.0+)?$/);
  const preview = page.getByRole("button", { name: "Получить данные из Альфа PRO" });
  await preview.click();
  const row = page.getByRole("checkbox", { name: /Выбрать позицию/ });
  await row.check();
  await page.getByRole("button", { name: "Применить выбранный базовый срез" }).click();
  await expect(page.getByRole("button", { name: "Отмена", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  expect(writes).toBe(0);
  expect(await (await request.get("/api/positions?month_id=1")).json()).toEqual(before);

  // Change local material state after preview using the canonical API.
  expect(
    (
      await request.patch(`/api/positions/${before[0].id}`, {
        data: { quantity: "8" },
        headers: { "If-Match": before[0].updated_at },
      })
    ).ok(),
  ).toBe(true);
  await page.getByRole("button", { name: "Применить выбранный базовый срез" }).click();
  const stale = page.waitForResponse((response) =>
    response.url().includes("broker-baseline-apply"),
  );
  await page.getByRole("button", { name: "Подтвердить базовый срез" }).click();
  expect((await (await stale).json()).error_code).toBe("preview_changed");
  await expect(preview).toBeVisible();
  expect((await (await request.get("/api/positions?month_id=1")).json())[0].quantity).toMatch(
    /^8(?:\.0+)?$/,
  );

  await preview.click();
  await row.check();
  await page.screenshot({ path: info.outputPath("desktop-preview.png"), fullPage: true });
  await page.getByRole("button", { name: "Применить выбранный базовый срез" }).click();
  await page.getByRole("button", { name: "Подтвердить базовый срез" }).dblclick();
  await expect(page.getByText("Базовый срез применён. Позиций: 1.", { exact: true })).toBeVisible();
  expect(writes).toBe(2);
  const after = await (await request.get("/api/positions?month_id=1")).json();
  expect(after[0].quantity).toMatch(/^10(?:\.0+)?$/);
  for (const key of [
    "average_cost_per_unit",
    "market_price_per_unit",
    "accrued_interest",
    "price_date",
    "price_source",
  ])
    expect(after[0][key]).toEqual(before[0][key]);
  await expect(page.getByRole("region", { name: "Актуальные позиции месяца" })).toContainText("10");
  await page.setViewportSize({ width: 390, height: 844 });
  await preview.click();
  await row.check();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  await page.screenshot({ path: info.outputPath("mobile-preview.png"), fullPage: true });
  await page.getByRole("button", { name: "Применить выбранный базовый срез" }).click();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Подтвердить базовый срез" })).toBeFocused();
  await page.keyboard.press("Escape");
  // An ambiguous network result must not reuse the previous success banner.
  await page.route("**/broker-baseline-apply", (route) => route.abort());
  await page.getByRole("button", { name: "Применить выбранный базовый срез" }).click();
  await page.getByRole("button", { name: "Подтвердить базовый срез" }).click();
  await expect(page.getByText(/Результат применения не подтверждён/)).toBeVisible();
  await expect(page.getByText("Базовый срез применён. Позиций: 1.", { exact: true })).toHaveCount(
    0,
  );
  await page.unroute("**/broker-baseline-apply");
  await preview.click();
  await row.check();
  await page.getByRole("button", { name: "Применить выбранный базовый срез" }).click();
  await page.getByRole("button", { name: "Подтвердить базовый срез" }).click();
  await expect(page.getByText("Базовый срез без изменений: 1.", { exact: true })).toBeVisible();

  await preview.click();
  await row.check();
  // UI apply is pending while another canonical action closes the month.
  await page.route("**/broker-baseline-apply", async (route) => {
    expect((await request.post("/api/months/1/close")).ok()).toBe(true);
    await route.continue();
  });
  await page.getByRole("button", { name: "Применить выбранный базовый срез" }).click();
  const closed = page.waitForResponse((response) =>
    response.url().includes("broker-baseline-apply"),
  );
  await page.getByRole("button", { name: "Подтвердить базовый срез" }).click();
  expect((await (await closed).json()).error_code).toBe("closed_month");
  expect(await (await request.get("/api/positions?month_id=1")).json()).toEqual(after);
  await page.getByRole("link", { name: "Вернуться к закрытию", exact: true }).click();
  await expect(page).toHaveURL(/\/v2\/close\?month=1&step=alfa_baseline/);
});
