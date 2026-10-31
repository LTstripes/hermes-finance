/** Synthetic Owner-source protocol fixtures; no actual holdings or entry. */
import {
  GOLD_VERSION,
  type GoldDeclaration,
  type GoldHistory,
  type GoldIntent,
  type GoldPreview,
  type GoldReceipt,
  type GoldResult,
} from "./goldHistory";
export function goldIntentFixture(): GoldIntent {
  return {
    contract_version: GOLD_VERSION,
    account_id: 10,
    instrument_id: 20,
    expected_revision: 0,
    covered_from: "2044-01-01",
    covered_to: "2044-03-31",
    complete: true,
    zero_start: true,
    current_quantity: "2",
    current_quantity_date: "2044-03-31",
    provenance_reference: "SYNTHETIC-DOCUMENT",
    change_reason: null,
    events: [
      {
        event_id: "synthetic_buy",
        event_date: "2044-01-02",
        side: "BUY",
        grams: "2",
        amount_basis: "actual",
        amount_rub: "5000",
        unit_price_rub: null,
        fee_state: "known_zero",
        fee_rub: null,
      },
    ],
  };
}
export function goldDeclarationFixture(intent = goldIntentFixture()): GoldDeclaration {
  const { expected_revision: _revision, events, ...declaration } = intent;
  return {
    ...declaration,
    events: events.map((event) => ({
      event_id: event.event_id,
      event_date: event.event_date,
      side: event.side,
      grams: event.grams,
      amount_basis: event.amount_basis,
      unit_price_rub: event.unit_price_rub,
      fee_state: event.fee_state,
      amount_kopecks: "500000",
      separate_fee_kopecks: event.fee_state === "unknown" ? null : "0",
    })),
  };
}
export function goldResultFixture(): GoldResult {
  return {
    total_result_kopecks: "100000",
    realized_result_kopecks: "0",
    unrealized_result_kopecks: "100000",
    remaining_cost_kopecks: "500000",
    buy_amount_kopecks: "500000",
    sale_amount_kopecks: "0",
    separate_fees_kopecks: "0",
    net_sales_kopecks: "0",
    calculated_quantity: "2",
    declared_calculated_quantity: "2",
    valuation_kopecks: "600000",
    amount_basis: "actual",
    tax_treatment: "not_provided",
    method: "synthetic_server_gold",
    reason_codes: [],
    decomposition_reason_codes: [],
    total_reason_codes: [],
    realized_reason_codes: [],
    unrealized_reason_codes: [],
    period: { covered_from: "2044-01-01", covered_to: "2044-03-30" },
    valuation_date: "2044-03-30",
    valuation_basis: "saved_snapshot_quote",
    as_of_date: "2044-03-30",
  };
}
export function goldHistoryFixture(intent = goldIntentFixture()): GoldHistory {
  const declaration = goldDeclarationFixture(intent);
  return {
    contract_version: GOLD_VERSION,
    source_kind: "owner_manual_gold_history",
    authority: "owner_attestation",
    history_id: 50,
    revision: intent.expected_revision + 1,
    account_id: intent.account_id,
    instrument_id: intent.instrument_id,
    events_loaded: true,
    currentness: "current",
    declaration,
    events: declaration.events,
    valuation: {
      snapshot_id: 60,
      date: "2044-03-30",
      snapshot_date: "2044-03-31",
      price_date: "2044-03-30",
      quantity: "2",
      market_value_kopecks: "600000",
      price_source: "synthetic_saved",
    },
    result: goldResultFixture(),
    reason_codes: [],
    revisions: [
      { revision: intent.expected_revision + 1, declaration, accepted_at: "2044-04-01T00:00:00Z" },
    ],
  };
}
export function goldPreviewFixture(intent = goldIntentFixture()): GoldPreview {
  const history = goldHistoryFixture(intent);
  return {
    contract_version: GOLD_VERSION,
    source_kind: "owner_manual_gold_history",
    authority: "owner_attestation",
    action: intent.expected_revision ? "revise" : "create",
    history_id: intent.expected_revision ? 50 : null,
    expected_revision: intent.expected_revision,
    declaration: history.declaration,
    valuation: history.valuation,
    result: history.result,
    confirmation_digest: "a".repeat(64),
    can_apply: true,
  };
}
export function goldReceiptFixture(intent: GoldIntent, requestId: string): GoldReceipt {
  const history = goldHistoryFixture(intent);
  return {
    contract_version: GOLD_VERSION,
    request_id: requestId,
    accepted_revision: history.revision,
    history,
  };
}
