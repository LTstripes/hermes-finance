import type { BrokerMonthReadback } from "../api/brokerMonths";

/** Fictional original-bound GET response; shared by component and desktop fixtures. */
export function makeCapitalDraft(accountId = 3, monthId = 12): BrokerMonthReadback {
  return {
    contract_version: "broker_month_v1",
    request_id: `synthetic-draft-${accountId}-${monthId}`,
    reporting_month_id: monthId,
    account_id: accountId,
    import_id: 501,
    confirmation_digest: "b".repeat(64),
    status: "draft",
    exceptions: ["money_semantics_unsupported", "instrument_currency_unknown"],
    bookkeeping_ready: false,
    coverage_state: "unknown",
    accepted: {
      position_ids: [701],
      cash_id: 702,
      trade_ids: [],
      source_digest: "c".repeat(64),
      projection_digest: "d".repeat(64),
      document: {
        provider: "mybroker",
        parser: "mybroker-s1-v2",
        document_sha256: "a".repeat(64),
        filename_account: "SYNTHETIC-ALIAS",
        covered_from: "2031-08-01",
        covered_to: "2031-08-31",
        source_accounts: ["SYNTHETIC-ALIAS"],
        section_inventory: { positions: 1, rub_money: 1 },
        positions: [
          {
            ordinal: 1,
            source_account: "SYNTHETIC-ALIAS",
            isin: "SYNTHETIC-ISIN-A",
            actual_quantity: "10.000000",
            forward_quantity: "10",
            beginning_value: null,
            ending_value: "1234.56",
          },
        ],
        rub_money: [
          {
            ordinal: 1,
            source_account: "SYNTHETIC-ALIAS",
            currency: "RUB",
            beginning_amount: "0.00",
            ending_amount: "789.01",
          },
        ],
        trades: [],
        money: [
          {
            ordinal: 1,
            kind: "unsupported",
            source_account: "SYNTHETIC-ALIAS",
            amount: "99999.99",
            currency: "RUB",
          },
        ],
      },
    },
  };
}
