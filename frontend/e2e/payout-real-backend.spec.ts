import { expect, test } from "@playwright/test";

for (const width of [1366, 390]) {
  test(`synthetic real-backend payout journey ${width}px`, async ({ page, request }, testInfo) => {
    const monthId = width === 1366 ? 1 : 2;
    const positionId = width === 1366 ? 1 : 5;
    await page.setViewportSize({ width, height: 900 });
    const posts: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST") posts.push(request.url());
    });
    await page.goto(
      `/v2/data/payouts?month=${monthId}&from=monthly-close-v2&step=future_payouts&monthId=${monthId}`,
    );
    await expect(page.getByText("Объединённый календарь выплат")).toBeVisible();
    expect(posts).toEqual([]);
    await expect(page.getByLabel("PDF отчёта Alfa")).toHaveCount(0);
    await page.getByRole("button", { name: "Проверить все позиции T-Invest" }).click();
    await expect(page.getByText(/Возможный ручной дубль/)).toBeVisible();
    await expect(page.locator(`#payout-group-${positionId}`)).toBeHidden();
    await expect(page.locator(`#payout-group-${positionId + 1}`)).toBeHidden();
    await page.getByRole("button", { name: "Развернуть всё" }).click();
    await page.getByLabel("Решение для дубля 1").selectOption("count_manual");
    await page.getByLabel("Ручная запись для дубля 1").selectOption(String(monthId));
    await page.getByRole("button", { name: "Выбрать доступные" }).click();
    await expect(page.getByText("Выбрано событий: 3")).toBeVisible();
    await page.getByRole("button", { name: "Свернуть всё" }).click();
    await expect(page.getByText(/Возможный ручной дубль/)).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`collapsed-${width}.png`), fullPage: true });
    const apply = page.getByRole("button", { name: "Применить выбранные", exact: true });
    await apply.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("alertdialog")).toBeVisible();
    await page.keyboard.press("Escape");
    expect(posts.filter((url) => url.endsWith("/payout-apply"))).toHaveLength(0);
    await apply.focus();
    await page.keyboard.press("Enter");
    const confirm = page.getByRole("button", { name: "Подтвердить выбор (2 групп)" });
    await confirm.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText(/Подтверждено: 2 из 2/)).toBeVisible();
    expect(posts.filter((url) => url.endsWith("/payout-apply"))).toHaveLength(2);
    await page.screenshot({ path: testInfo.outputPath(`confirmed-${width}.png`), fullPage: true });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
    ).toBe(true);
    const actual = await request.get(`/api/investment-flows?month_id=${monthId}`);
    expect(await actual.json()).toEqual([]);
    const manual = await request.get(`/api/expected-flows?month_id=${monthId}&forecast_version=v1`);
    const rows = await manual.json();
    expect(rows).toHaveLength(1);
    expect(rows[0].expected_net_amount.amount).toBe("999.00");
    expect(rows[0].is_confirmed).toBe(false);
    await page.reload();
    await expect(page.getByText("Объединённый календарь выплат")).toBeVisible();
    expect(posts.filter((url) => url.endsWith("/payout-apply"))).toHaveLength(2);
    await page.getByRole("button", { name: "Проверить все позиции T-Invest" }).click();
    await expect(page.getByText(/ALREADY_PRESENT/).first()).toBeVisible();
    await expect(page.getByText("Выбрано событий: 0")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Применить выбранные", exact: true }),
    ).toBeDisabled();
    await expect(page.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
      "href",
      `/v2/close?month=${monthId}&step=future_payouts`,
    );
  });
}
