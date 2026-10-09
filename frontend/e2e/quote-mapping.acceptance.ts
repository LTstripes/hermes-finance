import { expect, test } from "@playwright/test";

const SYNTHETIC_UID = "11111111-1111-1111-1111-111111111111";

test("synthetic real-backend: missing mapping, verified mapping, explicit new preview and readback", async ({
  page,
  request,
}, info) => {
  let previewCalls = 0;
  page.on("request", (sent) => {
    if (sent.url().includes("quote-preview")) previewCalls += 1;
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/v2/data/months/1?section=positions#month-quotes");
  await expect(page.getByRole("heading", { name: "Позиции", exact: true })).toBeVisible();
  const before = await (await request.get("/api/positions?month_id=1")).json();
  expect(before).toHaveLength(1);
  expect(before[0].price_source).toBe("manual");
  expect(previewCalls).toBe(0);

  // Explicit preview only; an unmapped instrument never reaches the provider.
  await page.getByRole("button", { name: "Обновить котировки" }).click();
  const previewTable = page.getByRole("table", { name: "Предпросмотр котировок" });
  const row = previewTable.getByRole("row").filter({ hasText: "Synthetic unmapped" });
  await expect(row).toContainText("Внешний источник не настроен");
  await expect(
    row.getByRole("button", { name: "Сопоставить инструмент Synthetic unmapped" }),
  ).toBeVisible();
  expect(previewCalls).toBe(1);
  expect(await (await request.get("/api/instruments/1/market-mapping")).json()).toMatchObject({
    state: "unmapped",
    identity: null,
  });

  // Cancel is a no-op for both the mapping and the existing preview.
  const dialog = page.getByRole("dialog", { name: "Источник котировки" });
  await row.getByRole("button", { name: "Сопоставить инструмент Synthetic unmapped" }).click();
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(row).toContainText("Внешний источник не настроен");
  expect(await (await request.get("/api/instruments/1/market-mapping")).json()).toMatchObject({
    state: "unmapped",
  });

  // A rejected identity fails closed and leaves the saved mapping untouched.
  await row.getByRole("button", { name: "Сопоставить инструмент Synthetic unmapped" }).click();
  await dialog.getByLabel("Идентификатор инструмента T-Invest").fill("not-found-uid");
  await dialog.getByRole("button", { name: "Сохранить источник" }).click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(row).toContainText("Внешний источник не настроен");
  expect(await (await request.get("/api/instruments/1/market-mapping")).json()).toMatchObject({
    state: "unmapped",
    identity: null,
  });

  // The existing validated flow saves a verified identity.
  await row.getByRole("button", { name: "Сопоставить инструмент Synthetic unmapped" }).click();
  await dialog.getByLabel("Идентификатор инструмента T-Invest").fill(SYNTHETIC_UID);
  await dialog.getByRole("button", { name: "Сохранить источник" }).click();
  await expect(dialog.getByTestId("accepted-mapping-identity")).toContainText(
    `T-Invest · ${SYNTHETIC_UID}`,
  );
  const saved = await (await request.get("/api/instruments/1/market-mapping")).json();
  expect(saved).toMatchObject({
    state: "mapped",
    identity: { provider: "t_invest", provider_instrument_id: SYNTHETIC_UID },
  });

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  // The confirmed mapping invalidates the preview: no stale apply is possible.
  await expect(page.getByText(/Сопоставление сохранено/)).toBeVisible();
  await expect(page.getByRole("table", { name: "Предпросмотр котировок" })).toHaveCount(0);
  expect(await (await request.get("/api/positions?month_id=1")).json()).toEqual(before);

  // Explicit new preview uses the saved mapping; applying stays a separate action.
  await page.getByRole("button", { name: "Обновить котировки" }).click();
  await expect(page.getByRole("table", { name: "Предпросмотр котировок" })).toBeVisible();
  await expect(page.getByRole("cell", { name: /123,45/ })).toBeVisible();
  expect(await (await request.get("/api/positions?month_id=1")).json()).toEqual(before);
  await page.getByRole("button", { name: "Применить выбранные" }).click();
  await expect(page.getByText(/Котировки применены: 1/)).toBeVisible();
  const after = await (await request.get("/api/positions?month_id=1")).json();
  expect(after[0].price_source).toBe("t_invest");
  expect(after[0].market_price_per_unit.amount).toBe("123.45");

  // Desktop and keyboard keep the quote panel bounded and operable.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/v2/data/months/1?section=positions#month-quotes");
  const refresh = page.getByRole("button", { name: "Обновить котировки" });
  await refresh.focus();
  await expect(refresh).toBeFocused();
  await refresh.click();
  await expect(page.getByRole("table", { name: "Предпросмотр котировок" })).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
  await page.screenshot({ path: info.outputPath("quote-mapping-desktop.png"), fullPage: true });
});
