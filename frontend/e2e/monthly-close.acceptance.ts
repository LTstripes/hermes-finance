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
