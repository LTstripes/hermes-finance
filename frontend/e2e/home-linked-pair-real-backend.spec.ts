import { expect, test } from "@playwright/test";

// G04 owns a new synthetic database; all writes use supported public APIs.
test("Home linked pair: real backend correction, reclose and readback", async ({
  page,
  request,
}) => {
  const api = "http://127.0.0.1:8000/api";
  const money = (amount: string) => ({ amount, currency: "RUB" });
  async function write(path: string, data: unknown = {}, method = "POST", status = 201) {
    const response = await request.fetch(`${api}${path}`, { method, data });
    expect(response.status(), await response.text()).toBe(status);
    return response.json();
  }
  const account = await write("/accounts", {
    name: "Synthetic Home linked account",
    account_type: "savings",
  });
  const other = await write("/accounts", {
    name: "Synthetic alternate account",
    account_type: "cash",
  });
  const months = [];
  const debts = [];
  for (const m of [1, 2]) {
    const month = await write("/months", { year: 2091, month: m, snapshot_date: `2091-0${m}-28` });
    months.push(month);
    await write("/cash-balances", {
      reporting_month_id: month.id,
      account_id: account.id,
      name: "Synthetic cash",
      amount: money(m === 1 ? "40.00" : "10.00"),
    });
    await write("/cash-balances", {
      reporting_month_id: month.id,
      account_id: other.id,
      name: "Synthetic alternate cash",
      amount: money("0.00"),
    });
    await write("/deposits", {
      reporting_month_id: month.id,
      account_id: account.id,
      name: "Synthetic deposit",
      deposit_type: "deposit",
      balance: money(m === 1 ? "60.00" : "30.00"),
      annual_rate: "0.00",
      actual_interest_received: money("0.00"),
    });
    const debt = await write("/debts", {
      reporting_month_id: month.id,
      debt_type: "credit_card",
      name: "Synthetic endpoint card",
      current_balance: money(m === 1 ? "80.00" : "20.00"),
      include_in_liquid_capital: true,
    });
    debts.push(debt);
    if (m === 2)
      await write(`/debts/${debt.id}/linked-account`, { account_id: account.id }, "PUT", 200);
    await write(`/months/${month.id}/close`, {}, "POST", 200);
  }
  await page.goto("/v2");
  await expect(page.getByText(/Для части счетов нет явной связи/)).toBeVisible();
  await expect(page.getByTestId("v2-capital-change")).toHaveText("0 ₽");
  await write(`/months/${months[0].id}/reopen`, {}, "POST", 200);
  await write(`/debts/${debts[0].id}/linked-account`, { account_id: account.id }, "PUT", 200);
  await write(`/months/${months[0].id}/close`, {}, "POST", 200);
  await page.reload();
  const summary = page.locator("summary").filter({ hasText: "Synthetic Home linked account" });
  await expect(summary).toHaveCount(1);
  await expect(page.getByText(/Для части счетов нет явной связи/)).toHaveCount(0);
  await summary.click();
  await expect(page.getByText(/счёт 100\s*₽/)).toBeVisible();
  await expect(page.getByText(/счёт 40\s*₽/)).toBeVisible();
  await expect(page.getByTestId("v2-capital-change")).toHaveText("0 ₽");
  await write(`/months/${months[0].id}/reopen`, {}, "POST", 200);
  await write(`/debts/${debts[0].id}/linked-account`, { account_id: other.id }, "PUT", 200);
  await write(`/months/${months[0].id}/close`, {}, "POST", 200);
  await page.reload();
  await expect(summary).toHaveCount(0);
  await expect(page.getByText(/Для части счетов нет явной связи/)).toBeVisible();
  await expect(page.getByTestId("v2-capital-change")).toHaveText("0 ₽");
});
