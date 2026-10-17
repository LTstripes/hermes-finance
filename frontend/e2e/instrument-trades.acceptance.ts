import { expect, test } from "@playwright/test";

test("canonical executions and independently accepted cash stay separate on desktop", async ({
  page,
  request,
}, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const instruments = await (await request.get("/api/instruments")).json();
  const stock = instruments.find((i: { instrument_type: string }) => i.instrument_type === "stock");
  const path = `/api/instruments/${stock.id}/known-trades`;
  const api = await (await request.get(`${path}?account_id=1&t0=2029-12-31&t1=2030-01-31`)).json();
  expect(api.known_count).toBe(2);
  expect(api.events[0].cash_legs.map((l: { signed_rub: string | null }) => l.signed_rub)).toEqual([
    "-100.00",
    null,
    "-1.25",
  ]);
  expect(api.trade_history_completeness).toBe("unknown");
  expect(api.dependency_fingerprint).toBeNull();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(
    "/v2/capital/performance?start=2029-12-31&end=2030-01-31&scope=account&account_id=1&view=accounts",
  );
  const panel = page.getByRole("region", { name: "Известные выплаты по бумаге", exact: true });
  await panel.getByRole("button", { name: "Выбрать бумагу и период" }).click();
  await expect(panel.getByRole("button", { name: "Прочитать оценки и выплаты" })).toBeDisabled();
  await panel.getByLabel("Бумага выплат").selectOption(String(stock.id));
  await panel.getByRole("button", { name: "Прочитать оценки и выплаты" }).focus();
  await page.keyboard.press("Enter");
  const trades = panel.getByRole("region", { name: "Известные сделки и расчёты", exact: true });
  await expect(trades.getByTestId("known-trades-result")).toBeVisible();
  await expect(trades.getByText("Расчёт по сделке: -100,00 ₽", { exact: true })).toHaveCount(2);
  await expect(trades.getByText("Комиссия: -1,25 ₽", { exact: true })).toHaveCount(2);
  await expect(trades.getByText("Уплаченный НКД: Неизвестно", { exact: true })).toHaveCount(2);
  await trades
    .getByText(/Native IDs:/)
    .first()
    .click();
  await expect(trades.getByText(/Исполнение проверено при чтении/).first()).toBeVisible();
  await trades.screenshot({ path: info.outputPath("trades-two-identities-1440.png") });
  await panel.getByLabel("Выплаты по дату").fill("2030-01-15");
  await expect(trades.getByTestId("known-trades-result")).toHaveCount(0);
  await panel.getByRole("button", { name: "Прочитать оценки и выплаты" }).click();
  await expect(trades.getByText(/Расчёт: .*вне \(t0,t1\]/).first()).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await trades.screenshot({ path: info.outputPath("trades-boundary-crossing-1280-125.png") });
  // Delay a real API response; a newer account selection must suppress it.
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**${path}?**`, async (route) => {
    const response = await route.fetch();
    await held;
    // Selector invalidation aborts fetch via AbortSignal; Chromium can already
    // have handled that route when the deliberately delayed response is released.
    await route.fulfill({ response }).catch((error) => {
      if (!String(error).includes("Route is already handled")) throw error;
    });
  });
  await panel.getByRole("button", { name: "Прочитать оценки и выплаты" }).click();
  await expect(trades.getByRole("status")).toBeVisible();
  await panel.getByLabel("Счёт выплат").selectOption("2");
  release();
  await expect(trades.getByTestId("known-trades-result")).toHaveCount(0);
  await page.unroute(`**${path}?**`);
  await panel.getByRole("button", { name: "Прочитать оценки и выплаты" }).click();
  await expect(trades.getByText(/Это не доказывает отсутствия сделок/)).toBeVisible();
  await expect(trades.getByText(/Нет источника, подтверждающего состав операций/)).toBeVisible();
  await trades.screenshot({ path: info.outputPath("trades-empty-source-gap-1280-125.png") });
  await page.route(`**${path}?**`, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"detail":"synthetic reader unavailable"}',
    }),
  );
  await panel.getByRole("button", { name: "Прочитать оценки и выплаты" }).click();
  await expect(trades.getByRole("alert")).toHaveText(/Не удалось прочитать сделки/);
  await expect(trades.getByTestId("known-trades-result")).toHaveCount(0);
  expect(errors).toEqual([]);
});
