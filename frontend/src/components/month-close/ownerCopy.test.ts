import { describe, expect, it } from "vitest";
import type { CloseReadinessItem } from "../../api/types";
import { closeOwnerActionFindings, closeOwnerFindings } from "./ownerCopy";

describe("closeOwnerFindings", () => {
  it("keeps one next action per account in the ordinary review and preserves blocking severity", () => {
    const details = "Проверь подробности в разделе «Месяц → Брокерские выписки».";
    const items = [
      { message: `Synthetic broker: не разобраны разделы. ${details}`, severity: "warning" },
      {
        message: `Synthetic broker: не разобраны денежные движения. ${details}`,
        severity: "hard_blocker",
      },
      { message: `Synthetic IIS: требуется сверка. ${details}`, severity: "warning" },
      { message: "Проверь цены в позициях.", severity: "warning" },
    ];
    const result = closeOwnerActionFindings(items);
    expect(result).toHaveLength(3);
    expect(result[0]).toMatchObject({ severity: "hard_blocker" });
    expect(result[0].message).toContain("Synthetic broker: сверка выписки");
    expect(result[1].message).toContain("Synthetic IIS: сверка выписки");
    expect(items[0].message).toContain("не разобраны разделы");
    expect(closeOwnerFindings(items)).toHaveLength(4);
  });
  it("shows one line per problem without discarding different accounts or blocking severity", () => {
    const finding = (
      code: string,
      message: string,
      severity: CloseReadinessItem["severity"] = "warning",
    ): CloseReadinessItem => ({ code, message, severity, context: {} });
    const items = [
      finding("old-section", "Synthetic broker: проверь выписку"),
      finding("other-section", "Synthetic broker: проверь выписку"),
      finding("commission", "Synthetic broker: проверь комиссию"),
      finding("old-section", "Synthetic IIS: проверь выписку"),
      finding("integrity", "Synthetic broker: проверь выписку", "hard_blocker"),
      finding("context", "Synthetic broker: проверь цену", "info"),
      finding("price", "Synthetic broker: проверь цену", "warning"),
    ];
    const result = closeOwnerFindings(items);
    expect(result).toHaveLength(4);
    expect(result[0].severity).toBe("hard_blocker");
    expect(result.find((item) => item.message.includes("цену"))?.severity).toBe("warning");
    expect(items).toHaveLength(7);
  });
});
