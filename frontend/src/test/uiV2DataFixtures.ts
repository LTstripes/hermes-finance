import type { ProviderCapabilities } from "../api/providerCapabilities";
import type { FreshnessProvenanceSummary, ReportingMonth } from "../api/types";

import { uiV2Months } from "./uiV2Fixtures";

export function makeUiV2Freshness(
  month: ReportingMonth = uiV2Months[1],
): FreshnessProvenanceSummary {
  return {
    reporting_month: month,
    evaluated_on: "2031-08-18",
    quote_valuation_target_date: "2031-08-18",
    generated_at: "2031-08-18T09:30:00+00:00",
    providers: ["t_invest"],
    reasons: [
      {
        code: "quote_stale",
        severity: "warning",
        message: "Есть применённые котировки старше окна актуальности.",
      },
    ],
    families: [
      {
        family_id: "market_quotes",
        title: "Рыночные котировки",
        status: "stale",
        providers: ["t_invest"],
        coverage: {
          row_count: 2,
          current_count: 1,
          stale_count: 1,
          unavailable_count: 0,
          unknown_count: 0,
          missing_count: 0,
          manual_count: 0,
          provider_count: 1,
        },
        reasons: [
          {
            code: "quote_stale",
            severity: "warning",
            message: "Есть применённые котировки старше окна актуальности.",
          },
        ],
        items: [
          {
            item_kind: "quote",
            label: "Synthetic Stock",
            freshness_status: "stale",
            source_kind: "t_invest",
            source_timestamp_kind: "price_date",
            source_date: "2031-08-01",
            source_datetime: null,
            fetched_at: "2031-08-10T10:00:00+00:00",
            import_apply_time: "2031-08-10T11:00:00+00:00",
            local_edit_time: "2031-08-10T11:00:00+00:00",
            reason_codes: ["quote_stale"],
            account_name: "Broker",
            instrument_name: "Synthetic Stock",
          },
        ],
      },
      {
        family_id: "t_invest_payouts",
        title: "Выплаты T-Invest",
        status: "not_applicable",
        providers: ["t_invest"],
        coverage: {
          row_count: 1,
          current_count: 0,
          stale_count: 0,
          unavailable_count: 0,
          unknown_count: 0,
          missing_count: 0,
          manual_count: 0,
          provider_count: 1,
        },
        reasons: [
          {
            code: "payout_event_present",
            severity: "info",
            message: "В месяце есть принятые выплаты T-Invest.",
          },
          {
            code: "payout_not_freshness_classified",
            severity: "info",
            message:
              "Дата выплаты — событие, а не котировка; по возрасту она не помечается устаревшей.",
          },
        ],
        items: [
          {
            item_kind: "payout",
            label: "Synthetic Bond · coupon",
            freshness_status: "not_applicable",
            source_kind: "t_invest",
            source_timestamp_kind: "payment_date",
            source_date: "2031-08-15",
            source_datetime: null,
            fetched_at: "2031-08-10T10:00:00+00:00",
            import_apply_time: "2031-08-10T11:30:00+00:00",
            local_edit_time: null,
            reason_codes: ["payout_not_freshness_classified"],
            account_name: "Broker",
            instrument_name: "Synthetic Bond",
          },
        ],
      },
      {
        family_id: "alfa_statement_payouts",
        title: "Выписка Alfa PDF",
        status: "not_applicable",
        providers: ["alfa_pdf"],
        coverage: {
          row_count: 1,
          current_count: 0,
          stale_count: 0,
          unavailable_count: 0,
          unknown_count: 0,
          missing_count: 0,
          manual_count: 0,
          provider_count: 1,
        },
        reasons: [
          {
            code: "statement_event_present",
            severity: "info",
            message: "В месяце есть принятые события выписки Alfa.",
          },
          {
            code: "statement_not_freshness_classified",
            severity: "info",
            message:
              "Дата в выписке — событие документа, а не котировка; по возрасту она не устаревает.",
          },
        ],
        items: [
          {
            item_kind: "statement_event",
            label: "Synthetic Bond · coupon",
            freshness_status: "not_applicable",
            source_kind: "alfa_pdf",
            source_timestamp_kind: "event_date",
            source_date: "2031-08-12",
            source_datetime: null,
            fetched_at: null,
            import_apply_time: "2031-08-13T09:00:00+00:00",
            local_edit_time: "2031-08-13T09:05:00+00:00",
            reason_codes: ["statement_not_freshness_classified"],
            account_name: "Broker",
            instrument_name: "Synthetic Bond",
          },
        ],
      },
      {
        family_id: "alfa_pro_positions",
        title: "Позиции Alfa PRO",
        status: "not_applicable",
        providers: ["alfa_pro"],
        coverage: {
          row_count: 1,
          current_count: 0,
          stale_count: 0,
          unavailable_count: 0,
          unknown_count: 0,
          missing_count: 0,
          manual_count: 0,
          provider_count: 1,
        },
        reasons: [
          {
            code: "alfa_pro_baseline_present",
            severity: "info",
            message: "В месяце есть подтверждённый владельцем текущий срез Alfa PRO.",
          },
          {
            code: "alfa_pro_observation_not_freshness_classified",
            severity: "info",
            message:
              "Время наблюдения Alfa PRO сохранено; confirmed_at — время применения, не актуальность.",
          },
        ],
        items: [
          {
            item_kind: "alfa_pro_baseline",
            label: "Текущий срез Alfa PRO",
            freshness_status: "not_applicable",
            source_kind: "alfa_pro",
            source_timestamp_kind: "source_as_of",
            source_date: "2031-08-18",
            source_datetime: "2031-08-18T09:00:00+00:00",
            fetched_at: "2031-08-18T09:05:00+00:00",
            import_apply_time: "2031-08-18T09:10:00+00:00",
            local_edit_time: null,
            reason_codes: ["alfa_pro_observation_not_freshness_classified"],
            account_name: null,
            instrument_name: null,
          },
        ],
      },
      {
        family_id: "manual_month_data",
        title: "Ручные значения месяца",
        status: "not_applicable",
        providers: [],
        coverage: {
          row_count: 1,
          current_count: 0,
          stale_count: 0,
          unavailable_count: 0,
          unknown_count: 0,
          missing_count: 0,
          manual_count: 1,
          provider_count: 0,
        },
        reasons: [],
        items: [
          {
            item_kind: "manual_group",
            label: "Касса",
            freshness_status: "not_applicable",
            source_kind: "manual",
            source_timestamp_kind: "not_applicable",
            source_date: null,
            source_datetime: null,
            fetched_at: null,
            import_apply_time: null,
            local_edit_time: "2031-08-10T12:00:00+00:00",
            reason_codes: [],
            account_name: null,
            instrument_name: null,
          },
        ],
      },
    ],
  };
}

export function makeUiV2ProviderCapabilities(): ProviderCapabilities[] {
  return [
    {
      provider: "t_invest",
      supported_instrument_types: ["stock", "bond"],
      capabilities: [
        {
          name: "quotes",
          status: "supported",
          limitations: ["official REST only"],
        },
      ],
      limitations: ["no trading"],
    },
  ];
}
