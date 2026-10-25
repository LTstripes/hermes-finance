import { afterEach, expect, it, vi } from "vitest";
import {
  getSourceQuantityBases,
  previewSourcePayouts,
  type SourcePayoutPreview,
} from "./sourcePayoutPreview";

afterEach(() => vi.unstubAllGlobals());

it("reads quantity candidates by exact account, ISIN and upper date without provider POST", async () => {
  const data = {
    bases: [{ as_of: "2030-09-30", quantity: "9007199254740993.001", reason_codes: [] }],
  };
  const fetcher = vi.fn(
    async (_input: RequestInfo | URL) =>
      new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fetcher);
  expect(await getSourceQuantityBases("SYN/A", "RU000A000001", "2030-10-31")).toEqual(data);
  expect(fetcher.mock.calls[0][0]).toBe(
    "/api/source-returns/quantity-bases?source_account=SYN%2FA&isin=RU000A000001&on_or_before=2030-10-31",
  );
});

it("sends exact native scope and preserves Decimal, UNKNOWN, provenance and reconciliation", async () => {
  const payload = { source_account: "native-account", isin: "ZZ0000000011", as_of: "2030-04-30" };
  const response: SourcePayoutPreview = {
    ...payload,
    authority: "provisional",
    financial_authority: "none",
    native_source_account: "native-account",
    account_id: null,
    instrument_id: 1,
    quantity: "2.5",
    quantity_authority: "source_observed",
    assumptions: ["fixed_source_quantity_not_entitlement"],
    quantity_references: ["position:1:0:closing"],
    source_references: [],
    dependency_fingerprint: "digest",
    reason_codes: [],
    provider: "t_invest",
    instrument_uid: "uid",
    actuals: [],
    reconciliation_reasons: [],
    rows: [
      {
        identity_key: "event:1",
        event_kind: "dividend",
        payment_date: "2030-05-01",
        provider_status: null,
        source_method: "GetDividends",
        per_unit_amount: "1.2345",
        currency: "RUB",
        announced_amount_kopecks: "9007199254740993",
        personal_tax_known: false,
        status: "possible_paid",
        countable_future: false,
        actual_event_keys: ["money:1"],
        reason_codes: ["actual_provider_identity_unproven"],
      },
    ],
    failures: [],
  };
  const fetcher = vi
    .fn()
    .mockResolvedValue({ ok: true, status: 200, text: async () => JSON.stringify(response) });
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController();
  expect(await previewSourcePayouts(payload, controller.signal)).toEqual(response);
  const unknown = structuredClone(response);
  unknown.quantity = null;
  unknown.rows[0].announced_amount_kopecks = null;
  fetcher.mockResolvedValueOnce({
    ok: true,
    status: 200,
    text: async () => JSON.stringify(unknown),
  });
  expect(await previewSourcePayouts(payload)).toEqual(unknown);
  expect(fetcher.mock.calls[0][0]).toBe("/api/source-returns/payout-preview");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(payload);
  expect(fetcher.mock.calls[0][1].signal).toBe(controller.signal);
});
