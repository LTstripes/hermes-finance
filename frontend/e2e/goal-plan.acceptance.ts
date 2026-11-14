import { expect, test } from "@playwright/test";

test("capital goal plan uses explicit assumptions and preserves actual progress", async ({
  page,
}, testInfo) => {
  const writes: string[] = [];
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    if (request.url().includes("/api/") && request.method() !== "GET")
      writes.push(request.method());
    expect(request.url()).not.toContain(":8000");
  });
  await page.goto("/v2/income/goals?month=1");
  const card = page
    .getByRole("listitem")
    .filter({ has: page.getByRole("heading", { name: "Капитал для проекта" }) });
  await expect(card).toBeVisible();
  const plan = card.locator("details.goal-plan");
  await expect(plan).toHaveAttribute("open", "");
  await expect(card.getByText("Прогноз даты пока недоступен")).toHaveCount(0);
  const progress = card.getByRole("progressbar");
  const actual = await progress.getAttribute("value");
  await expect(
    card.getByText("Введите взнос в месяц (0 — без взносов).", { exact: true }),
  ).toBeVisible();
  await expect(card.getByLabel("Доходность в год")).toHaveValue("0");
  await expect(card.getByLabel("Первый взнос")).toHaveAttribute("placeholder", "ДД.ММ.ГГГГ");
  await card.getByLabel("Взнос в месяц").fill("100 000,00");
  await card.getByLabel("Взнос в месяц").blur();
  await expect(card.getByLabel("Взнос в месяц")).toHaveValue("100 000");
  await expect(card.getByText("июнь 2032", { exact: true })).toBeVisible();
  await expect(card.getByText("+54 545 ₽ запаса", { exact: true })).toBeVisible();
  await card.getByLabel("Доходность в год").fill("15");
  const chart = card.getByRole("figure", { name: "Условная помесячная траектория капитала" });
  await expect(chart).toBeVisible();
  await expect(chart.getByText("Цель 1 500 000 ₽", { exact: true })).toBeVisible();
  await expect(chart.getByText("Достигнете", { exact: true })).toBeVisible();
  await expect(chart.getByText("Срок", { exact: true })).toBeVisible();
  await expect(chart.getByText(/Старт ·/)).toBeVisible();
  await expect(chart.getByText(/Конец ·/)).toBeVisible();
  await expect(card.getByRole("table")).not.toBeVisible();
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBe(true);
    await expect
      .poll(() =>
        chart
          .locator("svg")
          .first()
          .evaluate((svg) => svg.getBoundingClientRect().width > 150),
      )
      .toBe(true);
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo(0, 0);
    });
    expect(
      await card.locator("input").evaluateAll((inputs) =>
        inputs.every((input) => {
          const rect = input.getBoundingClientRect();
          return (
            rect.left >= 0 &&
            rect.right <= window.innerWidth &&
            input.scrollWidth <= input.clientWidth + 1
          );
        }),
      ),
    ).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`goal-plan-${width}.png`), fullPage: true });
  }
  await page.evaluate(() => {
    document.documentElement.style.zoom = "1.25";
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("goal-plan-1280-125.png"), fullPage: true });
  await plan.getByText("Подробнее", { exact: true }).click();
  await expect(card.getByRole("table")).toBeVisible();
  await card.getByLabel("Первый взнос").fill("31.02.2032");
  await expect(card.getByRole("alert")).toHaveText("Введите дату в формате ДД.ММ.ГГГГ.");
  await expect(chart).toHaveCount(0);
  await card.getByLabel("Первый взнос").fill("29.02.2032");
  await expect(chart).toBeVisible();
  await expect(progress).toHaveAttribute("value", actual ?? "");
  expect(writes).toEqual([]);
  expect(pageErrors).toEqual([]);
});
