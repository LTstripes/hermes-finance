import { expect, test } from "@playwright/test";

test("real synthetic API → desktop: CLOSED before DRAFT, same ISIN in two accounts, exact GETs", async ({
  page,
  request,
}, testInfo) => {
  const responses: number[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/returns/")) responses.push(r.status());
  });
  page.on("request", (r) => expect(r.method()).toBe("GET"));
  await page.goto("/v2/returns");
  await expect(page.getByRole("region", { name: "Результат периода" })).toBeVisible();
  await expect(page).toHaveURL(/start=2030-03-31&end=2030-04-30/);
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
