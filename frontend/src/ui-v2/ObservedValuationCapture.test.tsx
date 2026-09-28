import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, apiRequest } from "../api/client";
import { ObservedValuationCapture } from "./ObservedValuationCapture";

vi.mock("../api/client", async (original) => ({
  ...(await original<typeof import("../api/client")>()),
  apiRequest: vi.fn(),
}));

const context = {
  start: "2030-05-01",
  end: "2030-05-31",
  scope: "account" as const,
  accountId: 1,
  view: "accounts" as const,
};

type MockSide = {
  id: number;
  relation: "pre_external_flow" | "post_external_flow";
  observed_date: string;
  total_value: { amount: string; currency: string };
  performance_currency: string;
  coverage: string;
  quality: string;
  provenance_kind: string;
  bound: boolean;
};

type MockTarget = {
  boundary_group_id: number | null;
  flow_ids: number[];
  event_date: string;
  reporting_month_id: number | null;
  reporting_month_status: string | null;
  scope: "portfolio" | "account";
  account_id: number | null;
  performance_currency: string;
  material_signature: string | null;
  pre_external_flow: MockSide[];
  post_external_flow: MockSide[];
  pre_state: string;
  post_state: string;
  missing_relations: string[];
  reason_codes: string[];
  capture_capability: string | null;
  blocked_reason: string | null;
  form_token: string | null;
};

function baseTarget(overrides: Partial<MockTarget> = {}): MockTarget {
  return {
    boundary_group_id: null,
    flow_ids: [5],
    event_date: "2030-05-15",
    reporting_month_id: 2,
    reporting_month_status: "draft",
    scope: "account",
    account_id: 1,
    performance_currency: "RUB",
    material_signature: "a".repeat(64),
    pre_external_flow: [],
    post_external_flow: [],
    pre_state: "missing",
    post_state: "missing",
    missing_relations: ["pre_external_flow", "post_external_flow"],
    reason_codes: ["not_computable_valuation_boundary_missing"],
    capture_capability: "available",
    blocked_reason: null,
    form_token: "token-1",
    ...overrides,
  };
}

let target: MockTarget;
let reads: number;
let posts: number;
let postMode: "ok" | "ambiguous" | "conflict";
let lastBody: Record<string, unknown> | null;

function response(captured: unknown = null) {
  reads += 1;
  return {
    schema_version: 1,
    scope: "account",
    account_id: 1,
    start_date: context.start,
    end_date: context.end,
    performance_currency: "RUB",
    targets: [structuredClone(target)],
    readiness: {
      scope: "account",
      account_id: 1,
      start_date: context.start,
      end_date: context.end,
      performance_currency: "RUB",
      xirr: { availability: "available" },
      twrr: { availability: "not_computable" },
      diagnostics: [],
    },
    captured,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  target = baseTarget();
  reads = 0;
  posts = 0;
  postMode = "ok";
  lastBody = null;
  vi.mocked(apiRequest).mockImplementation(async (_path, options) => {
    if (options?.method === "POST") {
      posts += 1;
      lastBody = options.body as Record<string, unknown>;
      if (postMode === "ambiguous") throw new Error("Connection lost after commit");
      if (postMode === "conflict") {
        throw new ApiClientError(409, {
          code: "conflict",
          message: "closed reporting month must be reopened before editing",
          details: [],
        });
      }
      const body = options.body as {
        relation: "pre_external_flow" | "post_external_flow";
        total_value: string;
        performance_currency: string;
        coverage: string;
        quality: string;
        provenance_kind: string;
      };
      const side: MockSide = {
        id: 100 + posts,
        relation: body.relation,
        observed_date: target.event_date,
        total_value: { amount: body.total_value, currency: body.performance_currency },
        performance_currency: body.performance_currency,
        coverage: body.coverage,
        quality: body.quality,
        provenance_kind: body.provenance_kind,
        bound: true,
      };
      if (body.relation === "pre_external_flow") {
        target.pre_external_flow = [side];
        target.pre_state = "captured";
      } else {
        target.post_external_flow = [side];
        target.post_state = "captured";
      }
      target.missing_relations = [];
      if (target.pre_state !== "captured") target.missing_relations.push("pre_external_flow");
      if (target.post_state !== "captured") target.missing_relations.push("post_external_flow");
      target.form_token = target.missing_relations.length > 0 ? `token-${reads + 2}` : null;
      target.capture_capability = target.missing_relations.length > 0 ? "available" : null;
      return response({
        id: side.id,
        relation: side.relation,
        observed_date: side.observed_date,
        material_signature: target.material_signature,
      });
    }
    return response();
  });
});
afterEach(cleanup);

function setup() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ObservedValuationCapture context={context} />
    </QueryClientProvider>,
  );
}

async function capturePre(amount = "1100.00") {
  fireEvent.change(await screen.findByLabelText("Сторона наблюдения"), {
    target: { value: "pre_external_flow" },
  });
  fireEvent.change(screen.getByLabelText("Сумма наблюдения"), { target: { value: amount } });
  fireEvent.change(screen.getByLabelText("Полнота наблюдения"), {
    target: { value: "complete" },
  });
  fireEvent.change(screen.getByLabelText("Источник наблюдения"), {
    target: { value: "owner_statement" },
  });
  fireEvent.click(screen.getByLabelText(/Я ввёл/));
  fireEvent.click(screen.getByRole("button", { name: "Сохранить наблюдение" }));
}

describe("observed PRE/POST valuation capture", () => {
  it("shows the exact missing side and publishes one observed value bound to the target", async () => {
    setup();
    expect(await screen.findByText(/PRE — не записано; POST — не записано/)).toBeInTheDocument();
    await screen.findByTestId("valuation-capture-missing-flow:5");
    expect(screen.getByText(/Не хватает: PRE, POST/)).toBeInTheDocument();

    await capturePre();
    await screen.findByText(/Запись подтверждена/);
    expect(posts).toBe(1);
    expect(lastBody).toMatchObject({
      relation: "pre_external_flow",
      total_value: "1100.00",
      performance_currency: "RUB",
      coverage: "complete",
      quality: "exact",
      provenance_kind: "owner_statement",
      form_token: "token-1",
      expected_material_signature: "a".repeat(64),
      attested: true,
    });
    expect(await screen.findByTestId("valuation-capture-side-101")).toBeInTheDocument();
    expect(screen.getByText(/Не хватает: POST/)).toBeInTheDocument();
  });

  it("does not retry an ambiguous write and unlocks only after an explicit reread", async () => {
    postMode = "ambiguous";
    setup();
    await capturePre();
    await screen.findByText(/Результат записи не подтверждён/);
    expect(posts).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Перечитать данные наблюдений" }));
    await screen.findByText(/Данные перечитаны/);
    expect(screen.getByRole("button", { name: "Сохранить наблюдение" })).toBeEnabled();
  });

  it("reports a closed month as requires_reopen without a form", async () => {
    target = baseTarget({
      reporting_month_status: "closed",
      capture_capability: "requires_reopen",
      form_token: null,
    });
    setup();
    expect(await screen.findByText(/Отчёт закрыт\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Сохранить наблюдение" })).not.toBeInTheDocument();
  });

  it("fails closed on ambiguous sides and never offers a convenient repair", async () => {
    target = baseTarget({
      capture_capability: "unsupported",
      blocked_reason: "ambiguous_sides",
      pre_state: "ambiguous",
      pre_external_flow: [
        {
          id: 8,
          relation: "pre_external_flow",
          observed_date: "2030-05-15",
          total_value: { amount: "1100.00", currency: "RUB" },
          performance_currency: "RUB",
          coverage: "complete",
          quality: "exact",
          provenance_kind: "owner_statement",
          bound: false,
        },
        {
          id: 9,
          relation: "pre_external_flow",
          observed_date: "2030-05-15",
          total_value: { amount: "1110.00", currency: "RUB" },
          performance_currency: "RUB",
          coverage: "complete",
          quality: "exact",
          provenance_kind: "owner_statement",
          bound: true,
        },
      ],
      post_external_flow: [],
      post_state: "missing",
      reason_codes: ["not_computable_valuation_boundary_order_unknown"],
    });
    setup();
    expect(await screen.findByText(/несколько записей одной стороны/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Сохранить наблюдение" })).not.toBeInTheDocument();
  });

  it("keeps the order limitation visible when both sides are already captured", async () => {
    const side = (relation: "pre_external_flow" | "post_external_flow", id: number): MockSide => ({
      id,
      relation,
      observed_date: "2030-05-15",
      total_value: { amount: "1100.00", currency: "RUB" },
      performance_currency: "RUB",
      coverage: "complete",
      quality: "exact",
      provenance_kind: "owner_statement",
      bound: true,
    });
    target = baseTarget({
      pre_external_flow: [side("pre_external_flow", 3)],
      post_external_flow: [side("post_external_flow", 4)],
      pre_state: "captured",
      post_state: "captured",
      missing_relations: [],
      capture_capability: null,
      form_token: null,
      reason_codes: ["not_computable_valuation_boundary_order_unknown"],
    });
    setup();
    expect(await screen.findByText(/Обе стороны записаны/)).toBeInTheDocument();
    expect(screen.getByText(/Порядок наблюдения не подтверждён/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Сохранить наблюдение" })).not.toBeInTheDocument();
  });

  it("guards a double click with one submission", async () => {
    setup();
    await capturePre();
    const button = screen.getByRole("button", { name: "Сохранить наблюдение" });
    fireEvent.click(button);
    fireEvent.click(button);
    await screen.findByText(/Запись подтверждена/);
    expect(posts).toBe(1);
  });
});
