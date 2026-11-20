import { expect, test } from "@playwright/test";

test("reserve saves a category budget, reads the calendar, and returns to the selected month", async ({
  page,
}) => {
  await page.goto("/v2/spending?month=2026-10");
  await page.getByRole("link", { name: "Подушка", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Подушка безопасности" })).toBeVisible();
  await page.getByLabel("С", { exact: true }).fill("2027-01-01");
  await page.getByLabel("До", { exact: true }).fill("2027-06-30");
  await page.getByRole("checkbox", { name: "Продукты", exact: true }).check();
  await page.getByRole("textbox", { name: "Оценка · Продукты" }).fill("38000");
  await page.getByRole("button", { name: "Сохранить план" }).click();
  await expect(page.getByRole("status").filter({ hasText: "План сохранён" })).toBeVisible();
  const goal = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: "Цель до 30.06.2027" }) });
  await expect(goal).toContainText(/228\s000/);
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Оценка · Продукты" })).toHaveValue("38000");
  await expect(goal).toContainText(/228\s000/);
  await page.getByRole("link", { name: "Операции", exact: true }).click();
  await expect(page).toHaveURL(/\/v2\/spending\?month=2026-10$/);
});

test("reserve opens a possible rent payment and updates the budget after confirmation", async ({
  request,
  page,
}) => {
  const name = "Учебная аренда";
  const category = "Тестовое жильё";
  const ledger = async (month: string) => {
    const response = await request.get("/api/spending/operations", { params: { month } });
    expect(response.ok()).toBe(true);
    return (await response.json()).items[0];
  };
  for (const [month, last] of [
    ["10", "31"],
    ["11", "30"],
  ]) {
    const date = `01.${month}.2024`;
    const file = {
      name: `Statement ${date} - ${last}.${month}.2024.csv`,
      mimeType: "text/csv",
      buffer: Buffer.from(
        [
          "operationDate,transactionDate,accountName,accountNumber,cardName,cardNumber,merchant,amount,currency,status,category,mcc,type,comment,bonusValue,bonusTitle",
          [
            date,
            date,
            "Тестовый счёт",
            "SYNTHETIC-RENT",
            "",
            "",
            name,
            "30000",
            "RUR",
            "Выполнен",
            category,
            "",
            "Списание",
            "",
            "",
            "",
          ].join(","),
        ].join("\n"),
      ),
    };
    const multipart = { month: `2024-${month}`, source: "alfa_csv", file };
    const preview = await request.post("/api/spending/uploads/preview", { multipart });
    expect(preview.ok()).toBe(true);
    const { preview_token } = await preview.json();
    const applied = await request.post("/api/spending/uploads/apply", {
      multipart: { ...multipart, preview_token },
    });
    expect(applied.ok()).toBe(true);
  }
  const anchor = await ledger("2024-10");
  const url = `/api/spending/payment-rules/alfa/${anchor.id}?month=2024-10`;
  const schedule = {
    note: "",
    mandatory_override: true,
    repeat: true,
    period_months: 1,
    next_due: "2024-11-01",
    amount: "30000",
  };
  const token = (await (await request.get(url)).json()).token;
  const saved = await request.put(url, { data: { ...schedule, token } });
  expect(saved.ok()).toBe(true);
  const path = "/api/spending/reserve";
  const original = await (await request.get(path)).json();
  try {
    const configured = await request.put(path, {
      data: {
        expected_revision: original.revision,
        plan: {
          start: "2025-01-01",
          end: "2025-06-30",
          sources: [],
          categories: [{ id: anchor.category_id, estimate: null }],
          months: ["2024-11"],
        },
      },
    });
    expect(configured.ok()).toBe(true);
    await page.goto("/v2/spending/reserve?month=2024-11");
    const goal = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "Цель до 30.06.2025" }) });
    await expect(goal).toContainText("недостаточно данных");
    const action = goal.getByRole("button", { name: `Открыть покупку «${name}»` });
    await action.click();
    const card = page.getByRole("dialog", { name: "Карточка покупки" });
    await expect(card.getByLabel("Существующий график")).toHaveValue(
      String((await saved.json()).rule.id),
    );
    await card.getByRole("button", { name: "Уже оплачено по этому графику" }).click();
    await expect(card.getByRole("status")).toHaveText("Сохранено");
    await card.getByRole("button", { name: "Закрыть" }).click();
    await expect(action).toHaveCount(0);
    await expect(goal).toContainText(/180\s000/);
    await page.reload();
    await expect(goal).toContainText(/180\s000/);
    expect((await ledger("2024-11")).amount.amount).toBe("30000.00");
  } finally {
    const currentCard = await (await request.get(url)).json();
    const stopped = await request.put(url, {
      data: {
        ...schedule,
        token: currentCard.token,
        repeat: false,
        period_months: null,
        next_due: null,
        amount: null,
      },
    });
    expect(stopped.ok()).toBe(true);
    const { revision } = await (await request.get(path)).json();
    const restored = await request.put(path, {
      data: { expected_revision: revision, plan: original.plan },
    });
    expect(restored.ok()).toBe(true);
  }
});
