import fs from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("synthetic desktop: real context → explicit choices → 211 RUB / 2.01% → bound JSON", async ({
  page,
  request,
}, info) => {
  test.setTimeout(60000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const raw = await (await request.get("/api/synthetic-what-if-original")).body();
  const actual = await (
    await request.get("/api/broker-statement-returns?account_id=1&request_id=synthetic-batch")
  ).json();
  expect(actual.rate_fraction).toBeNull();
  await page.goto("/v2/capital/statement-return");
  await page.getByLabel("Брокерский счёт").selectOption("1");
  await page.getByLabel("Принятая выписка").selectOption("synthetic-batch");
  const panel = page.getByRole("region", { name: "Условная оценка / сценарий" });
  await panel.getByLabel("Оригинал WHAT-IF").setInputFiles({
    name: "Брокерский 1234567 (01.09.30-30.09.30).xml",
    mimeType: "application/xml",
    buffer: raw,
  });
  const pending = page.waitForResponse((r) =>
    r.url().endsWith("/broker-statement-what-if/context"),
  );
  await panel.getByRole("button", { name: "Проверить контекст сценария" }).click();
  const context = await (await pending).json();
  expect(context.hard_blockers).toEqual([]);
  await panel.getByRole("button", { name: "Рассчитать условную оценку" }).click();
  await expect(panel.getByText("Выбери все необходимые допущения и режим графика.")).toBeVisible();
  for (const r of context.required_assumptions)
    await panel.getByLabel(r.requirement_id, { exact: true }).selectOption(r.choices[0]);
  await panel.getByLabel("Режим графика", { exact: true }).selectOption("dated");
  const evaluated = page.waitForResponse((r) =>
    r.url().endsWith("/broker-statement-what-if/evaluate"),
  );
  await panel.getByRole("button", { name: "Рассчитать условную оценку" }).click();
  const result = await (await evaluated).json();
  expect(result.scenario_result_kopecks).toBe("21100");
  await expect(panel.getByText(/2,01% · за фактический период/)).toBeVisible();
  await expect(
    panel.getByText(/Условный результат после учёта выбранных внешних движений: 211,00/),
  ).toBeVisible();
  await expect(panel.getByText(/Фактический S3: Недоступна/)).toBeVisible();
  await panel.screenshot({ path: info.outputPath("synthetic-what-if-1440.png") });
  const download = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Экспорт сценария JSON с перепроверкой" }).click();
  const path = await (await download).path();
  expect(JSON.parse(await fs.readFile(path, "utf8"))).toEqual(result);
  await panel
    .getByLabel("candidate", { exact: true })
    .selectOption("exclude_from_external_schedule");
  await expect(panel.getByText(/2,01% · за фактический период/)).toHaveCount(0);
  await expect(
    panel.getByRole("button", { name: "Экспорт сценария JSON с перепроверкой" }),
  ).toBeDisabled();
  await panel.getByLabel("Режим графика", { exact: true }).selectOption("explicit_empty");
  await panel.getByRole("button", { name: "Рассчитать условную оценку" }).click();
  await expect(panel.getByText(/12,11% · за фактический период/)).toBeVisible();
  await panel.screenshot({ path: info.outputPath("synthetic-what-if-excluded-1440.png") });
  await page.getByRole("button", { name: "Обновить результат", exact: true }).click();
  await expect(panel.getByText(/12,11% · за фактический период/)).toHaveCount(0);
  await expect(panel.getByRole("button", { name: "Проверить контекст сценария" })).toBeDisabled();
  expect(
    await (
      await request.get("/api/broker-statement-returns?account_id=1&request_id=synthetic-batch")
    ).json(),
  ).toEqual(actual);
  expect(errors).toEqual([]);
});
