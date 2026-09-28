import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import type { PerformanceContext } from "./capitalPerformanceContext";
import { HistoricalMembership } from "./HistoricalMembership";

vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  apiRequest: vi.fn(),
}));

const context: PerformanceContext = {
  start: "2030-05-01",
  end: "2030-05-31",
  scope: "account",
  accountId: 1,
  view: "accounts",
};
type Row = {
  id: number;
  effective_from: string;
  effective_to: string | null;
  include_in_returns: boolean;
};
let rows: Row[];
let version: number;
let reads: number;
let ambiguous: boolean;
let mismatch: boolean;
let readFails: boolean;
let posts: number;

function response() {
  return {
    account_id: 1,
    start_date: context.start,
    end_date: context.end,
    scope: context.scope,
    rows: structuredClone(rows),
    identity: `version-${version}`,
    form_token: `form-${++reads}`,
    readiness: {
      scope: "account",
      account_id: 1,
      start_date: context.start,
      end_date: context.end,
      xirr: { value: null },
      twrr: { value: null },
    },
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  rows = [];
  version = 0;
  reads = 0;
  posts = 0;
  ambiguous = false;
  mismatch = false;
  readFails = false;
  vi.mocked(apiRequest).mockImplementation(async (_path, options) => {
    if (options?.method === "POST") {
      posts++;
      const body = options.body as { replaced_ids: number[]; replacements: Omit<Row, "id">[] };
      rows = [
        ...rows.filter((r) => !body.replaced_ids.includes(r.id)),
        ...body.replacements.map((r, i) => ({ ...r, id: 20 + i })),
      ];
      version++;
      if (ambiguous) throw new Error("Connection lost after commit");
      return response();
    }
    if (readFails && posts > 0) throw new Error("Read failed");
    const result = response();
    if (mismatch && posts > 0) result.identity = "concurrent-edit";
    return result;
  });
});
afterEach(cleanup);

function setup() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <HistoricalMembership accountId={1} context={context} />
    </QueryClientProvider>,
  );
}

async function prepare() {
  fireEvent.click(await screen.findByRole("button", { name: "Добавить явный интервал" }));
  fireEvent.change(screen.getByLabelText("Начало"), { target: { value: "2030-05-01" } });
  fireEvent.change(screen.getByLabelText("Конец включительно"), {
    target: { value: "2030-05-31" },
  });
  fireEvent.change(screen.getByLabelText("Участие"), { target: { value: "excluded" } });
  fireEvent.click(screen.getByLabelText(/Я проверил/));
}

describe("finite historical membership", () => {
  it("requires explicit dates, inclusion and re-attestation; verifies the full read-back", async () => {
    setup();
    fireEvent.click(await screen.findByRole("button", { name: "Добавить явный интервал" }));
    expect(screen.getByLabelText("Начало")).toHaveValue("");
    expect(screen.getByLabelText("Участие")).toHaveValue("");
    expect(screen.getByText(/Новая запись:.*участие не выбрано/)).toBeInTheDocument();
    expect(screen.queryByText(/Новая запись:.*исключён/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Подтвердить изменение участия" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Начало"), { target: { value: "2030-05-01" } });
    fireEvent.change(screen.getByLabelText("Конец включительно"), {
      target: { value: "2030-05-31" },
    });
    fireEvent.change(screen.getByLabelText("Участие"), { target: { value: "included" } });
    fireEvent.click(screen.getByLabelText(/Я проверил/));
    fireEvent.change(screen.getByLabelText("Участие"), { target: { value: "excluded" } });
    expect(screen.getByLabelText(/Я проверил/)).not.toBeChecked();
    fireEvent.click(screen.getByLabelText(/Я проверил/));
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить изменение участия" }));
    await screen.findByText(/История подтверждена/);
    expect(posts).toBe(1);
    expect(reads).toBeGreaterThan(2);
    expect(rows[0].include_in_returns).toBe(false);
  });

  it("shows open-ended rows read-only and blocks every overlap", async () => {
    rows = [{ id: 1, effective_from: "2030-05-01", effective_to: null, include_in_returns: true }];
    setup();
    const row = await screen.findByRole("checkbox", { name: /Запись 1:/ });
    expect(row).toBeDisabled();
    await prepare();
    expect(screen.getByRole("button", { name: "Подтвердить изменение участия" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Пересечения недопустимы");
    expect(posts).toBe(0);
  });

  it("withdraws only explicitly selected identities and leaves unknown history", async () => {
    rows = [
      {
        id: 9,
        effective_from: "2030-05-01",
        effective_to: "2030-05-31",
        include_in_returns: false,
      },
    ];
    setup();
    fireEvent.click(await screen.findByRole("checkbox", { name: /Запись 9:/ }));
    expect(screen.getByText("История будет неизвестной.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Я проверил/));
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить изменение участия" }));
    await screen.findByText(/История подтверждена/);
    const write = vi.mocked(apiRequest).mock.calls.find(([, opts]) => opts?.method === "POST");
    expect(write?.[1]?.body).toMatchObject({ replaced_ids: [9], replacements: [], attested: true });
  });

  it.each(["ambiguous", "mismatch", "read failure"])(
    "fails closed after %s without automatic POST retry",
    async (mode) => {
      ambiguous = mode === "ambiguous";
      mismatch = mode === "mismatch";
      readFails = mode === "read failure";
      setup();
      await prepare();
      const button = screen.getByRole("button", { name: "Подтвердить изменение участия" });
      fireEvent.click(button);
      fireEvent.click(button);
      await screen.findByText(/Изменение не подтверждено/);
      expect(screen.queryByText(/История подтверждена/)).not.toBeInTheDocument();
      await waitFor(() => expect(posts).toBe(1));
      if (mode !== "read failure")
        expect(
          screen.getByRole("button", { name: "Подтвердить изменение участия" }),
        ).toBeDisabled();
    },
  );
});
