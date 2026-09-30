import { expect, type Page, test } from "@playwright/test";

const startingMonths = [
  { id: 2, year: 2030, month: 6, status: "draft", snapshot_date: "2030-06-30", source: "manual" },
  { id: 1, year: 2030, month: 5, status: "closed", snapshot_date: "2030-05-31", source: "manual" },
];

async function installMonthsApi(page: Page) {
  let rows = [...startingMonths];
  const calls: string[] = [];
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      calls.push(`${request.method()} ${pathname}`);
      if (request.method() === "GET" && pathname === "/api/months") {
        await route.fulfill({ json: rows });
      } else if (request.method() === "POST" && pathname === "/api/months/2/clone") {
        const payload = request.postDataJSON();
        const created = { id: 3, status: "draft", source: "manual", ...payload };
        rows = [created, ...rows];
        await route.fulfill({ status: 201, json: created });
      } else if (request.method() === "DELETE" && pathname === "/api/months/3") {
        rows = rows.filter((row) => row.id !== 3);
        await route.fulfill({ status: 204, body: "" });
      } else {
        await route.fulfill({
          status: 404,
          json: {
            error: { code: "fixture_missing", message: "Synthetic route missing", details: [] },
          },
        });
      }
    },
  );
  return calls;
}

for (const viewport of [
  { name: "desktop", width: 1366, height: 900 },
  { name: "390px", width: 390, height: 844 },
]) {
  test(`native months ${viewport.name}: clone, refresh, delete and keyboard`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const calls = await installMonthsApi(page);
    await page.goto("/v2/data/months?month=2");
    await expect(page.getByRole("heading", { level: 1, name: "Отчётные месяцы" })).toBeVisible();
    await expect(page.getByText("Выбран", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: testInfo.outputPath(`${viewport.name}-months.png`),
      fullPage: true,
    });

    await page.getByRole("button", { name: "Создать следующий месяц" }).click();
    const form = page.getByRole("region", { name: "Копирование месяца" });
    await expect(form.getByText(/Источник:/)).toContainText("Июнь 2030");
    await expect(form.getByRole("combobox", { name: "Целевой месяц" })).toHaveValue("7");
    const copy = form.getByRole("button", { name: "Копировать данные" });
    await copy.focus();
    await expect(copy).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/month=3/);
    await expect(
      page.getByRole("status").filter({ hasText: "подтверждён обновлённым списком" }),
    ).toBeVisible();
    expect(calls.filter((call) => call === "POST /api/months/2/clone")).toHaveLength(1);

    await page.reload();
    await expect(page.getByText("Выбран", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Удалить черновик" }).first().click();
    await expect(page.getByRole("alertdialog")).toContainText("Июль 2030");
    await page.getByRole("alertdialog").getByRole("button", { name: "Удалить черновик" }).click();
    await expect(page).not.toHaveURL(/month=3/);
    await expect(
      page.getByRole("status").filter({ hasText: "Черновик Июль 2030 удалён" }),
    ).toBeVisible();
    expect(calls.filter((call) => call === "DELETE /api/months/3")).toHaveLength(1);

    await page.goto("/v2/data/months?month=999");
    await expect(page.getByText(/Запрошенный месяц не найден/)).toBeVisible();
    await page.goBack();
    await expect(page.getByRole("heading", { level: 1, name: "Отчётные месяцы" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
  });
}
