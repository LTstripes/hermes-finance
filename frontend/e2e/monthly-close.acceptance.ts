import { expect, type Page, test } from "@playwright/test";

async function tile(page: Page, name: RegExp) {
  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name })
    .click();
}
async function fullReview(page: Page) {
  const summary = page.getByText("Подробнее об итогах и проверках", { exact: true });
  await expect(summary).toBeVisible();
  if (!(await summary.evaluate((element) => element.closest("details")?.open)))
    await summary.click();
}
async function advanced(page: Page) {
  const summary = page.getByText("Дополнительные интеграции и проверки", { exact: true });
  await expect(summary).toBeVisible();
  if (!(await summary.evaluate((element) => element.closest("details")?.open)))
    await summary.click();
}
test.beforeEach(async ({ page }) => {
  page.on("dialog", (dialog) =>
    dialog.type() === "beforeunload" ? dialog.accept() : dialog.dismiss(),
  );
});

test("intentional empty UI: Clone, zero, guards, stale consent, lost ACK and GET-only Back/Reload", async ({
  page,
  request,
}, info) => {
  const source = await (
    await request.post("/api/months", {
      data: { year: 2035, month: 1, snapshot_date: "2035-01-31" },
    })
  ).json();
  expect(
    (
      await request.post("/api/expenses", {
        data: {
          reporting_month_id: source.id,
          category: "Synthetic recurring",
          expense_type: "mandatory",
          is_recurring: true,
          amount: { amount: "123.45", currency: "RUB" },
        },
      })
    ).status(),
  ).toBe(201);
  const clonedResponse = await request.post(`/api/months/${source.id}/clone`, {
    data: { year: 2035, month: 2, snapshot_date: "2035-02-28" },
  });
  expect(clonedResponse.status()).toBe(201);
  const cloned = await clonedResponse.json();
  const path = `/v2/close?month=${cloned.id}&step=final_review_close`;
  const readinessPath = `/api/months/${cloned.id}/close-readiness`;
  const commandPath = `/api/months/${cloned.id}/close-intentionally-empty`;
  let posts = 0;
  page.on("request", (sent) => {
    if (sent.method() === "POST" && sent.url().endsWith(commandPath)) posts++;
  });
  const readiness = await (await request.get(readinessPath)).json();
  expect(readiness.can_close).toBe(false);
  expect(readiness.intentional_empty_close.eligible).toBe(true);
  expect((await request.post(`/api/months/${cloned.id}/close`)).status()).toBe(422);
  await page.goto(path);
  const start = page.getByRole("button", { name: "Закрыть намеренно пустой период…" });
  await start.click();
  const dialog = page.getByRole("alertdialog", { name: "Закрыть намеренно пустой период?" });
  await expect(dialog).toContainText(`ID ${cloned.id}`);
  await expect(dialog).toContainText("28.02.2035");
  const confirm = page.getByRole("button", { name: "Подтвердить пустой Close" });
  await expect(confirm).toBeDisabled();
  await page.getByLabel("Причина пустого периода").fill("Synthetic intentionally unobserved month");
  await expect(confirm).toBeDisabled();
  await page
    .getByRole("checkbox", { name: "Подтверждаю точный период и намеренное отсутствие фактов" })
    .check();
  await page.screenshot({ path: info.outputPath("empty-confirm-desktop.png"), fullPage: true });
  await page.keyboard.press("Escape");
  expect(posts).toBe(0);

  // A real header revision after consent prevents dispatch, even with the same calendar month.
  await start.click();
  await page.getByLabel("Причина пустого периода").fill("Stale consent");
  await page.getByRole("checkbox", { name: /Подтверждаю точный период/ }).check();
  expect(
    (
      await request.patch(`/api/months/${cloned.id}`, { data: { snapshot_date: "2035-02-27" } })
    ).ok(),
  ).toBe(true);
  await confirm.click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(/Снимок 27\.02\.2035/).first()).toBeVisible();
  expect(posts).toBe(0);
  await page.reload();

  // A committed POST loses its ACK and initial GET; recovery remains GET-only after Back/Reload.
  await start.click();
  await page.getByLabel("Причина пустого периода").fill("Synthetic empty Close with lost ACK");
  await page.getByRole("checkbox", { name: /Подтверждаю точный период/ }).check();
  await page.route(`**${commandPath}`, async (route) => {
    await route.fetch();
    await route.abort();
  });
  const receiptPattern = `**/api/months/${cloned.id}/intentional-empty-close-receipts/*`;
  await page.route(receiptPattern, (route) => route.abort());
  await confirm.click();
  await expect(page.getByRole("button", { name: "Проверить результат закрытия" })).toBeEnabled();
  expect(posts).toBe(1);
  expect((await (await request.get(`/api/months/${cloned.id}`)).json()).status).toBe("closed");
  await page.getByRole("link", { name: "Отчётные месяцы →", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toContainText("Сохранение ещё не подтверждено");
  await page.getByRole("button", { name: "Вернуться к форме", exact: true }).click();
  await page.goBack();
  await expect(page.getByRole("alertdialog")).toContainText("Сохранение ещё не подтверждено");
  await page.getByRole("button", { name: "Вернуться к форме", exact: true }).click();
  await expect(page.getByRole("button", { name: "Проверить результат закрытия" })).toBeEnabled();
  await page.reload();
  await expect(page.getByRole("button", { name: "Проверить результат закрытия" })).toBeEnabled();
  expect(posts).toBe(1);
  await page.unroute(receiptPattern);
  await page.getByRole("button", { name: "Проверить результат закрытия" }).click();
  await expect(page.getByText(/Закрытие пустого периода подтверждено квитанцией/)).toBeVisible();
  expect(posts).toBe(1);
  await page.screenshot({ path: info.outputPath("empty-recovered-desktop.png"), fullPage: true });

  // Fresh explicit zero in another real Clone is an actual fact; ordinary Close becomes valid.
  const zero = await (
    await request.post(`/api/months/${source.id}/clone`, {
      data: { year: 2035, month: 3, snapshot_date: "2035-03-31" },
    })
  ).json();
  const expenses = await (await request.get(`/api/expenses?month_id=${zero.id}`)).json();
  expect(
    (
      await request.patch(`/api/expenses/${expenses[0].id}`, {
        data: { amount: { amount: "0.00", currency: "RUB" } },
      })
    ).ok(),
  ).toBe(true);
  const zeroReady = await (await request.get(`/api/months/${zero.id}/close-readiness`)).json();
  expect(zeroReady.can_close).toBe(true);
  await page.goto(`/v2/close?month=${zero.id}&step=final_review_close`);
  await expect(page.getByRole("button", { name: "Закрыть месяц", exact: true })).toBeEnabled();
  await expect(start).toHaveCount(0);
  expect((await request.post(`/api/months/${zero.id}/close`)).status()).toBe(200);
});

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
  expect(initial.readiness.can_close).toBe(false);
  expect(initial.readiness.reason_codes).toContain("empty_manual_month");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/v2/close?month=1&step=final_review_close");
  await expect(page.getByRole("group", { name: "Итоги месяца" })).toBeVisible();
  await tile(page, /Расходы и план/);
  await expect(page.getByRole("region", { name: "Рабочая область: Расходы и план" })).toBeVisible();
  await page.getByLabel("Категория расхода", { exact: true }).fill("Синтетический расход");
  await page.getByLabel("Сумма расхода", { exact: true }).fill("123.45");
  await page.getByRole("button", { name: "Добавить расход", exact: true }).click();
  await expect(page.getByText("Сохранено", { exact: true })).toBeVisible();
  expect(expenseWrites).toBe(1);
  const afterSave = await (await request.get(workflowPath)).json();
  expect(afterSave.readiness.can_close).toBe(true);
  expect(
    afterSave.final_review.manual_review_cards.find(
      (card: { id: string }) => card.id === "income_budget",
    ).summary.expense_row_count,
  ).toBe(1);

  const readsBeforeReturn = workflowReads;
  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name: /Закрыть месяц/ })
    .click();
  await expect(page).toHaveURL(/\/v2\/close\?.*panel=close/);
  await expect(page.getByRole("group", { name: "Итоги месяца" })).toBeVisible();
  await expect.poll(() => workflowReads).toBeGreaterThan(readsBeforeReturn);
  await fullReview(page);
  await expect(page.getByTestId("final-review-card-income_budget")).toContainText("Есть данные");

  // An unconfirmed edit stays out of the authoritative read model.
  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name: /Расходы и план/ })
    .click();
  await page.getByLabel("Категория расхода", { exact: true }).fill("Несохранённое");
  await page.getByLabel("Сумма расхода", { exact: true }).fill("9.99");
  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name: /Закрыть месяц/ })
    .click();
  await page.getByRole("button", { name: "Остаться", exact: true }).click();
  await expect(page.getByLabel("Категория расхода", { exact: true })).toHaveValue("Несохранённое");
  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name: /Закрыть месяц/ })
    .click();
  await page.getByRole("button", { name: "Перейти без сохранения" }).click();
  await expect(page).toHaveURL(/\/v2\/close\?.*panel=close/);
  expect(expenseWrites).toBe(1);

  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name: /Расходы и план/ })
    .click();
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
  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name: /Закрыть месяц/ })
    .click();
  await page.getByRole("button", { name: "Перейти без сохранения" }).click();
  await expect(page).toHaveURL(/\/v2\/close\?.*panel=close/);

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
  await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("group", { name: "Итоги месяца" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Изменить" })).toHaveCount(0);
  expect((await (await request.get("/api/months/1")).json()).status).toBe("closed");
  await page.screenshot({ path: info.outputPath("closed-desktop.png"), fullPage: true });

  // A later synthetic CLOSED report makes this month an actual archive target.
  const laterResponse = await request.post("/api/months", {
    data: { year: 2031, month: 6, snapshot_date: "2031-06-30" },
  });
  expect(laterResponse.status()).toBe(201);
  const later = await laterResponse.json();
  const laterReadiness = await (
    await request.get(`/api/months/${later.id}/close-readiness`)
  ).json();
  expect(laterReadiness.can_close).toBe(false);
  const { eligible, ...laterIdentity } = laterReadiness.intentional_empty_close;
  expect(eligible).toBe(true);
  expect(
    (
      await request.post(`/api/months/${later.id}/close-intentionally-empty`, {
        data: {
          ...laterIdentity,
          request_id: "synthetic-later-history",
          reason: "Intentionally empty synthetic archive fixture",
        },
      })
    ).status(),
  ).toBe(200);
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
  await advanced(page);
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

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/v2/close?month=1&step=final_review_close");
  await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("group", { name: "Итоги месяца" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  await page.screenshot({ path: info.outputPath("closed-return-desktop.png"), fullPage: true });
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
  await expect(page.getByRole("group", { name: "Итоги месяца" })).toBeVisible();
  expect((await (await request.get(workflowPath)).json()).month.status).toBe("draft");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );

  await page
    .getByRole("navigation", { name: "Разделы месяца" })
    .getByRole("link", { name: /Расходы и план/ })
    .click();
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
    const id = (await response.json()).id as number;
    // History/navigation cases use a genuine explicitly saved zero observation.
    // Empty-month confirmation UI is a separate consumer task.
    expect(
      (
        await request.post("/api/cash-balances", {
          data: {
            reporting_month_id: id,
            name: "Synthetic recorded cash",
            amount: { amount: "0.00", currency: "RUB" },
          },
        })
      ).ok(),
    ).toBe(true);
    return id;
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
  for (const width of [1440]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/v2/data/months");
    const oldRow = page
      .getByRole("listitem")
      .filter({ has: page.getByText(/Май.*2034/, { exact: true }) });
    await oldRow.getByRole("link", { name: "Открыть месяц", exact: true }).click();
    await expect(page).toHaveURL(`/v2/close?month=${old}`);
    await tile(page, /Снимок и общие данные/);
    await expect(page.getByLabel("Дата снимка")).toBeDisabled();

    await page.getByRole("button", { name: "Открыть для редактирования", exact: true }).click();
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
    await tile(page, /Закрыть месяц/);
    await page.getByRole("button", { name: "Остаться", exact: true }).click();
    await page.getByRole("button", { name: "Сохранить общие данные" }).click();
    await expect(page.getByText("Сохранено", { exact: true })).toBeVisible();
    await tile(page, /Закрыть месяц/);
    await expect(page).toHaveURL(/panel=close/);
    await expect(page.getByRole("group", { name: "Итоги месяца" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Закрыть месяц", exact: true })).toBeInViewport();
    expect(closePosts).toBe(width === 1440 ? 0 : 1);
    await page.screenshot({
      path: info.outputPath(`historical-review-${width}.png`),
      fullPage: true,
    });

    // Quotes are a focused handoff; only its explicit button requests the provider.
    await page.goto(`/v2/close?month=${old}&step=market_quotes`);
    await advanced(page);
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
    const reopenedPrimary = reopened.getByRole("link", {
      name: "Открыть месяц",
      exact: true,
    });
    await expect(reopenedPrimary).toBeVisible();
    const reopenedContrast = await reopenedPrimary.evaluate((element) => {
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
      return (light + 0.05) / (dark + 0.05);
    });
    expect(reopenedContrast).toBeGreaterThanOrEqual(4.5);
    await reopenedPrimary.click();
    const panelWorkflow = page.waitForResponse((response) => {
      const referer = response.request().headers().referer;
      return (
        response.request().method() === "GET" &&
        new URL(response.url()).pathname === `/api/months/${old}/close-workflow` &&
        !!referer &&
        new URL(referer).searchParams.get("panel") === "close"
      );
    });
    await tile(page, /Закрыть месяц/);
    expect((await panelWorkflow).ok()).toBe(true);
    const closeButton = page.getByRole("button", { name: "Закрыть месяц", exact: true });
    await expect(closeButton).toBeEnabled();
    await closeButton.focus();
    await expect(closeButton).toBeFocused();
    await closeButton.press("Enter");
    await expect(page.getByRole("alertdialog", { name: "Закрыть месяц?" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    expect((await (await request.get(`/api/months/${old}`)).json()).status).toBe("draft");
    await page.getByRole("button", { name: "Закрыть месяц", exact: true }).click();
    await page.getByRole("button", { name: "Закрыть", exact: true }).click();
    await expect(page.getByText("Месяц закрыт", { exact: true }).first()).toBeVisible();
    expect((await (await request.get(`/api/months/${old}`)).json()).status).toBe("closed");
    expect((await (await request.get(`/api/months/${newestDraft}`)).json()).status).toBe("draft");
    await page.getByRole("link", { name: "Отчётные месяцы →", exact: true }).click();
    const otherRow = page
      .getByRole("listitem")
      .filter({ has: page.getByText(/Май.*2035/, { exact: true }) });
    await otherRow.getByRole("button", { name: /Действия месяца/ }).click();
    await page.getByRole("menuitem", { name: "Посмотреть отчёт", exact: true }).click();
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
  expect(
    (
      await request.post("/api/cash-balances", {
        data: {
          reporting_month_id: month.id,
          name: "Synthetic recorded cash",
          amount: { amount: "0.00", currency: "RUB" },
        },
      })
    ).ok(),
  ).toBe(true);
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
}, info) => {
  let settingsWrites = 0;
  page.on("request", (sent) => {
    if (sent.method() === "PUT" && sent.url().endsWith("/api/settings")) settingsWrites += 1;
  });
  for (const width of [1440]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/v2/data/app?month=1#diagnostics");
    const sections = page.getByRole("navigation", { name: "Настройки и диагностика" });
    await expect(sections.getByRole("link", { name: "Диагностика", exact: true })).toHaveAttribute(
      "aria-current",
      "location",
    );
    // Slow settings reads must not move the selected diagnostics heading away.
    await expect(page.locator("#v2-data-app-locale")).toHaveValue(/.+/);
    await expect(page.locator("#diagnostics")).toBeFocused();
    await expect(page.getByRole("heading", { name: "Диагностика", exact: true })).toBeInViewport();
    await page.screenshot({ path: info.outputPath(`settings-diagnostics-${width}.png`) });
    const sidebar = page.getByRole("navigation", { name: "Основная навигация" });
    await expect(sidebar.getByRole("link", { name: "Настройки", exact: true })).toHaveCount(1);
    await expect(sidebar.getByRole("link", { name: "Диагностика", exact: true })).toHaveCount(0);
    await sections.getByRole("link", { name: "Настройки", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL("/v2/data/app?month=1#settings");
    await expect(page.locator("#settings")).toBeFocused();
    const locale = page.getByLabel("Локаль", { exact: true });
    await locale.fill("en-US");
    await sections.getByRole("link", { name: "Диагностика", exact: true }).click();
    await sections.getByRole("link", { name: "Настройки", exact: true }).click();
    await expect(locale).toHaveValue("en-US");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
  }
  expect(settingsWrites).toBe(0);
});
