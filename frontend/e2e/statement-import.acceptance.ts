import os from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

const SYNTHETIC_PDF = path.join(os.tmpdir(), "hermes-statement-synthetic", "statement.pdf");
const FLOWS = "/api/investment-flows?month_id=1";
const APPLY = "/api/statement-import/apply";

test("synthetic real-backend statement import: no mutation until confirm, apply, reload", async ({
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
  expect(await (await request.get(FLOWS)).json()).toEqual([]);

  // The write/import tool mounts only for one explicit valid month.
  await page.goto("/v2/data/payouts");
  await expect(page.getByRole("heading", { name: "Месяц не выбран" })).toBeVisible();
  await expect(page.getByLabel("PDF отчёта Alfa")).toHaveCount(0);
  expect(posts).toEqual([]);

  await page.goto("/v2/data/payouts?month=1");
  await expect(page.locator("#statement-import")).toBeVisible();
  await expect(page.getByLabel("Отчётный месяц")).toHaveValue("1");
  expect(posts).toEqual([]);

  // Selecting a document alone performs no request and no write.
  await page.setInputFiles("#statement-file", SYNTHETIC_PDF);
  expect(posts).toEqual([]);
  expect(await (await request.get(FLOWS)).json()).toEqual([]);

  // Inspect and prepare are read-only against the real backend.
  await page.getByRole("button", { name: "Проверить отчёт" }).click();
  await expect(page.getByRole("cell", { name: "SYN-DEPO-001", exact: true })).toBeVisible();
  await page.getByLabel("Alfa-счёт SYN-DEPO-001").selectOption(accountId);
  await page.getByRole("button", { name: "Подготовить к импорту" }).click();
  await expect(page.getByText("Новая строка")).toBeVisible();
  expect(posts).toEqual(["/api/statement-import/inspect", "/api/statement-import/prepare"]);
  expect(await (await request.get(FLOWS)).json()).toEqual([]);
  await page.getByRole("checkbox", { name: "Выбрать строку 1" }).check();

  // Cancel closes the confirmation without any write.
  await page.getByRole("button", { name: "Применить выбранные строки" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await page.screenshot({ path: info.outputPath("desktop-confirm.png"), fullPage: true });
  await dialog.getByRole("button", { name: "Отмена", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(posts.filter((call) => call === APPLY)).toEqual([]);
  expect(await (await request.get(FLOWS)).json()).toEqual([]);

  // Keyboard confirmation is the only write, and the readback must prove it.
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
  const flows = await (await request.get(FLOWS)).json();
  expect(flows).toHaveLength(1);
  expect(flows[0].reporting_month_id).toBe(1);
  await page.screenshot({ path: info.outputPath("desktop-applied.png"), fullPage: true });

  // Reload: the persisted row is proved again and never created twice.
  await page.reload();
  await expect(page.locator("#statement-import")).toBeVisible();
  await page.setInputFiles("#statement-file", SYNTHETIC_PDF);
  await page.getByRole("button", { name: "Проверить отчёт" }).click();
  await page.getByLabel("Alfa-счёт SYN-DEPO-001").selectOption(accountId);
  await page.getByRole("button", { name: "Подготовить к импорту" }).click();
  await expect(page.getByText("Уже импортировано")).toBeVisible();
  await expect(page.getByRole("button", { name: "Применить выбранные строки" })).toBeDisabled();
  expect(posts.filter((call) => call === APPLY)).toHaveLength(1);
  expect(await (await request.get(FLOWS)).json()).toHaveLength(1);

  // 390px keeps the whole prepared statement inside the viewport.
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
  await page.screenshot({ path: info.outputPath("mobile-statement.png"), fullPage: true });

  // CLOSED stays inspectable while apply is fail-closed.
  const close = await request.post("/api/months/1/close");
  expect(close.ok(), await close.text()).toBe(true);
  await page.reload();
  await expect(
    page.getByText(/Проверка PDF доступна, но применение выплат заблокировано/),
  ).toBeVisible();
  await page.setInputFiles("#statement-file", SYNTHETIC_PDF);
  await page.getByRole("button", { name: "Проверить отчёт" }).click();
  await expect(page.getByRole("cell", { name: "SYN-DEPO-001", exact: true })).toBeVisible();
  expect(posts.filter((call) => call === APPLY)).toHaveLength(1);
  expect(pageErrors).toEqual([]);
});
