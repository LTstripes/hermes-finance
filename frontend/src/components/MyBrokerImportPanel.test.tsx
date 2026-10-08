import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listAccounts } from "../api/accounts";
import { confirmBrokerIdentityMapping } from "../api/brokerIdentityMappings";
import { listInstruments } from "../api/instruments";
import {
  applyMyBroker,
  type MyBrokerImport,
  type MyBrokerPreview,
  previewMyBroker,
  readMyBrokerImport,
} from "../api/mybrokerImport";
import { MyBrokerImportPanel, verifyMyBrokerReadback } from "./MyBrokerImportPanel";

vi.mock("../api/mybrokerImport", () => ({
  previewMyBroker: vi.fn(),
  applyMyBroker: vi.fn(),
  readMyBrokerImport: vi.fn(),
}));
vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
vi.mock("../api/brokerIdentityMappings", () => ({ confirmBrokerIdentityMapping: vi.fn() }));

const preview: MyBrokerPreview = {
  document: {
    provider: "alfa_mybroker",
    parser: "mybroker-s1-v1",
    document_sha256: "a".repeat(64),
    filename_account: "1234567",
    covered_from: "2030-01-01",
    covered_to: "2030-01-31",
    source_accounts: ["1234567", "1234567-000"],
    section_inventory: { "1_Positions": 0, "2_Trades": 0 },
    positions: [],
    trades: [],
    money: [],
  },
  confirmation_digest: "b".repeat(64),
  mappings: [{ kind: "account", identity: "1234567", mapping_id: 1, hermes_id: 1 }],
  missing_mappings: [],
  conflicts: [],
  blockers: [],
  coverage_state: "unknown",
  can_apply: true,
};
const imported: MyBrokerImport = {
  import_id: 1,
  document: preview.document,
  mappings: preview.mappings,
  confirmation_digest: preview.confirmation_digest,
  coverage_state: "unknown",
};

async function inspect(user: ReturnType<typeof userEvent.setup>) {
  const file = new File(
    ["entirely synthetic placeholder"],
    "Брокерский 1234567 (01.01.30-31.01.30).xml",
    { type: "text/xml" },
  );
  await user.upload(screen.getByLabelText("XML MyBroker"), file);
  await user.click(screen.getByRole("button", { name: "Проверить XML" }));
  await screen.findByText(/Период: 2030-01-01/);
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(previewMyBroker).mockResolvedValue(structuredClone(preview));
  vi.mocked(listAccounts).mockResolvedValue([]);
  vi.mocked(listInstruments).mockResolvedValue([]);
  vi.mocked(applyMyBroker).mockResolvedValue(structuredClone(imported));
  vi.mocked(readMyBrokerImport).mockResolvedValue(structuredClone(imported));
});

describe("MyBroker explicit Preview Apply", () => {
  it("requires range/mapping confirmation and shows success only after matching reread", async () => {
    const user = userEvent.setup();
    render(<MyBrokerImportPanel />);
    await inspect(user);
    const apply = screen.getByRole("button", { name: "Сохранить данные отчёта" });
    expect(apply).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(apply);
    await screen.findByRole("status");
    expect(applyMyBroker).toHaveBeenCalledTimes(1);
    expect(readMyBrokerImport).toHaveBeenCalledWith(1);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it.each(["network", "mismatch"])("retires confirmation on %s reread failure", async (failure) => {
    if (failure === "network")
      vi.mocked(readMyBrokerImport).mockRejectedValue(new Error("unavailable"));
    else
      vi.mocked(readMyBrokerImport).mockResolvedValue({
        ...imported,
        document: { ...imported.document, covered_to: "2030-02-28" },
      });
    const user = userEvent.setup();
    render(<MyBrokerImportPanel />);
    await inspect(user);
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Сохранить данные отчёта" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("requires explicit mapping in the distinct provider namespace and a fresh Preview", async () => {
    vi.mocked(previewMyBroker).mockResolvedValueOnce({
      ...preview,
      can_apply: false,
      missing_mappings: [{ kind: "account", identity: "1234567-000" }],
    });
    vi.mocked(listAccounts).mockResolvedValue([{ id: 1, name: "Synthetic account" }] as Awaited<
      ReturnType<typeof listAccounts>
    >);
    const user = userEvent.setup();
    render(<MyBrokerImportPanel />);
    await inspect(user);
    expect(confirmBrokerIdentityMapping).not.toHaveBeenCalled();
    await user.selectOptions(screen.getByLabelText("Счёт 1234567-000"), "1");
    await user.click(screen.getByRole("button", { name: "Подтвердить сопоставление" }));
    await waitFor(() => expect(previewMyBroker).toHaveBeenCalledTimes(2));
    expect(confirmBrokerIdentityMapping).toHaveBeenCalledWith({
      provider: "alfa_mybroker",
      subject_kind: "account",
      provider_identity: "1234567-000",
      hermes_target_id: 1,
    });
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("blocks conflicts and clears an earlier confirmation when the file changes", async () => {
    vi.mocked(previewMyBroker).mockResolvedValueOnce({
      ...preview,
      can_apply: false,
      conflicts: ["pending_disappeared"],
    });
    const user = userEvent.setup();
    render(<MyBrokerImportPanel />);
    await inspect(user);
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByText(/Нерассчитанная сделка исчезла/)).toBeVisible();
    await user.upload(
      screen.getByLabelText("XML MyBroker"),
      new File(["other"], "other.xml", { type: "text/xml" }),
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(applyMyBroker).not.toHaveBeenCalled();
  });

  it("does not accept different persisted identities or mappings", () => {
    expect(() =>
      verifyMyBrokerReadback(preview, imported, { ...imported, import_id: 2 }),
    ).toThrow();
    expect(() =>
      verifyMyBrokerReadback(preview, imported, { ...imported, mappings: [] }),
    ).toThrow();
  });

  it("shows endpoint quantities, values and RUB money evidence", async () => {
    vi.mocked(previewMyBroker).mockResolvedValueOnce({
      ...structuredClone(preview),
      document: {
        ...preview.document,
        positions: [
          {
            ordinal: 0,
            source_account: "1234567-000",
            isin: "RU000A000000",
            actual_quantity: "10",
            forward_quantity: "10",
            beginning_actual_quantity: "8",
            beginning_value: "800",
            ending_value: "1000",
          },
        ],
        rub_money: [
          {
            ordinal: 1,
            source_account: "1234567-000",
            currency: "RUB",
            beginning_amount: "500",
            ending_amount: "400",
          },
        ],
      },
    });
    const user = userEvent.setup();
    render(<MyBrokerImportPanel />);
    await inspect(user);
    expect(screen.getByText("8 / 10")).toBeVisible();
    expect(screen.getByText("800 / 1000")).toBeVisible();
    expect(screen.getByText("500")).toBeVisible();
    expect(screen.getByText("400")).toBeVisible();
    expect(screen.getByText(/деньги RUB: 1/)).toBeVisible();
  });

  it("renders legacy readbacks without endpoint keys", async () => {
    vi.mocked(previewMyBroker).mockResolvedValueOnce({
      ...structuredClone(preview),
      document: {
        ...preview.document,
        positions: [
          {
            ordinal: 0,
            source_account: "1234567-000",
            isin: "RU000A000000",
            actual_quantity: "10",
            forward_quantity: "10",
          },
        ],
      },
    });
    const user = userEvent.setup();
    render(<MyBrokerImportPanel />);
    await inspect(user);
    expect(screen.getByText("— / 10")).toBeVisible();
    expect(screen.getByText("— / —")).toBeVisible();
    expect(screen.getByText(/деньги RUB: 0/)).toBeVisible();
  });
});

it("reviews an archived ISIN skip without creating a mapping and verifies its GET", async () => {
  const isin = "RU000A000001";
  const document = {
    ...preview.document,
    positions: [
      {
        ordinal: 0,
        source_account: "1234567-000",
        isin,
        actual_quantity: "10",
        forward_quantity: "10",
      },
    ],
  };
  const reviewed: MyBrokerPreview = {
    ...preview,
    document,
    instrument_choices: [{ isin, choice: "skip" }],
    instrument_dispositions: [{ isin, source_set_fingerprint: "c".repeat(64) }],
    counts: { mapped: 0, skipped: 1, unsupported: 0 },
  };
  vi.mocked(previewMyBroker)
    .mockResolvedValueOnce({
      ...reviewed,
      can_apply: false,
      instrument_choices: [{ isin, choice: "undecided" }],
      instrument_dispositions: [],
      counts: { mapped: 0, skipped: 0, unsupported: 0 },
      missing_mappings: [{ kind: "instrument", identity: isin }],
    })
    .mockResolvedValueOnce(reviewed);
  const saved: MyBrokerImport = {
    ...imported,
    document,
    counts: reviewed.counts,
    instrument_choices: reviewed.instrument_choices,
    instrument_dispositions: [
      {
        isin,
        source_set_fingerprint: "c".repeat(64),
        revision_id: 1,
        revision: 1,
        effective_state: "accepted",
      },
    ],
  };
  vi.mocked(applyMyBroker).mockResolvedValue(saved);
  vi.mocked(readMyBrokerImport).mockResolvedValue(saved);
  const user = userEvent.setup();
  render(<MyBrokerImportPanel />);
  await inspect(user);
  expect(screen.getByRole("checkbox")).toBeDisabled();
  expect(readMyBrokerImport).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Пропустить (не учитывать)" }));
  await waitFor(() => expect(previewMyBroker).toHaveBeenCalledTimes(2));
  expect(vi.mocked(previewMyBroker).mock.calls[1][1]).toEqual([isin]);
  expect(confirmBrokerIdentityMapping).not.toHaveBeenCalled();
  await screen.findByText(/Источник сохранён; для затронутой/);
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Сохранить данные отчёта" }));
  await screen.findByRole("status");
  expect(() =>
    verifyMyBrokerReadback(reviewed, saved, {
      ...saved,
      instrument_dispositions: [
        { isin, source_set_fingerprint: "c".repeat(64), effective_state: "retired" },
      ],
    }),
  ).toThrow();
  expect(() =>
    verifyMyBrokerReadback(reviewed, saved, {
      ...saved,
      instrument_choices: [{ isin, choice: "map" }],
    }),
  ).toThrow();
});

const replayIsin = "RU000A000001";
const replayPreview: MyBrokerPreview = {
  ...preview,
  already_imported: 1,
  instrument_choices: [{ isin: replayIsin, choice: "skip" }],
  instrument_dispositions: [{ isin: replayIsin, source_set_fingerprint: "c".repeat(64) }],
  counts: { mapped: 0, skipped: 1, unsupported: 0 },
};
const replayImport: MyBrokerImport = {
  ...imported,
  instrument_choices: replayPreview.instrument_choices,
  counts: replayPreview.counts,
  instrument_dispositions: [
    {
      isin: replayIsin,
      source_set_fingerprint: "c".repeat(64),
      revision_id: 1,
      revision: 1,
      effective_state: "accepted",
    },
  ],
};
const undecidedReplay: MyBrokerPreview = {
  ...replayPreview,
  instrument_choices: [{ isin: replayIsin, choice: "undecided" }],
  instrument_dispositions: [],
  counts: { mapped: 0, skipped: 0, unsupported: 0 },
  missing_mappings: [{ kind: "instrument", identity: replayIsin }],
  conflicts: ["instrument_disposition_reconciliation_required"],
  can_apply: false,
};
const replayButton = "Подтверждаю прежние решения — проверить повторно";

it("replays GET-reviewed skip after fresh mount and file reselection with a new Preview and GET", async () => {
  vi.mocked(previewMyBroker)
    .mockResolvedValueOnce({ ...undecidedReplay, already_imported: null, conflicts: [] })
    .mockResolvedValueOnce({ ...replayPreview, already_imported: null })
    .mockResolvedValueOnce(undecidedReplay)
    .mockResolvedValueOnce(replayPreview)
    .mockResolvedValueOnce(undecidedReplay)
    .mockResolvedValueOnce(replayPreview);
  vi.mocked(applyMyBroker).mockResolvedValue(replayImport);
  vi.mocked(readMyBrokerImport).mockResolvedValue(replayImport);
  const user = userEvent.setup();
  const first = render(<MyBrokerImportPanel />);
  await inspect(user);
  expect(readMyBrokerImport).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Пропустить (не учитывать)" }));
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Сохранить данные отчёта" }));
  await screen.findByRole("status");
  expect(readMyBrokerImport).toHaveBeenCalledTimes(1);
  first.unmount();
  render(<MyBrokerImportPanel />);

  for (let repeat = 0; repeat < 2; repeat++) {
    await inspect(user);
    expect(vi.mocked(previewMyBroker).mock.calls[2 + repeat * 2][1]).toEqual([]);
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Пропустить (не учитывать)" })).toBeNull();
    expect(screen.getByRole("button", { name: "Подтвердить сопоставление" })).toBeDisabled();
    await user.click(await screen.findByRole("button", { name: replayButton }));
    await waitFor(() => expect(screen.getByRole("checkbox")).toBeEnabled());
    expect(vi.mocked(previewMyBroker).mock.calls[3 + repeat * 2][1]).toEqual([replayIsin]);
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Сохранить данные отчёта" }));
    await screen.findByRole("status");
    expect(vi.mocked(applyMyBroker).mock.calls[repeat + 1][1]).toEqual(replayPreview);
  }
  expect(applyMyBroker).toHaveBeenCalledTimes(3);
  expect(readMyBrokerImport).toHaveBeenCalledTimes(9);
  expect(confirmBrokerIdentityMapping).not.toHaveBeenCalled();
  vi.mocked(previewMyBroker).mockResolvedValue({
    ...undecidedReplay,
    already_imported: null,
    conflicts: [],
    document: { ...preview.document, document_sha256: "d".repeat(64) },
  });
  await user.upload(
    screen.getByLabelText("XML MyBroker"),
    new File(["new synthetic document"], "new.xml", { type: "text/xml" }),
  );
  await user.click(screen.getByRole("button", { name: "Проверить XML" }));
  await screen.findByText(/Период: 2030-01-01/);
  expect(vi.mocked(previewMyBroker).mock.calls[6][1]).toEqual([]);
  expect(readMyBrokerImport).toHaveBeenCalledTimes(9);
  expect(screen.queryByRole("button", { name: replayButton })).toBeNull();
  expect(screen.getByRole("checkbox")).toBeDisabled();
});

it.each(["retired", "revoked", "invalid", "changed", "document"])(
  "refuses %s authoritative replay evidence before confirmation",
  async (state) => {
    vi.mocked(previewMyBroker).mockResolvedValue(undecidedReplay);
    const invalid = structuredClone(replayImport);
    if (state === "changed") invalid.instrument_choices = [{ isin: replayIsin, choice: "map" }];
    else if (state === "document") invalid.document.document_sha256 = "d".repeat(64);
    else if (invalid.instrument_dispositions)
      invalid.instrument_dispositions[0].effective_state = state as
        | "retired"
        | "revoked"
        | "invalid";
    vi.mocked(readMyBrokerImport).mockResolvedValue(invalid);
    const user = userEvent.setup();
    render(<MyBrokerImportPanel />);
    await user.upload(
      screen.getByLabelText("XML MyBroker"),
      new File(["synthetic"], "report.xml", { type: "text/xml" }),
    );
    await user.click(screen.getByRole("button", { name: "Проверить XML" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: replayButton })).toBeNull();
    expect(applyMyBroker).not.toHaveBeenCalled();
  },
);

it.each(["changed", "retired", "changed-preview", "stale-preview", "stale-apply"])(
  "does not bypass %s after showing recorded choices",
  async (failure) => {
    vi.mocked(previewMyBroker)
      .mockResolvedValueOnce(undecidedReplay)
      .mockResolvedValue(replayPreview);
    vi.mocked(readMyBrokerImport).mockResolvedValue(replayImport);
    const user = userEvent.setup();
    render(<MyBrokerImportPanel />);
    await inspect(user);
    if (failure === "changed" || failure === "retired") {
      const changed = structuredClone(replayImport);
      if (failure === "changed") changed.instrument_choices = [{ isin: replayIsin, choice: "map" }];
      else if (changed.instrument_dispositions)
        changed.instrument_dispositions[0].effective_state = "retired";
      vi.mocked(readMyBrokerImport).mockResolvedValue(changed);
    } else if (failure === "changed-preview") {
      vi.mocked(previewMyBroker).mockResolvedValue({
        ...replayPreview,
        instrument_choices: [{ isin: replayIsin, choice: "map" }],
      });
    } else if (failure === "stale-preview") {
      vi.mocked(previewMyBroker).mockResolvedValue({
        ...replayPreview,
        can_apply: false,
        conflicts: ["accepted_mapping_conflict"],
      });
    } else vi.mocked(applyMyBroker).mockRejectedValue(new Error("confirmation_stale"));
    await user.click(screen.getByRole("button", { name: replayButton }));
    if (failure === "stale-preview") {
      await waitFor(() => expect(previewMyBroker).toHaveBeenCalledTimes(2));
      expect(screen.getByRole("checkbox")).toBeDisabled();
      expect(applyMyBroker).not.toHaveBeenCalled();
    } else {
      if (failure === "stale-apply") {
        await waitFor(() => expect(screen.getByRole("checkbox")).toBeEnabled());
        await user.click(screen.getByRole("checkbox"));
        await user.click(screen.getByRole("button", { name: "Сохранить данные отчёта" }));
      }
      await screen.findByRole("alert");
      expect(screen.queryByRole("status")).toBeNull();
      expect(screen.queryByRole("checkbox")).toBeNull();
      if (failure !== "stale-apply") {
        expect(previewMyBroker).toHaveBeenCalledTimes(failure === "changed-preview" ? 2 : 1);
        expect(applyMyBroker).not.toHaveBeenCalled();
      }
    }
    expect(confirmBrokerIdentityMapping).not.toHaveBeenCalled();
  },
);
