import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import type { IntakeAck } from "../api/sourceIntake";
import { SourceMonthReturn } from "./SourceMonthReturn";
import UiV2MonthlyReturnsPage from "./UiV2MonthlyReturnsPage";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const intake = {
  contract_version: "source_intake_v1",
  id: 1,
  head_seq: 1,
  manifest_digest: "m",
  covered_from: "2030-04-01",
  covered_to: "2030-04-30",
  state: { reporting_month_id: null },
  document: { filename_account: "SYNTH-01" },
  observations: [{ id: 1 }],
  exceptions: [],
  financial_authority: "none",
};
// Synthetic server acknowledgement history, keyed by the actual outbound intent.
const savedAcks = new Map<number, IntakeAck[]>();
function saveAck(init: RequestInit | undefined, intakeId = 2) {
  const requestId = JSON.parse(String(formBody(init).get("intent"))).request_id;
  const prior = savedAcks.get(intakeId) ?? [];
  const ack = {
    intake_id: intakeId,
    request_id: requestId,
    head_seq: prior.length + 1,
    duplicate: false,
  };
  savedAcks.set(intakeId, [...prior, ack]);
  return json(ack);
}
function readSaved(intakeId = 2, patch: Record<string, unknown> = {}) {
  const acks = savedAcks.get(intakeId) ?? [];
  return {
    ...intake,
    id: intakeId,
    head_seq: acks.at(-1)?.head_seq ?? 1,
    history: acks.map((ack) => ({ seq: ack.head_seq, request_id: ack.request_id })),
    ...patch,
  };
}
afterEach(() => savedAcks.clear());
const totals = {
  buys_cost_kopecks: 10000,
  sells_proceeds_kopecks: 0,
  price_effect_kopecks: 2500,
  coupons_kopecks: 300,
  dividends_kopecks: 200,
  assumed_income_kopecks: 0,
  confirmed_income_kopecks: 500,
  income_kopecks: 500,
  total_kopecks: 3000,
  capital_base_kopecks: 110000,
  return_percent: "2.727",
  income_assumptions_used: false,
  income_complete: true,
  flags: [],
  approximate: false,
};
const monthly = {
  source_account: "SYNTH-01",
  authority: "provisional",
  financial_authority: "none",
  currency: "RUB",
  approximate: true,
  gaps: [],
  flows: [],
  defaults_applied: [],
  segments: [],
  period: {
    contributions_kopecks: 20000,
    withdrawals_kopecks: 5000,
    growth_kopecks: 3000,
    chained_return: "0.03",
    xirr_annualized_return: "0.36",
    xirr_period_return: "0.03",
    assumptions_used: false,
    missing_endpoint: false,
    chain_reason_codes: [],
    growth_reason_codes: [],
    xirr_reason_codes: [],
    approximate: true,
  },
  months: [
    {
      opening_date: "2030-03-31",
      closing_date: "2030-04-30",
      opening_kopecks: 100000,
      closing_kopecks: 118000,
      contributions_kopecks: 20000,
      withdrawals_kopecks: 5000,
      growth_kopecks: 3000,
      modified_dietz_return: "0.027",
      assumptions_used: false,
      missing_endpoint: false,
      reason_codes: [],
      approximate: true,
      intake_ids: [1],
      flags: [],
      previous_closing_kopecks: null,
      coupons_kopecks: 300,
      dividends_kopecks: 200,
      income_assumptions_used: false,
    },
  ],
};
const instruments = {
  source_account: "SYNTH-01",
  authority: "provisional",
  financial_authority: "none",
  currency: "RUB",
  gaps: [],
  income: [],
  instruments: [
    {
      isin: "SYNTH000001",
      source_name: "Синтетическая акция",
      instrument_type: "stock",
      months: [
        {
          ...totals,
          month: "2030-04-01",
          opening_quantity: "10",
          closing_quantity: "10",
          opening_value_kopecks: 100000,
          closing_value_kopecks: 112500,
          intake_ids: [1],
        },
      ],
      all_time: {
        ...totals,
        return_percent: null,
        capital_base_kopecks: null,
        available_months: ["2030-04-01"],
        missing_months: [],
        partial_months: [],
        partial: false,
      },
    },
  ],
};
function setup(fetcher: typeof fetch) {
  vi.stubGlobal("fetch", fetcher);
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <UiV2MonthlyReturnsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => vi.unstubAllGlobals());

test.each([
  ["0.001259", "0,13%"],
  ["-0.00125", "−0,13%"],
  ["0.00009999", "0,01%"],
  ["-0.00995", "−1,00%"],
  ["0.99995", "100,00%"],
])("Month and Monthly Returns agree for Decimal boundary %s", async (value, expected) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) =>
      String(input).includes("/source-returns/monthly?")
        ? json({
            ...monthly,
            months: [{ ...monthly.months[0], modified_dietz_return: value }],
          })
        : reads(input),
    ),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/?source_account=SYNTH-01"]}>
        <SourceMonthReturn account="SYNTH-01" period="2030-04" />
        <UiV2MonthlyReturnsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await waitForReturns();
  const card = screen.getByRole("region", { name: "Предварительная доходность месяца" });
  await waitFor(() => expect(card).toHaveTextContent(expected));
  expect(screen.getByTestId("returns-monthly-table")).toHaveTextContent(expected);
});

test.each(["monthly", "intakes"])(
  "failed %s refetch hides retained current proof and disables confirmation",
  async (failedQuery) => {
    let fail = false;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path.includes("/intakes"))
          return fail && failedQuery === "intakes"
            ? json({ error: { code: "offline", message: "Synthetic failed source read" } }, 503)
            : json([intake]);
        if (path.includes("/monthly?"))
          return fail && failedQuery === "monthly"
            ? json({ error: { code: "offline", message: "Synthetic failed read" } }, 503)
            : json({
                ...monthly,
                source_proof: {
                  status: "current",
                  proof_id: 3,
                  version: "source_return_custody_v1",
                  confirmed_at: "2030-05-01T00:00:00Z",
                  currentness: "c",
                  reason_codes: [],
                  financial_authority: "none",
                },
              });
        return json(instruments);
      }),
    );
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <UiV2MonthlyReturnsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByText(/Источник подтверждён:/);
    fail = true;
    await act(async () => {
      await client.invalidateQueries({
        queryKey:
          failedQuery === "monthly" ? ["source-returns", "monthly"] : ["source-intakes", "all"],
      });
    });
    await screen.findByText(/Не удалось проверить актуальность источников/);
    expect(screen.queryByText(/Источник подтверждён:/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Проверить оригиналы" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Сохранить подтверждение" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Не удалось проверить актуальность источников/)).toBeVisible();
    expect(screen.queryByRole("region", { name: "Взносы и рост" })).not.toBeInTheDocument();
  },
);

const queryWait = { timeout: 10_000 };
const testTimeout = 20_000;
const syntheticFile = (name: string) => new File(["<synthetic/>"], name, { type: "text/xml" });
function reads(
  input: RequestInfo | URL,
  monthData: unknown = monthly,
  instrumentData: unknown = instruments,
) {
  const url = String(input);
  if (url.includes("/monthly?")) return json(monthData);
  if (url.includes("/instruments?")) return json(instrumentData);
  return json([intake]);
}
async function waitForReturns() {
  await screen.findByRole("combobox", { name: "Счёт в выписке" }, queryWait);
  await Promise.all([
    screen.findByTestId("returns-monthly-total", {}, queryWait),
    screen.findByTestId("returns-instrument-table", {}, queryWait),
  ]);
}
function formBody(init: RequestInit | undefined): FormData {
  if (!(init?.body instanceof FormData)) throw new Error("Expected multipart upload body");
  return init.body;
}
const saves = (fetcher: ReturnType<typeof vi.fn<typeof fetch>>) =>
  fetcher.mock.calls.filter(([url]) => String(url).endsWith("/api/broker-months/intakes"));

test(
  "lists sorted unique filename accounts, skips empty accounts and tolerates source_accounts",
  async () => {
    const documents = [
      { filename_account: "SYNTH-02" },
      { filename_account: "SYNTH-01" },
      { filename_account: "SYNTH-02", source_accounts: ["SYNTH-03", "SYNTH-01", ""] },
      { filename_account: "" },
      { filename_account: null },
      { filename_account: "   " },
      {},
    ];
    const fetcher = vi.fn<typeof fetch>(async (input) =>
      String(input).includes("/intakes?")
        ? json(documents.map((document, id) => ({ ...intake, id, document })))
        : reads(input),
    );
    setup(fetcher);
    await waitForReturns();
    const select = screen.getByRole("combobox", { name: "Счёт в выписке" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["SYNTH-01", "SYNTH-02", "SYNTH-03"]);
    expect(select).toHaveValue("SYNTH-01");
    for (const endpoint of ["monthly", "instruments"]) {
      expect(
        fetcher.mock.calls.some(([url]) =>
          String(url).includes(`/${endpoint}?source_account=SYNTH-01`),
        ),
      ).toBe(true);
    }
  },
  testTimeout,
);

test(
  "shows the save conflict reason after the generic 409 message",
  async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) =>
      String(input).endsWith("/api/broker-months/intakes")
        ? json(
            {
              error: {
                code: "conflict",
                message: "source_intake_idempotency_conflict",
                details: [],
              },
            },
            409,
          )
        : reads(input),
    );
    setup(fetcher);
    await waitForReturns();
    await userEvent.upload(screen.getByLabelText("XML-файлы"), syntheticFile("conflict.xml"));
    const row = (await screen.findByText("conflict.xml: Не сохранен", {}, queryWait)).closest("li");
    expect(row).toHaveTextContent(
      "Операцию нельзя выполнить в текущем состоянии данных. Причина: source_intake_idempotency_conflict",
    );
    expect(saves(fetcher)).toHaveLength(1);
  },
  testTimeout,
);

test(
  "shows contributions apart from growth and explicitly approximate chained Dietz",
  async () => {
    setup(vi.fn(async (input) => reads(input)));
    await waitForReturns();
    const summary = screen.getByTestId("returns-monthly-total");
    expect(summary).toHaveTextContent("Взносы: 200,00 ₽");
    expect(summary).toHaveTextContent("Рост отдельно: 30,00 ₽");
    expect(summary).toHaveTextContent("XIRR, годовых: 36,00%");
    expect(summary).toHaveTextContent("Цепной Modified Dietz (≈TWRR, приблизительно): 3,00%");
    expect(within(summary).getByText("приблизительно")).toBeVisible();
    const instrument = screen.getByTestId("returns-instrument-table");
    expect(instrument).toHaveTextContent("Изменение цены");
    expect(instrument).toHaveTextContent("Купоны");
    expect(instrument).toHaveTextContent("Дивиденды");
    expect(within(instrument).getAllByText("полные данные")).toHaveLength(2);
  },
  testTimeout,
);

test(
  "uploads every synthetic file independently and keeps per-file flags",
  async () => {
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/broker-months/intakes")) return saveAck(init);
      if (url.endsWith("/2"))
        return json({
          ...readSaved(),
          observations: [{ id: 1 }, { id: 2 }],
          exceptions: ["unknown_section"],
        });
      return reads(input);
    });
    setup(fetcher);
    await waitForReturns();
    await userEvent.upload(screen.getByLabelText("XML-файлы"), [
      syntheticFile("one.xml"),
      syntheticFile("two.xml"),
    ]);
    expect(
      (await screen.findByText("one.xml: Сохранен", {}, queryWait)).closest("li"),
    ).toHaveTextContent("Флаги: unknown_section");
    expect(
      (await screen.findByText("two.xml: Сохранен", {}, queryWait)).closest("li"),
    ).toHaveTextContent("Сохранено наблюдений: 2");
    expect(saves(fetcher)).toHaveLength(2);
  },
  testTimeout,
);

test(
  "keeps unknown values distinct from zero and shows incomplete instrument quality",
  async () => {
    const unknownMonthly = {
      ...monthly,
      period: {
        ...monthly.period,
        contributions_kopecks: null,
        withdrawals_kopecks: 0,
        growth_kopecks: null,
        chained_return: null,
        xirr_annualized_return: null,
        xirr_period_return: null,
        missing_endpoint: true,
      },
      months: [
        {
          ...monthly.months[0],
          contributions_kopecks: null,
          withdrawals_kopecks: 0,
          growth_kopecks: null,
          modified_dietz_return: null,
          missing_endpoint: true,
          reason_codes: ["unknown_flow"],
          flags: ["unknown_flow", "missing_endpoint"],
        },
      ],
    };
    const incomplete = {
      ...totals,
      total_kopecks: null,
      return_percent: null,
      coupons_kopecks: null,
      dividends_kopecks: 0,
      income_kopecks: null,
      approximate: true,
      income_complete: false,
      flags: ["unattributed_income"],
    };
    const unknownInstruments = {
      ...instruments,
      instruments: [
        {
          ...instruments.instruments[0],
          months: [{ ...instruments.instruments[0].months[0], ...incomplete }],
          all_time: { ...instruments.instruments[0].all_time, ...incomplete, partial: true },
        },
      ],
    };
    setup(vi.fn(async (input) => reads(input, unknownMonthly, unknownInstruments)));
    await waitForReturns();
    const summary = screen.getByTestId("returns-monthly-total");
    expect(summary).toHaveTextContent("Взносы: —");
    expect(summary).toHaveTextContent("Выводы: 0,00 ₽");
    expect(summary).toHaveTextContent("Рост отдельно: —");
    expect(summary).toHaveTextContent("XIRR, годовых: —");
    expect(summary).toHaveTextContent("XIRR за период: —");
    expect(summary).toHaveTextContent("Цепной Modified Dietz (≈TWRR, приблизительно): —");
    const row = within(screen.getByTestId("returns-monthly-table")).getAllByRole("row")[1];
    const cells = within(row).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent(/^—$/);
    expect(cells[2]).toHaveTextContent("0,00 ₽");
    expect(cells[3]).toHaveTextContent(/^—$/);
    expect(cells[6]).toHaveTextContent(/^—$/);
    expect(cells[7].textContent?.match(/неизвестный поток/g)).toHaveLength(1);
    expect(cells[7]).toHaveTextContent("частичные данные");
    const instrumentRows = within(screen.getByTestId("returns-instrument-table")).getAllByRole(
      "row",
    );
    for (const instrumentRow of instrumentRows.slice(1)) {
      expect(instrumentRow).toHaveTextContent("приблизительно");
      expect(instrumentRow).toHaveTextContent("частичные данные");
      expect(instrumentRow).toHaveTextContent("доходы неполные");
      expect(instrumentRow).not.toHaveTextContent("полные данные");
      const values = within(instrumentRow).getAllByRole("cell");
      const offset = instrumentRow === instrumentRows[1] ? 0 : 1;
      expect(values[offset]).toHaveTextContent("25,00 ₽");
      expect(values[offset + 1]).toHaveTextContent(/^—$/);
      expect(values[offset + 2]).toHaveTextContent("0,00 ₽");
      expect(values[offset + 3]).toHaveTextContent(/^—$/);
      expect(values[offset + 4]).toHaveTextContent(/^—$/);
    }
  },
  testTimeout,
);

test.each([
  { flows: true, income: false },
  { flows: false, income: true },
])(
  "discloses flow and income assumptions separately: $flows/$income",
  async ({ flows, income }) => {
    const assumed = {
      ...monthly,
      period: { ...monthly.period, assumptions_used: flows },
      defaults_applied: flows
        ? [
            {
              event_date: "2030-04-15",
              amount_kopecks: 20000,
              status: "assumed",
              included: true,
              classification: "external_deposit",
              source_references: ["SYNTH-MONEY-1"],
            },
          ]
        : [],
      months: [{ ...monthly.months[0], assumptions_used: flows, income_assumptions_used: income }],
    };
    const assumedInstruments = {
      ...instruments,
      instruments: [
        {
          ...instruments.instruments[0],
          months: [
            {
              ...instruments.instruments[0].months[0],
              income_assumptions_used: income,
              approximate: income,
            },
          ],
          all_time: {
            ...instruments.instruments[0].all_time,
            income_assumptions_used: income,
            approximate: income,
          },
        },
      ],
    };
    setup(vi.fn(async (input) => reads(input, assumed, assumedInstruments)));
    await waitForReturns();
    const summary = within(screen.getByTestId("returns-monthly-total"));
    expect(summary.queryByText("потоки с допущениями") !== null).toBe(flows);
    expect(summary.queryByText("Потоки по правилам по умолчанию (допущения)") !== null).toBe(flows);
    if (flows) {
      expect(summary.getByRole("listitem")).toHaveTextContent(
        "2030-04-15 · 200,00 ₽ · external_deposit · включён",
      );
      expect(summary.getByRole("listitem")).toHaveTextContent("SYNTH-MONEY-1");
    }
    const row = within(screen.getByTestId("returns-monthly-table"));
    expect(row.queryByText("потоки с допущениями") !== null).toBe(flows);
    expect(row.queryByText("купоны/дивиденды с допущениями") !== null).toBe(income);
    expect(
      within(screen.getByTestId("returns-instrument-table")).queryAllByText(
        "купоны/дивиденды с допущениями",
      ),
    ).toHaveLength(income ? 2 : 0);
  },
  testTimeout,
);

test(
  "renders gaps that appear only in response arrays with source and instrument context",
  async () => {
    const gapMonthly = {
      ...monthly,
      gaps: [
        {
          code: "overlap_flow_deduplicated",
          intake_id: 7,
          month: "2030-04-01",
          source_reference: "SYNTH-FLOW-7",
        },
      ],
    };
    const gapInstruments = {
      ...instruments,
      gaps: [
        {
          code: "partial_month_source",
          intake_id: 8,
          month: "2030-04-01",
          source_reference: "SYNTH-SOURCE-8",
          isin: "SYNTH000001",
        },
        { code: "future_gap_code", intake_id: null, month: null, source_reference: null },
      ],
    };
    setup(vi.fn(async (input) => reads(input, gapMonthly, gapInstruments)));
    await waitForReturns();
    const monthlyGap = within(screen.getByTestId("returns-monthly-total")).getByRole("listitem");
    expect(monthlyGap).toHaveTextContent("повтор потока в перекрывающихся выписках учтён один раз");
    expect(monthlyGap).toHaveTextContent("месяц: апрель 2030");
    expect(monthlyGap).toHaveTextContent("выписка: 7 · строка: SYNTH-FLOW-7");
    const instrumentPanel = screen.getByTestId("returns-instrument-table");
    expect(instrumentPanel).toHaveTextContent("источник покрывает месяц частично");
    expect(instrumentPanel).toHaveTextContent(
      "выписка: 8 · строка: SYNTH-SOURCE-8 · ISIN: SYNTH000001",
    );
    expect(instrumentPanel).toHaveTextContent("future_gap_code");
  },
  testTimeout,
);

test(
  "keeps a successful file when another file fails to save",
  async () => {
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/broker-months/intakes")) {
        const file = formBody(init).get("file") as File;
        if (file.name === "bad.xml")
          return json(
            { error: { code: "synthetic_failure", message: "Синтетический отказ" } },
            422,
          );
        return saveAck(init);
      }
      if (url.endsWith("/2")) return json(readSaved());
      return reads(input);
    });
    setup(fetcher);
    await waitForReturns();
    const input = screen.getByLabelText("XML-файлы");
    await userEvent.upload(input, [syntheticFile("bad.xml"), syntheticFile("good.xml")]);
    expect(
      (await screen.findByText("bad.xml: Не сохранен", {}, queryWait)).closest("li"),
    ).toHaveTextContent("Синтетический отказ");
    expect(
      (await screen.findByText("good.xml: Сохранен", {}, queryWait)).closest("li"),
    ).toHaveTextContent("Сохранено наблюдений: 1");
    await waitFor(() => expect(input).toBeEnabled(), queryWait);
    expect(saves(fetcher)).toHaveLength(2);
  },
  testTimeout,
);

test(
  "preserves Save ACK on readback failure and retries only GET",
  async () => {
    let readCount = 0;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/broker-months/intakes")) return saveAck(init);
      if (url.endsWith("/2")) {
        readCount += 1;
        return readCount === 1 ? json({}, 503) : json(readSaved());
      }
      return reads(input);
    });
    setup(fetcher);
    await waitForReturns();
    await userEvent.upload(screen.getByLabelText("XML-файлы"), syntheticFile("saved.xml"));
    const saved = await screen.findByText(
      "saved.xml: Сохранен · не удалось прочитать",
      {},
      queryWait,
    );
    expect(saved.closest("li")).toHaveTextContent("Сохранение подтверждено");
    expect(screen.queryByText(/saved.xml: Не сохранен/)).not.toBeInTheDocument();
    const retry = await screen.findByRole(
      "button",
      { name: "Повторить чтение saved.xml" },
      queryWait,
    );
    await waitFor(() => expect(retry).toBeEnabled(), queryWait);
    await userEvent.click(retry);
    expect(
      (await screen.findByText("saved.xml: Сохранен", {}, queryWait)).closest("li"),
    ).toHaveTextContent("Сохранено наблюдений: 1");
    expect(saves(fetcher)).toHaveLength(1);
    expect(readCount).toBe(2);
    expect(
      screen.queryByRole("button", { name: "Повторить чтение saved.xml" }),
    ).not.toBeInTheDocument();
  },
  testTimeout,
);

test(
  "keeps same-name files independent and blocks another batch while busy",
  async () => {
    let releaseFirst: (response: Response) => void = () => {
      throw new Error("No pending save");
    };
    const firstSave = new Promise<Response>((resolve) => {
      releaseFirst = resolve;
    });
    let saveCount = 0;
    let firstInit: RequestInit | undefined;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/broker-months/intakes")) {
        saveCount += 1;
        if (saveCount === 1) {
          firstInit = init;
          return firstSave;
        }
        return saveAck(init, 3);
      }
      if (url.endsWith("/2")) return json(readSaved(2, { exceptions: ["first_file_flag"] }));
      if (url.endsWith("/3")) return json(readSaved(3, { exceptions: ["second_file_flag"] }));
      return reads(input);
    });
    setup(fetcher);
    await waitForReturns();
    const input = screen.getByLabelText("XML-файлы");
    await userEvent.upload(input, [syntheticFile("same.xml"), syntheticFile("same.xml")]);
    expect(input).toBeDisabled();
    expect(
      (await screen.findByText("same.xml: Сохранен", {}, queryWait)).closest("li"),
    ).toHaveTextContent("second_file_flag");
    expect(screen.getByText("same.xml: Сохраняем")).toBeVisible();
    await userEvent.upload(input, syntheticFile("blocked.xml"));
    expect(saves(fetcher)).toHaveLength(2);
    expect(screen.queryByText(/blocked.xml/)).not.toBeInTheDocument();
    await act(async () => {
      releaseFirst(saveAck(firstInit));
    });
    await waitFor(() => expect(input).toBeEnabled(), queryWait);
    const rows = screen.getAllByText("same.xml: Сохранен").map((element) => element.closest("li"));
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("first_file_flag");
    expect(rows[0]).not.toHaveTextContent("second_file_flag");
    expect(rows[1]).toHaveTextContent("second_file_flag");
    const requestIds = saves(fetcher).map(
      ([, init]) => JSON.parse(String(formBody(init).get("intent"))).request_id,
    );
    expect(new Set(requestIds).size).toBe(2);
    await userEvent.upload(input, syntheticFile("same.xml"));
    await waitFor(() => expect(input).toBeEnabled(), queryWait);
    expect(saves(fetcher)).toHaveLength(3);
    expect(screen.getAllByText("same.xml: Сохранен")).toHaveLength(1);
  },
  testTimeout,
);

test(
  "shared uploader refuses mismatched GET and keeps ACK for GET-only recovery",
  async () => {
    let readsCount = 0;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/broker-months/intakes")) return saveAck(init);
      if (url.endsWith("/2")) {
        readsCount++;
        return json(readSaved(2, { id: readsCount === 1 ? 99 : 2 }));
      }
      return reads(input);
    });
    setup(fetcher);
    await waitForReturns();
    await userEvent.upload(screen.getByLabelText("XML-файлы"), syntheticFile("mismatch.xml"));
    const retry = await screen.findByRole(
      "button",
      { name: "Повторить чтение mismatch.xml" },
      queryWait,
    );
    await waitFor(() => expect(retry).toBeEnabled(), queryWait);
    await userEvent.click(retry);
    expect(await screen.findByText("mismatch.xml: Сохранен", {}, queryWait)).toBeVisible();
    expect(saves(fetcher)).toHaveLength(1);
    expect(readsCount).toBe(2);
  },
  testTimeout,
);

test(
  "shared uploader reports lost Save ACK as uncertain without a blind retry",
  async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      if (String(input).endsWith("/api/broker-months/intakes")) throw new TypeError("network lost");
      return reads(input);
    });
    setup(fetcher);
    await waitForReturns();
    await userEvent.upload(screen.getByLabelText("XML-файлы"), syntheticFile("uncertain.xml"));
    expect(
      await screen.findByText("uncertain.xml: Результат сохранения неизвестен", {}, queryWait),
    ).toBeVisible();
    expect(screen.queryByText("uncertain.xml: Не сохранен")).not.toBeInTheDocument();
    expect(saves(fetcher)).toHaveLength(1);
  },
  testTimeout,
);

test.each([
  ["older head", { head_seq: 0 }],
  ["missing command in same-ID history", { history: [{ seq: 1, request_id: "another-command" }] }],
  ["wrong contract", { contract_version: "unrecognized" }],
])(
  "retains ACK and GET-only recovery across another batch: %s",
  async (_reason, patch) => {
    let firstReads = 0;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/broker-months/intakes")) {
        const file = formBody(init).get("file") as File;
        return saveAck(init, file.name === "first.xml" ? 2 : 3);
      }
      if (url.endsWith("/2")) {
        firstReads++;
        return json(readSaved(2, firstReads === 1 ? patch : {}));
      }
      if (url.endsWith("/3")) return json(readSaved(3));
      return reads(input);
    });
    setup(fetcher);
    await waitForReturns();
    const input = screen.getByLabelText("XML-файлы");
    await userEvent.upload(input, syntheticFile("first.xml"));
    await waitFor(
      () =>
        expect(screen.getByRole("button", { name: "Повторить чтение first.xml" })).toBeEnabled(),
      queryWait,
    );
    expect(screen.queryByText("first.xml: Сохранен", { exact: true })).not.toBeInTheDocument();
    await userEvent.upload(input, syntheticFile("second.xml"));
    expect(await screen.findByText("second.xml: Сохранен", {}, queryWait)).toBeVisible();
    const retry = screen.getByRole("button", { name: "Повторить чтение first.xml" });
    await waitFor(() => expect(retry).toBeEnabled(), queryWait);
    await userEvent.click(retry);
    expect(await screen.findByText("first.xml: Сохранен", {}, queryWait)).toBeVisible();
    expect(firstReads).toBe(2);
    expect(saves(fetcher)).toHaveLength(2);
    expect(saves(fetcher).map(([, init]) => (formBody(init).get("file") as File).name)).toEqual([
      "first.xml",
      "second.xml",
    ]);
  },
  testTimeout,
);

test(
  "rejects an ACK for another request without reading or retrying that command",
  async () => {
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input).endsWith("/api/broker-months/intakes")) {
        const response = await saveAck(init).json();
        return json({ ...response, request_id: "wrong-command" });
      }
      return reads(input);
    });
    setup(fetcher);
    await waitForReturns();
    await userEvent.upload(screen.getByLabelText("XML-файлы"), syntheticFile("wrong-ack.xml"));
    expect(
      await screen.findByText("wrong-ack.xml: Результат сохранения неизвестен", {}, queryWait),
    ).toBeVisible();
    expect(saves(fetcher)).toHaveLength(1);
    expect(fetcher.mock.calls.some(([input]) => String(input).endsWith("/2"))).toBe(false);
  },
  testTimeout,
);
