import { afterEach, expect, it, vi } from "vitest";
import {
  getSourceInstrumentReturns,
  previewSourceReturnProof,
  confirmSourceReturnProof,
  getSourceReturnProofRequest,
  type InstrumentAnalysis,
  type InstrumentTotals,
} from "./sourceReturns";

afterEach(() => vi.unstubAllGlobals());

it("binds all proof originals to the multipart Preview and separates explicit save from GET recovery", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => "{}" });
  vi.stubGlobal("fetch", fetcher);
  const sources = [{ intake_id: 2, manifest_digest: "a".repeat(64) }];
  const file = new File(["synthetic"], "synthetic.xml", { type: "application/xml" });
  await previewSourceReturnProof("SYNTH", sources, [file]);
  const form = fetcher.mock.calls[0][1].body as FormData;
  expect(JSON.parse(String(form.get("request")))).toEqual({
    source_account: "SYNTH",
    expected_sources: sources,
  });
  expect(form.getAll("files")).toHaveLength(1);
  await confirmSourceReturnProof(
    "SYNTH",
    { form_token: "token", preview_digest: "digest" } as Parameters<
      typeof confirmSourceReturnProof
    >[1],
    "request-id",
  );
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({
    source_account: "SYNTH",
    form_token: "token",
    preview_digest: "digest",
    request_id: "request-id",
    attested: true,
  });
  await getSourceReturnProofRequest("request-id");
  expect(fetcher.mock.calls[2][0]).toBe("/api/source-returns/proofs/requests/request-id");
  expect(fetcher.mock.calls[2][1].method).toBeUndefined();
});

it("keeps the legacy call and sends an exact optional interval without converting money or rates", async () => {
  const analysis: Pick<InstrumentAnalysis, "pnl" | "modified_dietz"> = {
    pnl: { value: 10000, status: "supported", reason_codes: [], assumptions: [] },
    modified_dietz: {
      value: "0.15",
      status: "supported",
      reason_codes: [],
      assumptions: [],
      method: "modified_dietz",
      approximate: true,
      annualized: false,
      capital_days: 2000000,
    },
  };
  const legacy: Pick<InstrumentTotals, "return_percent" | "capital_base_kopecks"> = {
    return_percent: "10",
    capital_base_kopecks: 100000,
  };
  const response = { instruments: [{ analysis, months: [legacy] }] };
  const fetcher = vi
    .fn()
    .mockResolvedValue({ ok: true, status: 200, text: async () => JSON.stringify(response) });
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController();
  await getSourceInstrumentReturns("native-account", controller.signal);
  expect(fetcher.mock.calls[0][0]).toBe(
    "/api/source-returns/instruments?source_account=native-account",
  );
  const result = await getSourceInstrumentReturns("native-account", controller.signal, {
    isin: "ZZ0000000011",
    opening_date: "2030-03-31",
    closing_date: "2030-04-30",
  });
  const url = new URL(fetcher.mock.calls[1][0], "http://localhost");
  expect(Object.fromEntries(url.searchParams)).toEqual({
    source_account: "native-account",
    isin: "ZZ0000000011",
    opening_date: "2030-03-31",
    closing_date: "2030-04-30",
  });
  expect(fetcher.mock.calls[1][1].signal).toBe(controller.signal);
  expect(result.instruments[0].analysis.modified_dietz.value).toBe("0.15");
  expect(result.instruments[0].analysis.pnl.value).toBe(10000);
  expect(result.instruments[0].months[0].return_percent).toBe("10");
});
