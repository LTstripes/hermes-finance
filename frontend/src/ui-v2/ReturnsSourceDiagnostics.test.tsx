import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import ReturnsSourceDiagnostics from "./ReturnsSourceDiagnostics";
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
const monthly = { source_account: "SYNTH-01" };
const instruments = { source_account: "SYNTH-01", instruments: [] };
afterEach(() => vi.unstubAllGlobals());
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
          <ReturnsSourceDiagnostics account="SYNTH-01" />
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

test("canonical native account previews and confirms originals without optional source_accounts", async () => {
  const user = userEvent.setup();
  const account = "SYNTH-01-000";
  const expected = [{ intake_id: 1, manifest_digest: "a".repeat(64) }];
  let confirmed = false;
  const writes: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (init?.method === "POST") writes.push(path);
      if (path.endsWith("/preview")) {
        const form = init?.body;
        if (!(form instanceof FormData)) throw new Error("Expected multipart request");
        const body = JSON.parse(String(form.get("request")));
        expect(body).toEqual({ source_account: account, expected_sources: expected });
        return json({
          source_account: account,
          source_count: 1,
          cancellation_months: [],
          form_token: "synthetic",
          preview_digest: "b".repeat(64),
          financial_authority: "none",
          financial_effects: 0,
        });
      }
      if (path.endsWith("/confirm")) {
        const body = JSON.parse(String(init?.body));
        confirmed = true;
        return json({ source_account: account, request_id: body.request_id });
      }
      if (path.includes("/intakes"))
        return json([
          {
            ...intake,
            manifest_digest: expected[0].manifest_digest,
            document: { filename_account: "SYNTH-01", positions: [{ source_account: account }] },
          },
        ]);
      if (path.includes("/monthly?"))
        return json({
          source_account: account,
          source_proof: {
            status: confirmed ? "current" : "absent",
            proof_id: confirmed ? 1 : null,
          },
        });
      return json({ source_account: account, instruments: [] });
    }),
  );
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <ReturnsSourceDiagnostics account={account} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText(/Оригиналы можно проверить один раз/);
  await user.upload(
    screen.getByLabelText("Оригиналы для подтверждения"),
    new File(["synthetic"], "source.xml", { type: "application/xml" }),
  );
  await user.click(screen.getByRole("button", { name: "Проверить оригиналы" }));
  const save = await screen.findByRole("button", { name: "Сохранить подтверждение" });
  expect(save).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: /Подтверждаю сохранение доказательства/ }));
  await user.click(save);
  await screen.findByText(/Источник подтверждён:/);
  expect(writes).toEqual([
    "/api/source-returns/proofs/preview",
    "/api/source-returns/proofs/confirm",
  ]);
});
