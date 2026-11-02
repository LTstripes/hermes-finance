import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
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
