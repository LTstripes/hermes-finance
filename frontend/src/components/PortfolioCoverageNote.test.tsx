import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { PortfolioCoverageNote } from "./PortfolioCoverageNote";

it("keeps complete coverage quiet and explains partial known capital", () => {
  const complete = { status: "complete" as const, reason_codes: [], missing_account_ids: [] };
  const { rerender } = render(<PortfolioCoverageNote coverage={complete} />);
  expect(screen.queryByTestId("portfolio-coverage-note")).toBeNull();
  rerender(
    <PortfolioCoverageNote
      coverage={{
        status: "partial",
        reason_codes: ["active_account_snapshot_missing", "another_quality_reason"],
        missing_account_ids: [2],
      }}
    />,
  );
  expect(screen.getByTestId("portfolio-coverage-note")).toHaveTextContent(
    "Частично: нет снимка счёта",
  );
  expect(screen.getByTestId("portfolio-coverage-note")).not.toHaveAttribute("title");
});
