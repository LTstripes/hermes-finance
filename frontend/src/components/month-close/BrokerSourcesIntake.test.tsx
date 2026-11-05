import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { BrokerSource, BrokerSources } from "../../api/brokerSources";
import { BrokerSourcesIntake } from "./BrokerSourcesIntake";

const api = vi.hoisted(() => ({
  read: vi.fn(),
  upload: vi.fn(),
  intake: vi.fn(),
  identity: vi.fn(),
}));
vi.mock("../../api/brokerSources", () => ({
  readBrokerSources: api.read,
  uploadBrokerSources: api.upload,
  brokerFileIdentity: api.identity,
}));
vi.mock("../../api/sourceIntake", () => ({ readSourceIntake: api.intake }));
vi.mock("../../api/accounts", () => ({ listAccounts: async () => [] }));
vi.mock("../../api/instruments", () => ({ listInstruments: async () => [] }));
vi.mock("../../ui-v2/UiV2StatementImportSection", () => ({ confirmStatementApply: vi.fn() }));
vi.mock("../SavedInvestmentReports", () => ({ SavedInvestmentReports: () => null }));
vi.mock("../SourceReportPreviewPanel", () => ({ SourceReportPreviewPanel: () => null }));
vi.mock("../StatementImportPanel", () => ({
  StatementImportPanel: ({ initialFile }: { initialFile?: File }) => (
    <p>Разбор выбранного PDF: {initialFile?.name}</p>
  ),
}));

const month = { id: 12, year: 2030, month: 1, status: "draft" as const };
const source = (name: string, id: number | null = 1): BrokerSource => ({
  intake_id: id,
  receipt_seq: id === null ? 20 : undefined,
  document_sha256: name,
  filename_digest: `${name}-name`,
  kind: id === null ? "income_pdf" : "mybroker_xml",
  slot: name,
  source_accounts: [name],
  covered_from: "2030-01-01",
  covered_to: "2030-01-31",
  state: "needs_decision",
  exceptions: [],
  head_seq: 1,
  request_ids: ["save"],
});
const state = (items: BrokerSource[] = []): BrokerSources => ({
  reporting_month_id: 12,
  items,
  confirmation_count: items.filter((item) => item.state === "needs_decision").length,
  status: !items.length
    ? "empty"
    : items.some((item) => item.state === "needs_decision")
      ? "needs_confirmation"
      : "ok",
  severity: items.some((item) => item.state === "needs_decision") ? "warning" : null,
  financial_effects: 0,
});
function mount(closed = false) {
  const onSaved = vi.fn();
  const onReview = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <BrokerSourcesIntake
        month={{ ...month, status: closed ? "closed" : "draft" }}
        onSaved={onSaved}
        onReview={onReview}
      />
    </QueryClientProvider>,
  );
  return { ...view, onSaved, onReview };
}
beforeEach(() => {
  vi.resetAllMocks();
  api.read.mockResolvedValue(state());
  api.identity.mockImplementation(async (file: File) => ({
    document_sha256: file.name,
    filename_digest: `${file.name}-name`,
  }));
  api.intake.mockImplementation(async (id: number) => ({
    id,
    document_sha256: id === 1 ? "first.xml" : "second.xml",
    head_seq: 1,
  }));
});

it("drops XML and PDF together, keeps successful siblings and retries only the PDF", async () => {
  const first = source("first.xml", 1);
  const second = source("second.xml", 2);
  const pdf = source("income.pdf", null);
  mount();
  await screen.findByText("Загрузи файлы выбранного месяца.");
  expect(screen.getAllByLabelText("Выбрать файлы")).toHaveLength(1);
  expect(
    within(screen.getByRole("list", { name: "Места для файлов" })).getAllByRole("listitem"),
  ).toHaveLength(3);
  api.read.mockResolvedValue(state([first, second]));
  api.upload.mockResolvedValueOnce({
    ...state([first, second]),
    results: [
      { index: 0, item: first, error: null },
      { index: 1, item: second, error: null },
      { index: 2, item: null, error: { code: "synthetic", message: "Не удалось прочитать PDF." } },
    ],
  });
  const files = [
    new File(["a"], "first.xml"),
    new File(["b"], "second.xml"),
    new File(["c"], "income.pdf"),
  ];
  fireEvent.drop(
    screen.getByRole("group", {
      name: "Перетащи сюда XML-выписки и PDF отчёта о выплатах",
    }),
    { dataTransfer: { files } },
  );
  await screen.findByText("income.pdf: Не удалось прочитать PDF.");
  expect(api.upload.mock.calls[0][1]).toEqual(files);
  api.read.mockResolvedValue(state([first, second, pdf]));
  api.upload.mockResolvedValueOnce({
    ...state([first, second, pdf]),
    results: [{ index: 0, item: pdf, error: null, duplicate: false }],
  });
  fireEvent.click(screen.getByRole("button", { name: "Повторить проблемные файлы" }));
  await screen.findByText("Нужен разбор файлов: 3");
  expect(api.upload.mock.calls[1][1]).toEqual([files[2]]);
  expect(api.upload.mock.calls[1][2]).toEqual(api.upload.mock.calls[0][2]);
  expect(screen.queryByText("synthetic")).not.toBeInTheDocument();
});

it("recovers a lost upload response through GET without replaying POST", async () => {
  mount();
  await screen.findByText("Загрузи файлы выбранного месяца.");
  api.upload.mockRejectedValueOnce(new Error("lost ACK"));
  fireEvent.change(screen.getByLabelText("Выбрать файлы"), {
    target: { files: [new File(["a"], "first.xml")] },
  });
  await screen.findByText("Ответ загрузки не получен; проверь сохранённый результат.");
  api.read.mockResolvedValue(state([source("first.xml")]));
  fireEvent.click(screen.getByRole("button", { name: "Прочитать результат загрузки" }));
  await screen.findByText("Сохранённые файлы подтверждены.");
  expect(api.upload).toHaveBeenCalledTimes(1);
});

it("reads saved warnings after remount and opens existing decisions without dismissing a finding", async () => {
  api.read.mockResolvedValue(state([source("first.xml")]));
  const first = mount();
  await screen.findByText("Нужен разбор файлов: 1");
  first.unmount();
  const second = mount();
  await screen.findByText("Нужен разбор файлов: 1");
  fireEvent.click(screen.getByRole("button", { name: "Разобрать операцию" }));
  expect(second.onReview).toHaveBeenCalledWith(1);
  expect(screen.getByText("Нужен разбор файлов: 1")).toBeInTheDocument();
  expect(api.upload).not.toHaveBeenCalled();
});

it("requires the original PDF after reload and reuses it in the existing selected-row review", async () => {
  const pdf = source("income.pdf", null);
  api.read.mockResolvedValue(state([pdf]));
  mount();
  await screen.findByText("Нужен разбор файлов: 1");
  fireEvent.click(screen.getByRole("button", { name: "Разобрать операцию" }));
  await screen.findByText(
    "Выбери исходный PDF в зоне загрузки, чтобы проверить и принять его выплаты.",
  );
  api.upload.mockResolvedValueOnce({
    ...state([pdf]),
    results: [{ index: 0, item: pdf, error: null, duplicate: true }],
  });
  fireEvent.change(screen.getByLabelText("Выбрать файлы"), {
    target: { files: [new File(["c"], "income.pdf")] },
  });
  await screen.findByText("Этот файл уже загружен.");
  fireEvent.click(screen.getByRole("button", { name: "Разобрать операцию" }));
  await screen.findByText("Разбор выбранного PDF: income.pdf");
  expect(screen.getAllByLabelText("Выбрать файлы")).toHaveLength(1);
});

it("does not offer uploading in a closed month", async () => {
  api.read.mockResolvedValue(state([{ ...source("first.xml"), state: "financial_data_accepted" }]));
  mount(true);
  await screen.findByText("Всё в порядке");
  expect(screen.queryByLabelText("Выбрать файлы")).not.toBeInTheDocument();
  await waitFor(() => expect(api.upload).not.toHaveBeenCalled());
});

it("keeps recognized structure information in details after remount without requesting confirmation", async () => {
  const saved = {
    ...source("first.xml"),
    state: "file_saved" as const,
    exceptions: ["4_Transfers_unsupported"],
    information_codes: ["4_Transfers_unsupported"],
    review_issues: [],
  };
  api.read.mockResolvedValue(state([saved]));
  const first = mount();
  await screen.findByText("Всё в порядке");
  first.unmount();
  mount();
  await screen.findByText("Всё в порядке");
  expect(screen.queryByRole("button", { name: "Разобрать операцию" })).not.toBeInTheDocument();
  expect(screen.queryByText(/Нужен разбор файлов/)).not.toBeInTheDocument();
  expect(api.upload).not.toHaveBeenCalled();
  expect(screen.getByText("4_Transfers_unsupported").closest("details")).not.toHaveAttribute(
    "open",
  );
});

it("shows the witnessed operation and one review action while accepted siblings remain saved", async () => {
  api.read.mockResolvedValue(
    state([
      {
        ...source("IIS"),
        review_issues: [
          {
            code: "source_intake_currency_conflict",
            name: "Synthetic bond",
            isin: "RU000A000001",
            source_account: "IIS",
            date: "2030-01-17",
            amount: "500.00",
            currency: "RUB",
            section: "money",
            ordinal: 2,
          },
        ],
      },
      { ...source("Broker", 2), state: "financial_data_accepted" },
    ]),
  );
  const { onReview } = mount();
  await screen.findByText("Нужен разбор файлов: 1");
  expect(screen.getByText(/Synthetic bond/)).toBeVisible();
  expect(screen.getByText(/Счёт IIS.*17.01.2030.*Сумма:/)).toBeVisible();
  expect(screen.getAllByRole("button", { name: "Разобрать операцию" })).toHaveLength(1);
  expect(screen.getByText(/Остальные данные сохранены/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Разобрать операцию" }));
  expect(onReview).toHaveBeenCalledWith(1);
  expect(api.upload).not.toHaveBeenCalled();
});
