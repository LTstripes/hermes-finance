import { expect, test } from "@playwright/test";

test("synthetic real-backend native Close: edit, reread, report, reopen and restore", async ({
  page,
  request,
}, info) => {
  const workflowPath = "/api/months/1/close-workflow";
  let workflowReads = 0;
  let expenseWrites = 0;
  page.on("request", (sent) => {
    if (sent.url().endsWith(workflowPath)) workflowReads += 1;
    if (sent.method() === "POST" && sent.url().includes("/api/expenses")) expenseWrites += 1;
  });

  const initial = await (await request.get(workflowPath)).json();
  expect(initial.contract_version).toBe("monthly_close_workflow_v1");
  expect(initial.month).toMatchObject({ id: 1, status: "draft" });
  expect(initial.readiness.can_close).toBe(true);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/v2/close?month=1&step=final_review_close");
  await expect(page.getByRole("heading", { name: /Итоги.*2031/ })).toBeVisible();
  const budget = page.getByRole("link", { name: "Бюджет", exact: true });
  await expect(budget).toHaveAttribute(
    "href",
    "/v2/data/months/1?section=budget&from=monthly-close-v2&step=final_review_close&monthId=1",
  );
  await budget.click();
  await expect(page.getByRole("heading", { name: "Редактор месяца" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Вернуться к закрытию" })).toHaveAttribute(
    "href",
    "/v2/close?month=1&step=final_review_close",
  );

  await page.getByLabel("Категория расхода", { exact: true }).fill("Синтетический расход");
  await page.getByLabel("Сумма расхода", { exact: true }).fill("123.45");
  await page.getByRole("button", { name: "Добавить расход", exact: true }).click();
  await expect(page.getByText("Расход сохранён и подтверждён.")).toBeVisible();
  expect(expenseWrites).toBe(1);
  const afterSave = await (await request.get(workflowPath)).json();
  expect(
    afterSave.final_review.manual_review_cards.find(
      (card: { id: string }) => card.id === "income_budget",
    ).summary.expense_row_count,
  ).toBe(1);

  const readsBeforeReturn = workflowReads;
  await page.getByRole("link", { name: "Вернуться к закрытию" }).click();
  await expect(page).toHaveURL(/\/v2\/close\?month=1&step=final_review_close$/);
  await expect(page.getByRole("heading", { name: /Итоги.*2031/ })).toBeVisible();
  await expect.poll(() => workflowReads).toBeGreaterThan(readsBeforeReturn);
  await expect(page.getByTestId("final-review-card-income_budget")).toContainText("Есть данные");

  // An unconfirmed edit stays out of the authoritative read model.
  await page.getByRole("link", { name: "Бюджет", exact: true }).click();
  await page.getByLabel("Категория расхода", { exact: true }).fill("Несохранённое");
  await page.getByLabel("Сумма расхода", { exact: true }).fill("9.99");
  await page.getByRole("link", { name: "Вернуться к закрытию" }).click();
  await page.getByRole("button", { name: "Остаться", exact: true }).click();
  await expect(page.getByLabel("Категория расхода", { exact: true })).toHaveValue("Несохранённое");
  await page.getByRole("link", { name: "Вернуться к закрытию" }).click();
  await page.getByRole("button", { name: "Перейти без сохранения" }).click();
  await expect(page).toHaveURL(/\/v2\/close\?month=1&step=final_review_close$/);
  expect(expenseWrites).toBe(1);

  await page.getByRole("link", { name: "Бюджет", exact: true }).click();
  await page.route("**/api/expenses", (route) =>
    route.request().method() === "POST" ? route.abort() : route.continue(),
  );
  await page.getByLabel("Категория расхода", { exact: true }).fill("Неуспешная запись");
  await page.getByLabel("Сумма расхода", { exact: true }).fill("19.99");
  await page.getByRole("button", { name: "Добавить расход", exact: true }).click();
  await expect(page.getByText("Расход сохранён и подтверждён.")).toHaveCount(0);
  expect(
    (await (await request.get(workflowPath)).json()).final_review.manual_review_cards.find(
      (card: { id: string }) => card.id === "income_budget",
    ).summary.expense_row_count,
  ).toBe(1);
  await page.unroute("**/api/expenses");
  await page.getByRole("link", { name: "Вернуться к закрытию" }).click();
  await page.getByRole("button", { name: "Перейти без сохранения" }).click();
  await expect(page).toHaveURL(/\/v2\/close\?month=1&step=final_review_close$/);

  await page.route(`**${workflowPath}`, async (route) => {
    const response = await route.fetch();
    const stale = await response.json();
    stale.final_review.month_header.id = 99;
    await route.fulfill({ response, json: stale });
  });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Состояние месяца не подтверждено" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Закрыть месяц" })).toHaveCount(0);
  await page.unroute(`**${workflowPath}`);
  await page.reload();

  await page.getByRole("button", { name: "Закрыть месяц" }).click();
  await expect(page.getByRole("alertdialog", { name: "Закрыть месяц?" })).toBeVisible();
  await page.keyboard.press("Escape");
  expect((await (await request.get("/api/months/1")).json()).status).toBe("draft");
  await page.getByRole("button", { name: "Закрыть месяц" }).click();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Месяц зафиксирован" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Итоги.*2031/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Изменить" })).toHaveCount(0);
  expect((await (await request.get("/api/months/1")).json()).status).toBe("closed");
  await page.screenshot({ path: info.outputPath("closed-desktop.png"), fullPage: true });

  // A later synthetic CLOSED report makes this month an actual archive target.
  const laterResponse = await request.post("/api/months", {
    data: { year: 2031, month: 6, snapshot_date: "2031-06-30" },
  });
  expect(laterResponse.status()).toBe(201);
  const later = await laterResponse.json();
  expect((await request.post(`/api/months/${later.id}/close`)).status()).toBe(200);
  await page.goto("/v2/reports/1");
  await expect(
    page.getByRole("heading", { name: "Исторический отчёт", exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("report-net")).toBeVisible();
  await expect(page.getByRole("link", { name: "Изменить", exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page).toHaveURL(/\/v2\/reports\/1$/);
  await expect(page.getByTestId("report-net")).toBeVisible();
  await page.screenshot({ path: info.outputPath("archive-desktop.png"), fullPage: true });

  await page.goto("/v2/close?month=1&step=next_month_outlook");
  await expect(page.getByRole("link", { name: "Открыть денежную лестницу" })).toHaveAttribute(
    "href",
    "/v2/data/payouts?month=1&from=monthly-close-v2&step=next_month_outlook&monthId=1",
  );
  await expect(page.getByRole("link", { name: "Создать следующий месяц" })).toHaveAttribute(
    "href",
    "/v2/data/months?month=1&from=monthly-close-v2&step=next_month_outlook&monthId=1",
  );
  await page.getByRole("link", { name: "Создать следующий месяц" }).click();
  await expect(
    page.getByRole("link", { name: "Вернуться к закрытию исходного месяца" }),
  ).toHaveAttribute("href", "/v2/close?month=1&step=next_month_outlook");
  await page.getByRole("link", { name: "Вернуться к закрытию исходного месяца" }).click();
  await expect(page).toHaveURL(/\/v2\/close\?month=1&step=next_month_outlook$/);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/v2/close?month=1&step=final_review_close");
  await expect(page.getByRole("heading", { name: "Месяц зафиксирован" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Итоги.*2031/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  await page.screenshot({ path: info.outputPath("closed-390.png"), fullPage: true });
  await page.getByRole("button", { name: "Открыть месяц заново" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alertdialog", { name: "Открыть месяц заново?" })).toBeVisible();
  await page.keyboard.press("Escape");
  expect((await (await request.get("/api/months/1")).json()).status).toBe("closed");
  await page.getByRole("button", { name: "Открыть месяц заново" }).click();
  await page.getByRole("button", { name: "Открыть заново" }).click();
  await expect(page.getByText("Черновик", { exact: true })).toBeVisible();
  expect((await (await request.get("/api/months/1")).json()).status).toBe("draft");

  const backup = await (await request.post("/api/backups")).json();
  expect(backup.id).toBeTruthy();
  expect((await request.delete("/api/months/1")).status()).toBe(204);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Месяц не найден" })).toBeVisible();
  expect(
    (
      await (
        await request.post(`/api/backups/${backup.id}/restore`, {
          data: { confirm: true },
        })
      ).json()
    ).restored_backup.id,
  ).toBe(backup.id);
  await page.reload();
  await expect(page.getByRole("heading", { name: /Итоги.*2031/ })).toBeVisible();
  expect((await (await request.get(workflowPath)).json()).month.status).toBe("draft");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );

  await page.getByRole("link", { name: "Бюджет", exact: true }).click();
  await page.goBack();
  await expect(page).toHaveURL(/\/v2\/close\?month=1&step=final_review_close$/);
  await page.goto("/v2/close?month=999&step=final_review_close");
  await expect(page.getByRole("heading", { name: "Месяц не найден" })).toBeVisible();
  await page.goto("/v2/close?month=1&month=1&step=final_review_close");
  await expect(page.getByRole("heading", { name: "Некорректный месяц" })).toBeVisible();
});

test("historical months stay exact through reopen, edit, direct review, quotes and another period", async ({
  page,
  request,
}, info) => {
  async function create(year: number, month: number, snapshot_date: string) {
    const response = await request.post("/api/months", {
      data: { year, month, snapshot_date, source: "manual" },
    });
    expect(response.ok()).toBe(true);
    return (await response.json()).id as number;
  }
  const old = await create(2034, 5, "2034-05-31");
  test.setTimeout(60_000);
  const other = await create(2035, 5, "2035-05-31");
  const latestClosed = await create(2036, 5, "2036-05-31");
  const newestDraft = await create(2037, 5, "2037-05-31");
  for (const id of [old, other, latestClosed])
    expect((await request.post(`/api/months/${id}/close`)).ok()).toBe(true);

  let quoteRequests = 0;
  let closePosts = 0;
  page.on("request", (sent) => {
    if (sent.url().includes("quote-preview")) quoteRequests += 1;
    if (sent.method() === "POST" && sent.url().endsWith(`/api/months/${old}/close`))
      closePosts += 1;
  });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/v2/data/months");
    const oldRow = page
      .getByRole("listitem")
      .filter({ has: page.getByText(/Май.*2034/, { exact: true }) });
    await oldRow.getByRole("link", { name: "Открыть для редактирования", exact: true }).click();
    await expect(
      page.getByRole("alertdialog", { name: "Открыть месяц для редактирования?" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    expect((await (await request.get(`/api/months/${old}`)).json()).status).toBe("closed");
    await page.getByRole("button", { name: "Открыть для редактирования", exact: true }).click();
    await page.getByRole("button", { name: "Открыть месяц", exact: true }).click();
    await expect(
      page.getByText("Месяц открыт для редактирования. Данные перечитаны."),
    ).toBeVisible();
    await page
      .getByLabel("Дата снимка", { exact: true })
      .fill(width === 1440 ? "2034-05-30" : "2034-05-31");
    await page.getByRole("link", { name: "Проверить и закрыть", exact: true }).click();
    await page.getByRole("button", { name: "Остаться", exact: true }).click();
    await page.getByRole("button", { name: "Сохранить общие данные" }).click();
    await expect(page.getByText("Общие данные сохранены и подтверждены.")).toBeVisible();
    await page.getByRole("link", { name: "Проверить и закрыть", exact: true }).click();
    await expect(page).toHaveURL(`/v2/close?month=${old}&step=final_review_close`);
    await expect(page.locator("#v2-close-current-step")).toBeFocused();
    await expect(page.getByRole("button", { name: "Закрыть месяц", exact: true })).toBeInViewport();
    expect(closePosts).toBe(width === 1440 ? 0 : 1);
    await page.screenshot({
      path: info.outputPath(`historical-review-${width}.png`),
      fullPage: true,
    });

    // Quotes are a focused handoff; only its explicit button requests the provider.
    await page.goto(`/v2/close?month=${old}&step=market_quotes`);
    await page.getByRole("link", { name: "Открыть котировки", exact: true }).click();
    const quotes = page.getByRole("button", { name: "Обновить котировки", exact: true });
    await expect(quotes).toBeFocused();
    await expect(quotes).toBeInViewport();
    expect(quoteRequests).toBe(0);
    await page.getByRole("link", { name: "Вернуться к закрытию", exact: true }).click();
    await expect(page).toHaveURL(`/v2/close?month=${old}&step=market_quotes`);
    await page.goto(`/v2/data/months?month=${old}`);
    const reopened = page
      .getByRole("listitem")
      .filter({ has: page.getByText(/Май.*2034/, { exact: true }) });
    await reopened.getByRole("link", { name: "Проверить и закрыть" }).click();
    await page.getByRole("button", { name: "Закрыть месяц", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("alertdialog", { name: "Закрыть месяц?" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    expect((await (await request.get(`/api/months/${old}`)).json()).status).toBe("draft");
    await page.getByRole("button", { name: "Закрыть месяц", exact: true }).click();
    await page.getByRole("button", { name: "Закрыть", exact: true }).click();
    await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible();
    expect((await (await request.get(`/api/months/${old}`)).json()).status).toBe("closed");
    expect((await (await request.get(`/api/months/${newestDraft}`)).json()).status).toBe("draft");
    await page.getByRole("link", { name: "Выбрать другой отчётный месяц" }).click();
    const otherRow = page
      .getByRole("listitem")
      .filter({ has: page.getByText(/Май.*2035/, { exact: true }) });
    await otherRow.getByRole("link", { name: "Посмотреть отчёт", exact: true }).click();
    await expect(page).toHaveURL(`/v2/reports/${other}`);
    await page.goto("/v2");
    await expect(page.getByTestId("v2-report-context")).toContainText(/2036/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
  }
});

test("a second tab closing a historical month cancels the pending Close without another write", async ({
  page,
  request,
}) => {
  const response = await request.post("/api/months", {
    data: { year: 2038, month: 5, snapshot_date: "2038-05-31", source: "manual" },
  });
  expect(response.ok()).toBe(true);
  const month = await response.json();
  let posts = 0;
  page.on("request", (sent) => {
    if (sent.method() === "POST" && sent.url().endsWith(`/api/months/${month.id}/close`))
      posts += 1;
  });
  await page.goto(`/v2/close?month=${month.id}&step=final_review_close`);
  await page.getByRole("button", { name: "Закрыть месяц", exact: true }).click();
  await expect(page.getByRole("alertdialog", { name: "Закрыть месяц?" })).toBeVisible();
  expect((await request.post(`/api/months/${month.id}/close`)).ok()).toBe(true);
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible();
  expect(posts).toBe(0);
  expect((await (await request.get(`/api/months/${month.id}`)).json()).status).toBe("closed");
});

test("settings has one sidebar entry and diagnostics deep links keep selection, focus and keyboard return", async ({
  page,
}) => {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/v2/data/app?month=1#diagnostics");
    const sections = page.getByRole("navigation", { name: "Настройки и диагностика" });
    await expect(sections.getByRole("link", { name: "Диагностика", exact: true })).toHaveAttribute(
      "aria-current",
      "location",
    );
    await expect(page.locator("#diagnostics")).toBeFocused();
    await expect(page.getByRole("heading", { name: "Диагностика", exact: true })).toBeInViewport();
    const sidebar = page.getByRole("navigation", { name: "Данные и приложение" });
    await expect(sidebar.getByRole("link", { name: "Настройки", exact: true })).toHaveCount(1);
    await expect(sidebar.getByRole("link", { name: "Диагностика", exact: true })).toHaveCount(0);
    await sections.getByRole("link", { name: "Настройки", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL("/v2/data/app?month=1#settings");
    await expect(page.locator("#settings")).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
  }
});
