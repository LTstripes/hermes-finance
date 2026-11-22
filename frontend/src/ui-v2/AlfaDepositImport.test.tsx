import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import {
  previewAlfaDeposits,
  type AlfaDepositPreview,
  type AlfaDepositRow,
} from "../api/alfaDeposits";
import { AlfaDepositImport } from "./AlfaDepositImport";

vi.mock("../api/alfaDeposits", () => ({ previewAlfaDeposits: vi.fn() }));

const values = { balance: "100000.00", actual_interest_received: "0.00", annual_rate: "10.00" };
const row: AlfaDepositRow = {
  source_key: "first",
  label: "Счёт •1234",
  first_line: 2,
  count: 3,
  first_date: "2026-10-01",
  last_date: "2026-10-31",
  account_id: 2,
  mapped: true,
  snapshot_id: 5,
  current: values,
  proposed: { balance: "105000.40", actual_interest_received: "1000.40", annual_rate: null },
  difference: "5000.40",
  messages: [],
  token: "verified",
};
const view = (rows: AlfaDepositRow[]): AlfaDepositPreview => ({
  month_id: 7,
  period_start: "2026-10-01",
  period_end: "2026-10-31",
  accounts: [{ id: 2, name: "Накопления" }],
  rows,
});
function upload(name: string) {
  const bytes = new TextEncoder().encode(name);
  const file = Object.assign(new File([bytes], name + ".csv"), {
    arrayBuffer: async () => bytes.buffer,
  });
  fireEvent.change(screen.getByLabelText("Выписка Альфы (CSV)"), { target: { files: [file] } });
}
function open() {
  const onConfirm = vi.fn().mockResolvedValue(undefined);
  render(
    <AlfaDepositImport
      monthId={7}
      monthLabel="октябрь 2026"
      disabled={false}
      onConfirm={onConfirm}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Заполнить депозиты из выписки" }));
  return onConfirm;
}
beforeEach(() => vi.resetAllMocks());

test("a late response to a replaced file cannot show or authorize its proposal", async () => {
  let finishOld!: (v: AlfaDepositPreview) => void;
  vi.mocked(previewAlfaDeposits)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishOld = resolve;
        }),
    )
    .mockResolvedValueOnce(view([{ ...row, label: "Второй счёт", token: null }]));
  const onConfirm = open();
  upload("old");
  await waitFor(() => expect(previewAlfaDeposits).toHaveBeenCalledTimes(1));
  upload("new");
  await screen.findByRole("heading", { name: "Второй счёт" });
  await act(async () => finishOld(view([row])));
  expect(screen.queryByRole("heading", { name: row.label })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Подтвердить по счёту" })).toBeDisabled();
  expect(onConfirm).not.toHaveBeenCalled();
});

test("changing coverage requests a new proposal; only a confirmed row goes to apply", async () => {
  vi.mocked(previewAlfaDeposits).mockImplementation(async (request) =>
    view([{ ...row, token: request.full_month ? "complete" : null }]),
  );
  const onConfirm = open();
  upload("month");
  const apply = await screen.findByRole("button", { name: "Подтвердить по счёту" });
  expect(screen.getByLabelText("Счёт в Finance")).toBeDisabled();
  expect(apply).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: "Выписка охватывает весь месяц" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Подтвердить по счёту" })).toBeEnabled(),
  );
  expect(onConfirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить по счёту" }));
  await screen.findByText(/Сохранено и проверено/);
  expect(onConfirm).toHaveBeenCalledExactlyOnceWith(
    { month_id: 7, csv: "month", full_month: true, bindings: {} },
    expect.objectContaining({ source_key: "first", token: "complete" }),
  );
});
