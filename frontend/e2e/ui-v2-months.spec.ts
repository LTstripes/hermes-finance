import { expect, type Page, test } from "@playwright/test";

const startingMonths = [
  { id: 2, year: 2030, month: 6, status: "draft", snapshot_date: "2030-06-30", source: "manual" },
  { id: 1, year: 2030, month: 5, status: "closed", snapshot_date: "2030-05-31", source: "manual" },
];

async function primaryContrast(locator: import("@playwright/test").Locator) {
  return locator.evaluate((element) => {
    const parseChannels = (value: string) => value.match(/[\d.]+/g)?.map(Number) ?? [];
    const luminance = (channels: number[]) => {
      const [r, g, b] = channels.slice(0, 3).map((channel) => {
        const c = channel / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const styles = getComputedStyle(element);
    const foreground = luminance(parseChannels(styles.color));
    const background = luminance(parseChannels(styles.backgroundColor));
    const [light, dark] =
      foreground > background ? [foreground, background] : [background, foreground];
    return {
      backgroundColor: styles.backgroundColor,
      color: styles.color,
      ratio: (light + 0.05) / (dark + 0.05),
    };
  });
}

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
    await expect(page.getByRole("link", { name: "Открыть месяц", exact: true })).toHaveCount(2);
    const primaryClose = page.getByRole("link", { name: "Проверить и закрыть", exact: true });
    await expect(primaryClose).toBeVisible();
    const normal = await primaryContrast(primaryClose);
    expect(normal.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
    expect(normal.ratio).toBeGreaterThanOrEqual(4.5);
    await primaryClose.focus();
    const focused = await primaryContrast(primaryClose);
    expect(focused.ratio).toBeGreaterThanOrEqual(4.5);
    await expect(page.getByRole("link", { name: "Открыть в «Мои финансы»" })).toHaveAttribute(
      "href",
      "/v2",
    );
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
