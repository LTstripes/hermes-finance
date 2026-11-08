/// <reference types="node" />
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import { performanceAttributionUnavailableMessage } from "./performanceMessages";
import { reasonCopy, UNAVAILABLE_REASON } from "./reasonCopy";

// Read the API-owned enum vocabulary, so newly added codes fail this contract test.
const files = ["performance_availability.py", "xirr.py", "twrr.py"];
const apiCodes = [
  ...new Set(
    files.flatMap((file) => {
      const source = readFileSync(
        resolve(
          dirname(fileURLToPath(import.meta.url)),
          "../../../backend/src/hermes_finance/domain",
          file,
        ),
        "utf8",
      );
      return [
        ...source.matchAll(
          /^ {4}[A-Z][A-Z_]+ = "(not_computable_[a-z_]+|boundary_observation_conflict)"/gm,
        ),
      ].map((match) => match[1]);
    }),
  ),
];

describe("reason copy API contract", () => {
  test("covers the performance availability and solver API enums", () => {
    expect(apiCodes.length).toBeGreaterThan(0);
    for (const code of apiCodes) {
      const copy = reasonCopy(code);
      expect(copy.message, code).not.toBe(UNAVAILABLE_REASON);
      expect(copy.message, code).not.toContain(code);
      expect(copy.action, code).toBeNull();
    }
  });
  test.each(["future_valuation_flow_error", "unknown", "toString", "constructor", "__proto__", ""])(
    "uses a neutral fallback for %s",
    (code) => {
      expect(reasonCopy(code)).toEqual({ message: UNAVAILABLE_REASON, action: null });
      expect(performanceAttributionUnavailableMessage([code])).toBe(UNAVAILABLE_REASON);
    },
  );
  test("preserves known wording and chooses the screen context exactly", () => {
    expect(reasonCopy("missing_endpoint", { surface: "returns" }).message).toBe(
      "Не хватает стоимости на границе периода.",
    );
    expect(reasonCopy("missing_endpoint", { surface: "instrument" }).message).toBe(
      "Нет подтверждённой стоимости или количества на границе периода.",
    );
    expect(
      reasonCopy("not_computable_xirr_convergence_failed", { surface: "class" }).message,
    ).toContain("численное ограничение");
  });
  test("keeps month, account and instrument context without inventing it", () => {
    const copy = reasonCopy("missing_endpoint", {
      month: "январь 2030",
      account: "Учебный счёт",
      instrument: "Учебная облигация",
    });
    expect(copy.message).toContain("Месяц: январь 2030");
    expect(copy.message).toContain("Счёт: Учебный счёт");
    expect(copy.message).toContain("Инструмент: Учебная облигация");
    expect(reasonCopy("missing_endpoint").message).not.toContain("Учебный");
  });
  test("requires a supported reason and an available local action", () => {
    const actions = { instrumentMapping: { available: true, href: "/v2/data/catalogs" } };
    expect(reasonCopy("mapping_ambiguous", { actions }).action).toEqual({
      label: "Исправить",
      href: "/v2/data/catalogs",
    });
    expect(reasonCopy("mapping_ambiguous").action).toBeNull();
    expect(reasonCopy("mapping_ambiguous", { actions, closed: true }).action).toBeNull();
    expect(
      reasonCopy("mapping_ambiguous", {
        actions: { instrumentMapping: { ...actions.instrumentMapping, available: false } },
      }).action,
    ).toBeNull();
    expect(
      reasonCopy("mapping_ambiguous", {
        actions: { instrumentMapping: { available: true, href: "https://example.invalid/" } },
      }).action,
    ).toBeNull();
    expect(reasonCopy("not_computable_xirr_convergence_failed", { actions }).action).toBeNull();
    expect(reasonCopy("future_mapping_ambiguous", { actions }).action).toBeNull();
  });
});
