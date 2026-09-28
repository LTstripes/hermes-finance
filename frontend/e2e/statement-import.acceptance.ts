import os from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

const SYNTHETIC_NATIVE_PDF = path.join(os.tmpdir(), "hermes-statement-synthetic", "statement.pdf");
const SYNTHETIC_LEGACY_PDF = path.join(
  os.tmpdir(),
  "hermes-statement-synthetic",
  "statement-legacy.pdf",
);
const APPLY = "/api/statement-import/apply";

function flowsUrl(monthId: number): string {
  return `/api/investment-flows?month_id=${monthId}`;
}

test("synthetic real-backend spanning statement: native month scope, legacy stays unconstrained", async ({
  page,
  request,
}, info) => {
  const posts: string[] = [];
  const pageErrors: string[] = [];
  page.on("request", (sent) => {
    if (sent.method() === "POST") posts.push(new URL(sent.url()).pathname);
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.setViewportSize({ width: 1440, height: 900 });
  const accounts = await (await request.get("/api/accounts")).json();
  const accountId = String(accounts[0].id);
  const months = await (await request.get("/api/months")).json();
  const january = months.find(
    (row: { year: number; month: number }) => row.year === 2026 && row.month === 1,
  );
  const february = months.find(
    (row: { year: number; month: number }) => row.year === 2026 && row.month === 2,
  );
  if (!january || !february) throw new Error("synthetic reporting months are missing");
  const readFlows = async (monthId: number) =>
    (await (await request.get(flowsUrl(monthId))).json()) as unknown[];

  expect(await readFlows(january.id)).toEqual([]);
  expect(await readFlows(february.id)).toEqual([]);

  // The write/import tool mounts only for one explicit valid month.
  await page.goto("/v2/data/payouts");
  await expect(page.getByRole("heading", { name: "Месяц не выбран" })).toBeVisible();
  await expect(page.getByLabel("PDF отчёта Alfa")).toHaveCount(0);
  expect(posts).toEqual([]);

  // Native workspace pinned to January 2026 with a January + February PDF.
  await page.goto(`/v2/data/payouts?month=${january.id}`);
  await expect(page.locator("#statement-import")).toBeVisible();
  await expect(page.getByLabel("Отчётный месяц")).toHaveValue(String(january.id));
  expect(posts).toEqual([]);

  await page.setInputFiles("#statement-file", SYNTHETIC_NATIVE_PDF);
  expect(posts).toEqual([]);

  await page.getByRole("button", { name: "Проверить отчёт" }).click();
  await expect(page.getByRole("cell", { name: "SYN-DEPO-001", exact: true }).first()).toBeVisible();
  await page.getByLabel("Alfa-счёт SYN-DEPO-001").selectOption(accountId);
  await page.getByRole("button", { name: "Подготовить к импорту" }).click();
  await expect(page.getByText("Новая строка").first()).toBeVisible();
  expect(posts).toEqual(["/api/statement-import/inspect", "/api/statement-import/prepare"]);
  expect(await readFlows(january.id)).toEqual([]);
  expect(await readFlows(february.id)).toEqual([]);

  // B1: the February row stays visible but is non-selectable/non-applicable.
  const checkboxes = page.getByRole("checkbox");
  await expect(checkboxes).toHaveCount(2);
  await expect(checkboxes.nth(0)).toBeEnabled();
  await expect(checkboxes.nth(1)).toBeDisabled();
  await expect(page.getByText(/строка относится к другому отчётному месяцу/)).toBeVisible();
  await page.getByRole("button", { name: "Выбрать все готовые" }).click();
  await expect(checkboxes.nth(0)).toBeChecked();
  await expect(checkboxes.nth(1)).not.toBeChecked();

  // Cancel closes the confirmation without any write.
  await page.getByRole("button", { name: "Применить выбранные строки" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await page.screenshot({ path: info.outputPath("desktop-confirm.png"), fullPage: true });
  await dialog.getByRole("button", { name: "Отмена", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(posts.filter((call) => call === APPLY)).toEqual([]);
  expect(await readFlows(january.id)).toEqual([]);

  // One keyboard confirm writes exactly one January row and nothing in February.
  const applyButton = page.getByRole("button", { name: "Применить выбранные строки" });
  await applyButton.focus();
  await expect(applyButton).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  const confirmButton = dialog.getByRole("button", { name: "Подтвердить и применить" });
  await confirmButton.focus();
  await expect(confirmButton).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page.getByText(/Импортировано строк: 1/)).toBeVisible();
  expect(posts.filter((call) => call === APPLY)).toHaveLength(1);
  const januaryFlows = await readFlows(january.id);
  expect(januaryFlows).toHaveLength(1);
  expect(januaryFlows[0].reporting_month_id).toBe(january.id);
  expect(await readFlows(february.id)).toEqual([]);
  await page.screenshot({ path: info.outputPath("desktop-applied.png"), fullPage: true });

  // Reload: persistence is proved again and neither row can be written twice.
  await page.reload();
  await expect(page.locator("#statement-import")).toBeVisible();
  await page.setInputFiles("#statement-file", SYNTHETIC_NATIVE_PDF);
  await page.getByRole("button", { name: "Проверить отчёт" }).click();
  await page.getByLabel("Alfa-счёт SYN-DEPO-001").selectOption(accountId);
  await page.getByRole("button", { name: "Подготовить к импорту" }).click();
  await expect(page.getByText("Уже импортировано")).toBeVisible();
  await expect(checkboxes.nth(1)).toBeDisabled();
  await expect(page.getByRole("button", { name: "Применить выбранные строки" })).toBeDisabled();
  expect(posts.filter((call) => call === APPLY)).toHaveLength(1);
  expect(await readFlows(january.id)).toHaveLength(1);
  expect(await readFlows(february.id)).toEqual([]);

  // 390px keeps the whole prepared statement inside the viewport.
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
  await page.screenshot({ path: info.outputPath("mobile-statement.png"), fullPage: true });

  // Legacy panel: no target period at all, so a second spanning document may
  // write both reporting months even though legacy shows the newest month.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/payouts");
  await expect(page.getByRole("heading", { level: 1, name: "Автовыплаты" })).toBeVisible();
  await expect(page.getByLabel("Отчётный месяц")).toHaveValue(String(february.id));
  await expect(page.locator("#statement-import")).toBeVisible();
  await page.setInputFiles("#statement-file", SYNTHETIC_LEGACY_PDF);
  await page.getByRole("button", { name: "Проверить отчёт" }).click();
  await expect(page.getByRole("cell", { name: "SYN-DEPO-001", exact: true }).first()).toBeVisible();
  await page.getByLabel("Alfa-счёт SYN-DEPO-001").selectOption(accountId);
  await page.getByRole("button", { name: "Подготовить к импорту" }).click();
  await expect(page.getByText("Новая строка").first()).toBeVisible();

  const legacyCheckboxes = page.getByRole("checkbox");
  await expect(legacyCheckboxes).toHaveCount(2);
  await expect(legacyCheckboxes.nth(0)).toBeEnabled();
  await expect(legacyCheckboxes.nth(1)).toBeEnabled();
  await expect(page.getByText(/строка относится к другому отчётному месяцу/)).toHaveCount(0);
  await page.getByRole("button", { name: "Выбрать все готовые" }).click();
  await expect(legacyCheckboxes.nth(0)).toBeChecked();
  await expect(legacyCheckboxes.nth(1)).toBeChecked();

  await page.getByRole("button", { name: "Применить выбранные строки" }).click();
  await page.getByRole("button", { name: "Подтвердить и применить" }).click();
  await expect(page.getByText(/Импортировано строк: 2/)).toBeVisible();
  expect(await readFlows(january.id)).toHaveLength(2);
  expect(await readFlows(february.id)).toHaveLength(1);

  // CLOSED stays inspectable while apply is fail-closed.
  const appliesBeforeClose = posts.filter((call) => call === APPLY).length;
  const close = await request.post(`/api/months/${january.id}/close`);
  expect(close.ok(), await close.text()).toBe(true);
  await page.goto(`/v2/data/payouts?month=${january.id}`);
  await expect(
    page.getByText(/Проверка PDF доступна, но применение выплат заблокировано/),
  ).toBeVisible();
  await page.setInputFiles("#statement-file", SYNTHETIC_NATIVE_PDF);
  await page.getByRole("button", { name: "Проверить отчёт" }).click();
  await expect(page.getByRole("cell", { name: "SYN-DEPO-001", exact: true }).first()).toBeVisible();
  expect(posts.filter((call) => call === APPLY)).toHaveLength(appliesBeforeClose);
  expect(pageErrors).toEqual([]);
});
