import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import type { IntakeAck } from "../api/sourceIntake";
import { SourceIntakeUpload } from "../components/month-close/SourceIntakeUpload";

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
function setup(fetcher: typeof fetch) {
  vi.stubGlobal("fetch", fetcher);
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <SourceIntakeUpload />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => vi.unstubAllGlobals());
const queryWait = { timeout: 10_000 };
const testTimeout = 20_000;
const syntheticFile = (name: string) => new File(["<synthetic/>"], name, { type: "text/xml" });
function reads(_input: RequestInfo | URL) {
  return json([intake]);
}
async function waitForReturns() {
  await screen.findByLabelText("XML-файлы");
}
function formBody(init: RequestInit | undefined): FormData {
  if (!(init?.body instanceof FormData)) throw new Error("Expected multipart upload body");
  return init.body;
}
const saves = (fetcher: ReturnType<typeof vi.fn<typeof fetch>>) =>
  fetcher.mock.calls.filter(([url]) => String(url).endsWith("/api/broker-months/intakes"));

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
