# R06-03 — Alfa PRO v2.1 field mapping for the production snapshot

**Date:** 2026-08-20
**Task:** R06-03 / issue #79
**Official source:** Alfa Investments PRO WebSocket API v2.1
`https://alfadt.servicecdn.ru/alfadt/ad5/Alfa-Investments-Pro-API.pdf`
PDF Title metadata: `Альфа-Инвестиции PRO API v.2.1`

This note is the mapping gate required by accepted ADR 0013. A field name is not evidence. Live R06-01 field presence is not an accepted semantic. R06-02R / issue #75 left `IIAType` and numeric operation types `3`/`14` unresolved; those are not inferred here.

The production adapter does not query historical operation entities.

## Accepted mappings

| Alfa entity | Alfa field | Official wording | Snapshot field | Units |
|---|---|---|---|---|
| ClientAccountEntity | IdAccount | Идентификатор счёта | provider_account_id | opaque id |
| ClientSubAccountEntity | IdSubAccount | Идентификатор субсчёта | provider_subaccount_id | opaque id |
| ClientSubAccountEntity | IdAccount | Счёт клиента | provider_account_id | opaque id |
| SubAccountRazdelEntity | IdRazdel | Идентификатор портфеля | provider_section_id | opaque id |
| SubAccountRazdelEntity | IdAccount | Счёт клиента | provider_account_id | opaque id |
| SubAccountRazdelEntity | IdSubAccount | Субсчёт клиента | provider_subaccount_id | opaque id |
| SubAccountRazdelEntity | IdRazdelGroup | Группа портфелей 1–4 | section_group | official int |
| SubAccountRazdelEntity | RCode | Код раздела | section_code | string |
| ClientPositionEntity | IdAccount / IdSubAccount / IdRazdel / IdObject | Счёт / Субсчёт / Портфель / Выпуск | provider_* ids | opaque id |
| ClientPositionEntity | TorgPos | Текущая позиция | quantity | Decimal quantity |
| ClientPositionEntity | Price | Текущая цена | broker_unit_price | provider price number |
| ClientPositionEntity | UchPrice | Учётная цена | accounting_price | provider price number |
| ClientPositionEntity | NKD | НКД (накопленный купонный доход) | accrued_interest_nkd | provider money number |
| ClientPositionEntity | NPLtoMarketCurPrice | Номинальная прибыль/убыток (НПУ) | unrealized_result | provider money number |
| ClientPositionEntity | IsMoney | Деньги — валютная позиция | is_money | bool |
| ClientBalanceEntity | Money | Рубли | amount + currency RUB | RUB cash |
| ClientBalanceEntity | IdAccount / IdSubAccount / IdRazdelGroup | Счёт / Субсчёт / Группа портфелей | provider refs | ids / group int |
| AssetInfoEntity | ISIN / Ticker / Name / IdObject | Международный идентификатор / тикер / наименование / выпуск | isin, ticker, display_name, provider_instrument_id | reconciliation metadata |

JSON financial numbers are decoded with `parse_float=Decimal` at the payload boundary. Binary `float` is rejected, not recovered via `Decimal(str(float))`.

`source_as_of` is a timezone-aware **local observation time**. The official current-state entities do not document an authoritative snapshot timestamp.

## Unresolved — kept None / ignored

| Alfa field | Official wording | Why not mapped |
|---|---|---|
| ClientAccountEntity extras (including undocumented live account-kind fields) | not in v2.1 schema (schema lists only IdAccount) | IIS remains owner-controlled; no inference from name/code/substring |
| ClientPositionEntity.PSTNKD | НКД | insufficient to distinguish from documented NKD |
| ClientPositionEntity.DailyPL | Текущая прибыль/убыток (ПУдн) | daily P/L is not the unrealized-result mapping |
| ClientBalanceEntity.PortfolioCost | Стоимость портфеля | portfolio-level; not a position market value |
| position market_value | (none) | no official position market-value field |

Hermes must not compute a silent `TorgPos * Price` stand-in for provider market value.

## Explicitly out of this adapter

- Historical operation entities and their type codes
- `#Order.*`, limits, archive, order book, trade tape
- Persistence, reconciliation, apply, API/UI
