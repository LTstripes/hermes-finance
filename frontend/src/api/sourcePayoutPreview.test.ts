import { afterEach, expect, it, vi } from "vitest";
import { previewSourcePayouts, type SourcePayoutPreview } from "./sourcePayoutPreview";

afterEach(() => vi.unstubAllGlobals());

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
        announced_amount_kopecks: null,
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
  expect(fetcher.mock.calls[0][0]).toBe("/api/source-returns/payout-preview");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(payload);
  expect(fetcher.mock.calls[0][1].signal).toBe(controller.signal);
});
