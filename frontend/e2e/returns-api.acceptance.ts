import { expect, test } from "@playwright/test";

test("basket actual API: all/one/none, signed source-only coverage, separate interest, Back/Reload", async ({
  page,
  request,
}, testInfo) => {
  await page.goto("/v2/returns/account");
  const basket = page.getByRole("region", { name: "Моя доходность" });
  await expect(basket.getByRole("checkbox")).toHaveCount(4);
  for (const box of await basket.getByRole("checkbox").all()) await expect(box).toBeChecked();
  const source = basket.getByRole("region", { name: "Известная часть по выпискам" });
  const deposits = basket.getByRole("region", { name: "Полученные депозитные проценты" });
  await expect(source).toContainText("0 ₽");
  await expect(source).toContainText("2 из 2");
  await expect(deposits).toContainText("+3 ₽");
  const result = await request.get(
    "/api/returns/basket?start=2030-03-31&end=2030-04-30&categories=brokerage,iis,deposits,gold",
  );
  expect(result.headers()["cache-control"]).toBe("no-store");
  const body = await result.json();
  expect(body.result_kopecks).toBeNull();
  expect(body.rate.value).toBeNull();
  expect(body.known_partial_subtotal_kopecks).toBe("0");
  expect(body.deposit_received_interest.value_kopecks).toBe("300");
  await basket.getByText("Покрытие и причины по категориям").click();
  await expect(basket.getByText(/Текущая стоимость и прирост от цены покупки/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("basket-all-coverage.png"), fullPage: true });
  for (const name of ["Брокерские счета", "ИИС", "Физическое золото"])
    await basket.getByRole("checkbox", { name, exact: true }).uncheck();
  await expect(page).toHaveURL(/categories=deposits/);
  await expect(deposits).toContainText("+3 ₽");
  await page.reload();
  await expect(basket.getByRole("checkbox", { name: "ИИС", exact: true })).not.toBeChecked();
  await expect(deposits).toContainText("+3 ₽");
  await basket.getByRole("checkbox", { name: "Депозиты и накопительные", exact: true }).uncheck();
  await expect(basket).toContainText("Выбери хотя бы одну категорию");
  await expect(basket.locator("strong")).toHaveCount(0);
  await page.goBack();
  await expect(deposits).toContainText("+3 ₽");
  await page.reload();
  await expect(deposits).toContainText("+3 ₽");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
});

test("duplicate alias scope fails closed without an overview request", async ({
  page,
  request,
}) => {
  const calls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/returns/")) calls.push(r.url());
  });
  const path =
    "/v2/returns?scope=source:1234567&scope=source:7654321-000&start=2030-03-31&end=2030-04-30";
  await page.goto(path);
  await expect(
    page.getByRole("combobox", { name: "Счёт" }).locator("option:not([disabled])"),
  ).toHaveCount(2);
  await expect(page).toHaveURL(/scope=source:1234567&scope=source:7654321-000&start=/);
  await expect(page.getByRole("region", { name: "Результат периода" })).toHaveCount(0);
  expect(calls.some((url) => url.includes("/overview"))).toBe(false);
  const bad = await request.get(
    "/api/returns/overview?scope=source:1234567&scope=source:7654321-000&start=2030-03-31&end=2030-04-30",
  );
  expect(bad.status()).toBe(422);
  // The existing app-wide HTTP error renderer drops exception headers.
  // Successful Returns reads are checked for no-store below; this regression
  // verifies invalid identity remains rejected in both UI and API.
});

test("real synthetic API → desktop: CLOSED before DRAFT, same ISIN in two accounts, exact GETs", async ({
  page,
  request,
}, testInfo) => {
  const responses: number[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/returns/")) responses.push(r.status());
  });
  page.on("request", (r) => expect(r.method()).toBe("GET"));
  await page.goto("/v2/returns/account");
  await expect(page.getByRole("region", { name: "Результат периода" })).toBeVisible();
  await expect(page).toHaveURL(/start=2030-03-31&end=2030-04-30/);
  await expect(
    page.getByRole("combobox", { name: "Счёт" }).locator("option:not([disabled])"),
  ).toHaveCount(2);
  await expect(page.getByRole("combobox", { name: "Счёт" })).not.toContainText("Учебный депозит");
  const partial = page.getByRole("region", { name: "За доступные месяцы", exact: true });
  await expect(partial).toContainText("За доступные месяцы · 2 из 3");
  await expect(partial).toContainText("+80 ₽");
  const instruments = page.getByRole("region", { name: "По инструментам" });
  const tops = page.getByRole("region", { name: "Лидеры и отстающие" });
  await expect(tops.locator("li")).toHaveCount(1);
  await expect(tops.locator("li > span")).toHaveText("Учебная акция из каталогаRU000A000000");
  await expect(tops.locator("small")).toHaveText("RU000A000000");
  await expect(instruments.getByRole("cell", { name: /\+100/ })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("returns-catalogue-account-a.png"),
    fullPage: true,
  });
  await page.getByRole("combobox", { name: "Счёт" }).selectOption("source:7654321-000");
  await expect(instruments.getByRole("cell", { name: /−100/ })).toBeVisible();
  await expect(tops.locator("li > span")).toHaveText("Учебная акция из каталогаRU000A000000");
  await instruments.getByRole("button").click();
  await expect(page.getByText("Количество: 10 → 10")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Счёт" })).toHaveValue("source:7654321-000");
  await expect(instruments.getByRole("cell", { name: /−100/ })).toBeVisible();
  const overview = await request.get(
    "/api/returns/overview?scope=source:7654321-000&start=2030-03-31&end=2030-04-30",
  );
  expect(overview.headers()["cache-control"]).toBe("no-store");
  const body = await overview.json();
  expect(body.instruments[0].pnl.value).toBe("-10000");
  expect(body.instruments[0].name).toBe("Учебная акция из каталога");
  const bad = await request.get(
    "/api/returns/overview?scope=source:7654321-000&scope=portfolio&start=2030-03-31&end=2030-04-30",
  );
  expect(bad.status()).toBe(422);
  expect(responses.every((s) => s === 200)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("returns-actual-api.png"), fullPage: true });
});

test("alias history links, partial coverage, keyboard details, Back and accepted compatibility", async ({
  page,
  request,
}, testInfo) => {
  const context = await (await request.get("/api/returns/context")).json();
  expect(context.scope_aliases["source:1234567"]).toBe("source:1234567-000");
  await page.goto("/v2/capital/monthly-returns?source_account=1234567#bond-slice");
  await expect(page).toHaveURL(/scope=source%3A1234567-000.*start=2030-03-31&end=2030-06-30/);
  const result = page.getByRole("region", { name: "Результат периода", exact: true });
  await expect(result).toContainText("За доступные месяцы · 2 из 3");
  await expect(result).toContainText("+80 ₽");
  await expect(result).not.toContainText("%");
  const info = result.getByLabel("Подробнее: Покрытие доступных месяцев", { exact: true });
  await info.focus();
  await page.keyboard.press("Enter");
  await expect(result.getByText("Не учтён: 30.04.2030 — 31.05.2030")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("returns-partial-coverage.png"),
    fullPage: true,
  });
  const body = await (
    await request.get("/api/returns/overview?scope=source:1234567&start=2030-03-31&end=2030-06-30")
  ).json();
  expect(body.all_history.pnl.value).toBeNull();
  expect(body.all_history.rate.value).toBeNull();
  expect(body.available_months_total.pnl.value).toBe("8000");
  await page.getByRole("combobox", { name: "Счёт" }).selectOption("source:7654321-000");
  await expect(result).toContainText("−80 ₽");
  await page.goBack();
  await expect(result).toContainText("+80 ₽");
  await page.reload();
  await expect(result).toContainText("+80 ₽");
  const acceptedScope = context.accounts.find(
    (a: { label: string }) => a.label === "Учебный депозит",
  ).id;
  await page.goto(`/v2/returns?scope=${acceptedScope}&start=2030-03-31&end=2030-06-30`);
  await expect(page.getByRole("combobox", { name: "Счёт" })).toHaveValue(acceptedScope);
  await expect(page.getByRole("combobox", { name: "Представление" })).toHaveCount(0);
  await expect(result).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
});
