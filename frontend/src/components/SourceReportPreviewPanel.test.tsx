import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  confirmInvestmentReport,
  getInvestmentProofRequest,
  getInvestmentReports,
  previewSourceReports,
  type SourceReportPreview,
} from "../api/sourceReportPreview";
import { SourceReportPreviewPanel } from "./SourceReportPreviewPanel";

vi.mock("../api/sourceReportPreview", () => ({
  previewSourceReports: vi.fn(),
  confirmInvestmentReport: vi.fn(),
  getInvestmentProofRequest: vi.fn(),
  getInvestmentReports: vi.fn(),
}));
const preview = vi.mocked(previewSourceReports);
const xml = new File(["synthetic"], "historical.xml", { type: "application/xml" });
const metric = (value: string | null) => ({ value, status: "provisional", reason_codes: [] });
function result(): SourceReportPreview {
  return {
    contract: "xml-pdf-source-return-preview-v1",
    financial_apply_available: false,
    close_available: false,
    pdf_period: { covered_from: "2030-01-01", covered_to: "2030-09-30" },
    pdf_payout_rows: 1,
    source_accounts: ["1234567"],
    comparison: [
      {
        source_account: "1234567",
        source_sha256: "a".repeat(64),
        repeated_native_trades: 3,
        conflicting_native_trades: 1,
        new_native_trades: 2,
        repeated_money_occurrences: 5,
        unmatched_money_occurrences: 1,
      },
    ],
    intervals: [
      {
        source_account: "1234567",
        source_sha256: "a".repeat(64),
        opening_date: "2029-12-31",
        closing_date: "2030-09-30",
        period_kind: "historical_interval",
        history_from_zero: true,
        pnl: metric("900719925474099321"),
        modified_dietz: metric("0.01235"),
        xirr_period: metric("0.02"),
        xirr_annualized: metric("0.03"),
        reason_codes: [],
        instruments: [],
        account_only: [{ kind: "account_tax", amount_kopecks: "-123" }],
        unallocated_payouts: [],
        reconciliation: {
          xml_payout_occurrences: 2,
          linked_payout_occurrences: 2,
          cash_delta_kopecks: "0",
          pdf_closing_delta_kopecks: "0",
          pdf_pnl_delta_kopecks: "0",
        },
      },
    ],
  };
}
function choosePdf() {
  fireEvent.change(screen.getByLabelText("Загрузить PDF Альфы"), {
    target: { files: [new File(["synthetic"], "report.pdf", { type: "application/pdf" })] },
  });
}
function savable() {
  const value = result();
  value.persistence = {
    available: true,
    form_token: "synthetic-form-capability",
    preview_digest: "d".repeat(64),
    replacements: [],
    reason_codes: [],
  };
  return value;
}
function readback() {
  vi.mocked(getInvestmentReports).mockResolvedValue({
    reports: [
      {
        pdf_period: result().pdf_period,
        pdf_payout_rows: 1,
        proof_id: 42,
        source_account: "1234567",
        covered_from: "2030-01-01",
        covered_to: "2030-09-30",
        status: "current",
        reason_codes: [],
        interval: result().intervals[0],
        financial_authority: "none",
      },
    ],
  });
}
it("saves one proof, verifies the exact acknowledgement and derived readback", async () => {
  preview.mockResolvedValue(savable());
  readback();
  vi.mocked(confirmInvestmentReport).mockImplementation(async (form) => ({
    ...form,
    proof_ids: [42],
    current: true,
    financial_authority: "none",
  }));
  const pending = vi.fn();
  render(<SourceReportPreviewPanel xmlFiles={[xml]} onPendingChange={pending} />);
  choosePdf();
  fireEvent.click(screen.getByRole("button", { name: "Проверить XML и PDF" }));
  fireEvent.click(await screen.findByRole("button", { name: "Сохранить PDF-связи" }));
  await screen.findByText(/PDF-связи сохранены и перечитаны/);
  expect(confirmInvestmentReport).toHaveBeenCalledOnce();
  expect(getInvestmentReports).toHaveBeenCalledOnce();
  expect(sessionStorage.getItem("hermes-investment-proof-pending-v1")).toBeNull();
  expect(pending).toHaveBeenCalledWith(true);
  expect(pending).toHaveBeenLastCalledWith(false);
});
it("recovers an uncertain Save after Reload by GET, without repeating POST", async () => {
  preview.mockResolvedValue(savable());
  readback();
  vi.mocked(confirmInvestmentReport).mockRejectedValue(new Error("lost acknowledgement"));
  const mounted = render(<SourceReportPreviewPanel xmlFiles={[xml]} />);
  choosePdf();
  fireEvent.click(screen.getByRole("button", { name: "Проверить XML и PDF" }));
  fireEvent.click(await screen.findByRole("button", { name: "Сохранить PDF-связи" }));
  await screen.findByText("lost acknowledgement");
  const intent = JSON.parse(sessionStorage.getItem("hermes-investment-proof-pending-v1") ?? "null");
  expect(intent.request_id).toBeTruthy();
  vi.mocked(getInvestmentProofRequest).mockResolvedValue({
    ...intent,
    proof_ids: [42],
    current: true,
    financial_authority: "none",
  });
  mounted.unmount();
  render(<SourceReportPreviewPanel xmlFiles={[]} />);
  await screen.findByText(/PDF-связи сохранены и перечитаны/);
  expect(getInvestmentProofRequest).toHaveBeenCalledWith(intent.request_id);
  expect(confirmInvestmentReport).toHaveBeenCalledOnce();
});
it("requires explicit replacement and retains an unverified acknowledgement for recovery", async () => {
  const r = savable();
  if (!r.persistence) throw new Error("missing synthetic proof form");
  r.persistence.replacements = [
    {
      source_account: "1234567",
      proof_id: 41,
      covered_from: "2030-01-01",
      covered_to: "2030-09-30",
    },
  ];
  preview.mockResolvedValue(r);
  vi.mocked(confirmInvestmentReport).mockImplementation(async (form) => ({
    ...form,
    preview_digest: "bad",
    proof_ids: [42],
    current: true,
    financial_authority: "none",
  }));
  render(<SourceReportPreviewPanel xmlFiles={[xml]} />);
  choosePdf();
  fireEvent.click(screen.getByRole("button", { name: "Проверить XML и PDF" }));
  const save = await screen.findByRole("button", { name: "Сохранить PDF-связи" });
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/Подтверждаю замену только source-proof/));
  fireEvent.click(save);
  await screen.findByText(/Сохранение требует проверки квитанции/);
  expect(sessionStorage.getItem("hermes-investment-proof-pending-v1")).not.toBeNull();
  expect(getInvestmentReports).not.toHaveBeenCalled();
});
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
});

it("shows source restrictions and known partial amounts when complete movement returns are unavailable", async () => {
  const r = result();
  const account = r.intervals[0];
  account.pnl = metric(null);
  account.known_subtotal = metric("9000");
  account.modified_dietz = metric(null);
  account.source_advisories = ["4_Transfers_unsupported"];
  account.unresolved_movements = [
    { isin: "RU000A000000", reason: "unresolved_native_security_movement" },
  ];
  account.instruments = [
    {
      isin: "RU000A000000",
      pnl: metric(null),
      known_subtotal: metric("9000"),
      modified_dietz: metric(null),
      xirr_period: metric(null),
      xirr_annualized: metric(null),
      event_count: 2,
      reason_codes: ["unresolved_native_security_movement"],
    },
  ];
  preview.mockResolvedValue(r);
  render(<SourceReportPreviewPanel xmlFiles={[xml]} />);
  choosePdf();
  fireEvent.click(screen.getByRole("button", { name: "Проверить XML и PDF" }));
  await screen.findByText(/Дополнительные разделы исходного XML/);
  expect(screen.getByText(/Известная часть по денежным операциям/)).toHaveTextContent("90.00");
  expect(screen.getByText(/Требуют разбора движения бумаг/)).toHaveTextContent("1");
  expect(screen.getByRole("row", { name: /RU000A000000/ })).toHaveTextContent(
    "Не определеноИзвестная часть: 90.00",
  );
});

it("uses the shared XML selection and shows the entire period, exact money and distinct period/annual rates", async () => {
  preview.mockResolvedValue(result());
  render(<SourceReportPreviewPanel xmlFiles={[xml]} />);
  expect(screen.queryByLabelText("XML для совместной проверки")).not.toBeInTheDocument();
  choosePdf();
  fireEvent.click(screen.getByRole("button", { name: "Проверить XML и PDF" }));
  await screen.findByText(/Период PDF: 2030-01-01/);
  expect(screen.getByText(/Исторический период/)).toHaveTextContent("9007199254740993.21");
  expect(screen.getByText(/Исторический период/)).toHaveTextContent("1,24%");
  expect(screen.getByText(/Исторический период/)).toHaveTextContent("за период: 2,00%");
  expect(screen.getByText(/Исторический период/)).toHaveTextContent("XIRR годовых: 3,00%");
  expect(screen.queryByRole("button", { name: /Apply|Сохранить|Закрыть/ })).not.toBeInTheDocument();
  expect(preview.mock.calls[0][0]).toEqual([xml]);
});

it("retires late A after selecting B then A, and requires a fresh explicit preview", async () => {
  let resolve!: (value: SourceReportPreview) => void;
  preview.mockReturnValueOnce(
    new Promise((r) => {
      resolve = r;
    }),
  );
  const view = render(<SourceReportPreviewPanel xmlFiles={[xml]} />);
  choosePdf();
  fireEvent.click(screen.getByRole("button", { name: "Проверить XML и PDF" }));
  await waitFor(() => expect(preview).toHaveBeenCalledOnce());
  const signal = preview.mock.calls[0][3];
  view.rerender(<SourceReportPreviewPanel xmlFiles={[new File(["B"], "other.xml")]} />);
  view.rerender(<SourceReportPreviewPanel xmlFiles={[xml]} />);
  expect(signal?.aborted).toBe(true);
  await act(async () => resolve(result()));
  expect(screen.queryByText(/Период PDF:/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Проверить XML и PDF" })).toBeEnabled();
});

it("invalidates a completed preview when PDF or inception assertion changes", async () => {
  preview.mockResolvedValue(result());
  render(<SourceReportPreviewPanel xmlFiles={[xml]} />);
  choosePdf();
  fireEvent.click(screen.getByRole("button", { name: "Проверить XML и PDF" }));
  await screen.findByText(/Период PDF:/);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.queryByText(/Период PDF:/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Проверить XML и PDF" }));
  await screen.findByText(/Период PDF:/);
  choosePdf();
  expect(screen.queryByText(/Период PDF:/)).not.toBeInTheDocument();
  expect(preview.mock.calls[1][2]).toBe(true);
});
