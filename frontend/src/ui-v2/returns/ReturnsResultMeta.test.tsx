import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReturnsResultMeta } from "./ReturnsResultMeta";

describe("ReturnsResultMeta", () => {
  it("keeps each explicitly linked account and its own dates", () => {
    render(
      (["109", "662"] as const).map((id, index) => (
        <ReturnsResultMeta
          key={id}
          period={{
            start: index ? "2030-04-30" : "2030-03-31",
            end: index ? "2030-05-31" : "2030-04-30",
          }}
          valuationDate={index ? "2030-05-31" : "2030-04-30"}
          accountLink={{
            source_account_id: id,
            financial_account_id: index + 1,
            account_type: index ? "brokerage" : "iis",
            label: (index ? "Брокерский " : "ИИС ") + id,
            status: "linked",
            reason_codes: [],
          }}
        />
      )),
    );
    expect(screen.getByText("ИИС 109")).toBeInTheDocument();
    expect(screen.getByText("Брокерский 662")).toBeInTheDocument();
    expect(screen.getByText("31.03.2030 — 30.04.2030 · Оценка на 30.04.2030")).toBeInTheDocument();
    expect(screen.getByText("30.04.2030 — 31.05.2030 · Оценка на 31.05.2030")).toBeInTheDocument();
    expect(screen.queryByText(/связь со счётом не подтверждена/)).not.toBeInTheDocument();
  });
  it("shows an unlinked account and unknown valuation honestly", () => {
    render(
      <ReturnsResultMeta
        period={null}
        valuationDate={null}
        accountLink={{
          source_account_id: "109",
          financial_account_id: null,
          account_type: null,
          label: "109",
          status: "unlinked",
          reason_codes: ["source_account_mapping_missing"],
        }}
      />,
    );
    expect(screen.getByText("Выписка 109: связь со счётом не подтверждена")).toBeInTheDocument();
    expect(
      screen.getByText("Период не установлен · Дата оценки не подтверждена"),
    ).toBeInTheDocument();
  });
});
