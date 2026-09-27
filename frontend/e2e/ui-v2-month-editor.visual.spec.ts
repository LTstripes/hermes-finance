import { expect, test, type Page } from "@playwright/test";

const closed = {
  id: 7,
  year: 2030,
  month: 4,
  status: "closed",
  snapshot_date: "2030-04-30",
  source: "manual",
};

async function installApi(page: Page) {
  let month = { ...closed };
  const calls: string[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (!path.startsWith("/api/")) {
      await route.continue();
      return;
    }
    calls.push(`${request.method()} ${path}`);
    if (path === "/api/months" && request.method() === "GET") {
      await route.fulfill({ json: [month] });
    } else if (path === "/api/months/7" && request.method() === "GET") {
      await route.fulfill({ json: month });
    } else if (path === "/api/months/7" && request.method() === "PATCH") {
      month = { ...month, ...request.postDataJSON() };
      await route.fulfill({ json: month });
    } else if (path === "/api/months/7/reopen" && request.method() === "POST") {
      month = { ...month, status: "draft" };
      await route.fulfill({ json: month });
    } else if (path === "/api/comments" && request.method() === "GET") {
      await route.fulfill({ json: [] });
    } else {
      await route.fulfill({
        status: 404,
        json: { error: { code: "not_found", message: "synthetic", details: [] } },
      });
    }
  });
  return calls;
}

test("browser Back keeps an unsaved month until the user confirms", async ({ page }) => {
  await installApi(page);
  await page.goto("/v2/data/months");
  await page.goto("/v2/data/months/7");
  await expect(page.getByLabel("Дата снимка")).toBeDisabled();
  await page.getByRole("button", { name: "Открыть для редактирования" }).click();
  await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
  await page.getByLabel("Дата снимка").fill("2030-04-29");
  page.once("dialog", (dialog) => void dialog.dismiss());
  await page.evaluate(() => window.history.back());
  await expect(page.getByLabel("Дата снимка")).toHaveValue("2030-04-29");
  await expect(page).toHaveURL(/\/v2\/data\/months\/7$/);
  page.once("dialog", (dialog) => void dialog.accept());
  await page.evaluate(() => window.history.back());
  await expect(page).toHaveURL(/\/v2\/data\/months$/);
});

test("saving removes the history guard and Back returns to the month list", async ({ page }) => {
  await installApi(page);
  await page.goto("/v2/data/months");
  await page.goto("/v2/data/months/7");
  await page.getByRole("button", { name: "Открыть для редактирования" }).click();
  await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
  await page.getByLabel("Дата снимка").fill("2030-04-29");
  await page.getByRole("button", { name: "Сохранить общие данные" }).click();
  await expect(page.getByText("Общие данные сохранены и подтверждены.")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => window.history.state?.monthEditorDirtyGuard ?? null))
    .toBeNull();
  await page.evaluate(() => window.history.back());
  await expect(page).toHaveURL(/\/v2\/data\/months$/);
});

for (const width of [1280, 390]) {
  test(`native month editor ${width}px and keyboard`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const calls = await installApi(page);
    await page.goto("/v2/data/months/7?from=monthly-close-v2&monthId=7&step=month_setup");
    await expect(page.getByRole("heading", { level: 1, name: "Редактор месяца" })).toBeVisible();
    await expect(page.getByTestId("data-month-context").getByText("Апрель 2030")).toBeVisible();
    await expect(page.getByLabel("Дата снимка")).toBeDisabled();
    await expect(page.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
      "href",
      "/v2/close?month=7&step=month_setup",
    );
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.activeElement?.tagName)).toBe("A");
    await page.getByRole("button", { name: "Открыть для редактирования" }).click();
    await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
    await expect(page.getByLabel("Дата снимка")).toBeEnabled();
    expect(calls.filter((call) => call === "GET /api/months/7").length).toBeGreaterThanOrEqual(2);
    expect(calls).toContain("POST /api/months/7/reopen");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
    await page.screenshot({
      path: testInfo.outputPath(`month-editor-${width}.png`),
      fullPage: true,
    });
  });
}
