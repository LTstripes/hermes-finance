import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { expect, test } from "vitest";
import { may, row } from "./fixtures";
import { ReturnsMonthInstruments } from "./ReturnsMonthInstruments";

test("ten rows expand to all; exact header sorting leaves unknown results last in both directions", () => {
  const rows = Array.from({ length: 12 }, (_, index) =>
    row(
      `RU000A${String(index).padStart(6, "0")}`,
      `Учебная бумага ${index}`,
      index === 5 ? null : String(BigInt(index) * 100n),
      index === 5 ? null : "0.01259",
    ),
  );
  render(
    <MemoryRouter>
      <ReturnsMonthInstruments
        rows={rows}
        period={may}
        scope="source:SYNTH-A"
        revision={1}
        reasonCodes={[]}
        initialIsin={null}
      />
    </MemoryRouter>,
  );
  const table = screen.getByRole("table", { name: "Бумаги за период" });
  expect(within(table).getAllByRole("row")).toHaveLength(11);
  expect(within(table).queryByRole("row", { name: /Учебная бумага 5/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Показать все" }));
  expect(within(table).getAllByRole("row")).toHaveLength(13);
  expect(within(table).getAllByRole("row").at(-1)).toHaveTextContent("Учебная бумага 5");
  const sort = within(table).getByRole("button", { name: "Результат, ₽" });
  fireEvent.click(sort);
  expect(within(table).getByRole("columnheader", { name: "Результат, ₽" })).toHaveAttribute(
    "aria-sort",
    "ascending",
  );
  expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Учебная бумага 0");
  expect(within(table).getAllByRole("row").at(-1)).toHaveTextContent("Учебная бумага 5");
  fireEvent.click(sort);
  expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Учебная бумага 11");
  expect(within(table).getAllByRole("row").at(-1)).toHaveTextContent("Учебная бумага 5");
  expect(table.querySelector("details")).toBeNull();
  expect(table).not.toHaveTextContent(/ⓘ|Modified Dietz/);
});
