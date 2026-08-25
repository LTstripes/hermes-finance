import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyStatement,
  inspectStatement,
  prepareStatement,
  type StatementPreparation,
} from "../api/statementImport";
import type { Account, Instrument } from "../api/types";
import { StatementImportPanel } from "./StatementImportPanel";

vi.mock("../api/statementImport", () => ({
  applyStatement: vi.fn(),
  inspectStatement: vi.fn(),
  prepareStatement: vi.fn(),
}));

const account = { id: 1, name: "Основной счёт" } as Account;
const instrument = { id: 10, name: "Синтетическая облигация", isin: "RU000SYNTH01" } as Instrument;
const file = new File(["synthetic pdf"], "statement.pdf", { type: "application/pdf" });

const inspectResult = {
  document_sha256: "sha-1",
  status: "applicable",
  rows: [
    {
      status: "matched",
      provider_account_ref: "broker-1",
      isin: "RU000SYNTH01",
      event_kind: "coupon",
      record_date: "2026-08-01",
      event_date: "2026-08-01",
      reason: null,
    },
  ],
  warnings: [],
  reason: null,
};

const preparation: StatementPreparation = {
  provider: "alfa_pdf",
  document_sha256: "sha-1",
  status: "applicable",
  warnings: [],
  reason: null,
  rows: [
    {
      status: "matched",
      duplicate_class: "duplicate",
      provider_account_ref: "broker-1",
      expected_hermes_account_id: 1,
      expected_hermes_instrument_id: 10,
      natural_identity: "duplicate-1",
      material_fingerprint: "fp-duplicate",
      expected_candidate_ids: [],
      candidates: [],
      isin: "RU000SYNTH01",
      event_date: "2026-08-01",
      reason: null,
    },
    {
      status: "matched",
      duplicate_class: "correction",
      provider_account_ref: "broker-1",
      expected_hermes_account_id: 1,
      expected_hermes_instrument_id: 10,
      natural_identity: "correction-1",
      material_fingerprint: "fp-correction",
      expected_candidate_ids: [],
      candidates: [],
      isin: "RU000SYNTH01",
      event_date: "2026-08-02",
      reason: null,
    },
    {
      status: "matched",
      duplicate_class: null,
      provider_account_ref: "broker-1",
      expected_hermes_account_id: 1,
      expected_hermes_instrument_id: 10,
      natural_identity: "new-1",
      material_fingerprint: "fp-new",
      expected_candidate_ids: [],
      candidates: [],
      isin: "RU000SYNTH01",
      event_date: "2026-08-03",
      reason: null,
    },
  ],
};

const candidatePreparation: StatementPreparation = {
  ...preparation,
  rows: [
    ...preparation.rows,
    {
      status: "matched",
      duplicate_class: null,
      provider_account_ref: "broker-1",
      expected_hermes_account_id: 1,
      expected_hermes_instrument_id: 10,
      natural_identity: "candidate-1",
      material_fingerprint: "fp-candidate",
      expected_candidate_ids: [42, 43],
      candidates: [
        {
          investment_cash_flow_id: 42,
          reporting_month_id: 6,
          account_id: 1,
          instrument_id: 10,
          flow_type: "coupon",
          event_date: "2026-08-03",
          gross_amount_kopecks: 1000,
          tax_amount_kopecks: 0,
          commission_amount_kopecks: 0,
          net_amount_kopecks: 1000,
          currency: "RUB",
          source: "manual",
        },
      ],
      isin: "RU000SYNTH01",
      event_date: "2026-08-03",
      reason: null,
    },
  ],
};

describe("StatementImportPanel explicit row decisions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(inspectStatement).mockResolvedValue(inspectResult);
    vi.mocked(prepareStatement).mockResolvedValue(preparation);
    vi.mocked(applyStatement).mockResolvedValue({
      success: true,
      selected_count: 2,
      items: [
        {
          action: "revise",
          natural_identity: "correction-1",
          applied_statement_event_id: 11,
          investment_cash_flow_id: 12,
          material_fingerprint: "fp-correction",
          revision_id: 13,
        },
      ],
      error_code: null,
      message: null,
    });
  });

  async function prepareReport() {
    const user = userEvent.setup();
    render(<StatementImportPanel accounts={[account]} instruments={[instrument]} />);
    await user.upload(screen.getByLabelText("PDF отчёта Alfa"), file);
    await user.click(screen.getByRole("button", { name: "Проверить отчёт" }));
    await screen.findByText("broker-1");
    await user.selectOptions(screen.getByLabelText("Alfa-счёт broker-1"), "1");
    await user.click(screen.getByRole("button", { name: "Подготовить к импорту" }));
    await screen.findByText("Уже импортировано");
    return user;
  }

  it("blocks a mixed set when a checked CORRECTION lacks revise", async () => {
    const user = await prepareReport();
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes[0]).toBeDisabled();
    expect(checkboxes[1]).not.toBeChecked();
    expect(checkboxes[2]).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Применить выбранные строки" })).toBeDisabled();

    await user.click(checkboxes[2]);
    await user.click(checkboxes[1]);
    expect(screen.getByRole("button", { name: "Применить выбранные строки" })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("Решение correction 2"), "revise");
    expect(screen.getByRole("button", { name: "Применить выбранные строки" })).toBeEnabled();
  });

  it("requires confirmation, sends the exact File and preserves apply actions", async () => {
    const user = await prepareReport();
    const checkboxes = screen.getAllByRole("checkbox");
    await user.click(checkboxes[1]);
    await user.selectOptions(screen.getByLabelText("Решение correction 2"), "revise");
    await user.click(checkboxes[2]);
    await user.click(screen.getByRole("button", { name: "Применить выбранные строки" }));
    await user.click(screen.getByRole("button", { name: "Подтвердить и применить" }));
    await waitFor(() => expect(applyStatement).toHaveBeenCalledTimes(1));
    expect(vi.mocked(applyStatement).mock.calls[0]?.[0]).toBe(file);
    expect(vi.mocked(applyStatement).mock.calls[0]?.[2]).toHaveLength(2);
    expect(screen.getByText("Создано уточнение записи")).toBeInTheDocument();
    expect(screen.getByText("Итог импорта")).toBeInTheDocument();
    expect(screen.queryByText("Результат apply")).toBeNull();
    expect(screen.queryByText("revise: correction-1")).toBeNull();
    expect(screen.queryByText("Уже импортировано")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Импортировано строк: 2");
  });

  it("blocks a mixed set when a checked candidate row lacks an explicit action", async () => {
    vi.mocked(prepareStatement).mockResolvedValueOnce(candidatePreparation);
    const user = await prepareReport();
    const checkboxes = screen.getAllByRole("checkbox");
    await user.click(checkboxes[2]);
    await user.click(checkboxes[3]);
    expect(screen.getByRole("button", { name: "Применить выбранные строки" })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText("Решение кандидата 4"), "link_existing");
    await user.selectOptions(screen.getByLabelText("Кандидат для ссылки 4"), "42");
    expect(screen.getByRole("button", { name: "Применить выбранные строки" })).toBeEnabled();
  });

  it("sends the exact checked set and link_existing candidate identifiers", async () => {
    vi.mocked(prepareStatement).mockResolvedValueOnce(candidatePreparation);
    const user = await prepareReport();
    const checkboxes = screen.getAllByRole("checkbox");
    await user.click(checkboxes[2]);
    await user.click(checkboxes[3]);
    await user.selectOptions(screen.getByLabelText("Решение кандидата 4"), "link_existing");
    await user.selectOptions(screen.getByLabelText("Кандидат для ссылки 4"), "42");
    await user.click(screen.getByRole("button", { name: "Применить выбранные строки" }));
    await user.click(screen.getByRole("button", { name: "Подтвердить и применить" }));

    await waitFor(() => expect(applyStatement).toHaveBeenCalledTimes(1));
    const selections = vi.mocked(applyStatement).mock.calls[0]?.[2] as Array<{
      natural_identity: string;
      existing_cash_flow_id?: number;
      expected_candidate_ids: number[];
    }>;
    expect(selections).toHaveLength(2);
    expect(selections[0]).toMatchObject({
      natural_identity: "new-1",
      expected_candidate_ids: [],
    });
    expect(selections[1]).toMatchObject({
      natural_identity: "candidate-1",
      existing_cash_flow_id: 42,
      expected_candidate_ids: [42, 43],
    });
  });

  it("uses owner-facing report errors and spaced import sections", async () => {
    vi.mocked(inspectStatement).mockResolvedValueOnce({
      ...inspectResult,
      status: "malformed",
      rows: [],
      reason: "missing_required_schema",
    });
    const user = userEvent.setup();
    const { container } = render(
      <StatementImportPanel accounts={[account]} instruments={[instrument]} />,
    );
    await user.upload(screen.getByLabelText("PDF отчёта Alfa"), file);
    await user.click(screen.getByRole("button", { name: "Проверить отчёт" }));

    expect(
      await screen.findByText(
        "Hermes не смог распознать структуру отчёта Alfa. Данные не были импортированы.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("missing_required_schema")).toBeNull();
    expect(screen.queryByText("mapping")).toBeNull();
    expect(container.querySelector(".statement-import__summary")).not.toBeNull();
    expect(container.querySelector(".statement-import__mapping")).not.toBeNull();
  });
});
