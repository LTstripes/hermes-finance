import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { expect, test } from "vitest";
import { ReturnsDetailBody } from "./ReturnsDetail";
import { instrumentCardFixture } from "./overallFixtures";

test("clean detail displays clean values and retains original operations without legacy P&L", () => {
  const account = instrumentCardFixture().accounts[0];
  if (!account.detail || !account.clean) throw new Error("missing synthetic data");
  account.detail.contract_version = "returns_source_detail_v2";
  account.detail.clean = account.clean;
  account.detail.analysis.pnl.value = "99999999";
  account.detail.pnl.value = "1200";
  render(
    <MemoryRouter>
      <ReturnsDetailBody detail={account.detail} />
    </MemoryRouter>,
  );
  expect(screen.getByText("+12 ₽")).toBeVisible();
  expect(screen.queryByText(/999.?999,99/)).toBeNull();
  expect(screen.getByText(/Сделки и выплаты/)).toBeInTheDocument();
  expect(screen.getByText("Известные составляющие")).toBeInTheDocument();
  const position = screen.getByRole("heading", { name: /Позиция на/ }).parentElement;
  expect(position).toHaveTextContent(/Количество: .* → /);
});
