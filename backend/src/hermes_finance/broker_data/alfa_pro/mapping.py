"""Exact Alfa PRO v2.1 raw-field mapping for the production snapshot.

A field name is not evidence. Only official PDF wording is accepted.
Undocumented live fields such as account-kind extras are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException
from typing import Final

from hermes_finance.broker_data.dto import (
    BrokerAccount,
    BrokerCashBalance,
    BrokerPosition,
    BrokerSection,
    BrokerSubAccount,
)

OFFICIAL_API_SOURCE: Final = (
    "Alfa Investments PRO WebSocket API v2.1, "
    "https://alfadt.servicecdn.ru/alfadt/ad5/Alfa-Investments-Pro-API.pdf"
)


@dataclass(frozen=True, slots=True)
class AlfaFieldMapping:
    entity: str
    alfa_field: str
    official_meaning: str
    snapshot_field: str | None
    unit_assumption: str
    decision: str


FIELD_MAPPINGS: Final[tuple[AlfaFieldMapping, ...]] = (
    AlfaFieldMapping(
        entity="ClientAccountEntity",
        alfa_field="IdAccount",
        official_meaning="Идентификатор счёта",
        snapshot_field="provider_account_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientSubAccountEntity",
        alfa_field="IdSubAccount",
        official_meaning="Идентификатор субсчёта",
        snapshot_field="provider_subaccount_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientSubAccountEntity",
        alfa_field="IdAccount",
        official_meaning="Счёт клиента",
        snapshot_field="provider_account_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="SubAccountRazdelEntity",
        alfa_field="IdRazdel",
        official_meaning="Идентификатор портфеля",
        snapshot_field="provider_section_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="SubAccountRazdelEntity",
        alfa_field="IdAccount",
        official_meaning="Счёт клиента",
        snapshot_field="provider_account_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="SubAccountRazdelEntity",
        alfa_field="IdSubAccount",
        official_meaning="Субсчёт клиента",
        snapshot_field="provider_subaccount_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="SubAccountRazdelEntity",
        alfa_field="IdRazdelGroup",
        official_meaning="Группа портфелей: 1 РЦБ, 2 ФОРТС, 3 ВР, 4 НТР",
        snapshot_field="section_group",
        unit_assumption="official integer group code",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="SubAccountRazdelEntity",
        alfa_field="RCode",
        official_meaning="Код раздела",
        snapshot_field="section_code",
        unit_assumption="provider string code",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="IdAccount",
        official_meaning="Счёт",
        snapshot_field="provider_account_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="IdSubAccount",
        official_meaning="Субсчёт",
        snapshot_field="provider_subaccount_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="IdRazdel",
        official_meaning="Портфель",
        snapshot_field="provider_section_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="IdObject",
        official_meaning="Выпуск",
        snapshot_field="provider_instrument_id",
        unit_assumption="opaque provider object id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="TorgPos",
        official_meaning="Текущая позиция",
        snapshot_field="quantity",
        unit_assumption="provider quantity units; Decimal, not lots",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="Price",
        official_meaning="Текущая цена",
        snapshot_field="broker_unit_price",
        unit_assumption="provider price units as documented double/JSON number",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="UchPrice",
        official_meaning="Учётная цена",
        snapshot_field="accounting_price",
        unit_assumption="provider price units as documented double/JSON number",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="NKD",
        official_meaning="НКД (накопленный купонный доход)",
        snapshot_field="accrued_interest_nkd",
        unit_assumption="provider monetary units as documented double/JSON number",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="PSTNKD",
        official_meaning="НКД",
        snapshot_field=None,
        unit_assumption="insufficient to distinguish from NKD",
        decision="unresolved",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="NPLtoMarketCurPrice",
        official_meaning="Номинальная прибыль/убыток (НПУ)",
        snapshot_field="unrealized_result",
        unit_assumption="provider monetary units as documented double/JSON number",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="DailyPL",
        official_meaning="Текущая прибыль/убыток (ПУдн)",
        snapshot_field=None,
        unit_assumption="daily P/L is not the snapshot unrealized-result field",
        decision="unresolved",
    ),
    AlfaFieldMapping(
        entity="ClientPositionEntity",
        alfa_field="IsMoney",
        official_meaning="Деньги -- валютная позиция",
        snapshot_field="is_money",
        unit_assumption="boolean",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientBalanceEntity",
        alfa_field="IdAccount",
        official_meaning="Счёт клиента",
        snapshot_field="provider_account_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientBalanceEntity",
        alfa_field="IdSubAccount",
        official_meaning="Субсчёт клиента",
        snapshot_field="provider_subaccount_id",
        unit_assumption="opaque provider id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientBalanceEntity",
        alfa_field="IdRazdelGroup",
        official_meaning="Группа портфелей",
        snapshot_field="section_group",
        unit_assumption="official integer group code",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientBalanceEntity",
        alfa_field="Money",
        official_meaning="Рубли",
        snapshot_field="amount",
        unit_assumption="RUB cash as documented; JSON number → Decimal",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="ClientBalanceEntity",
        alfa_field="PortfolioCost",
        official_meaning="Стоимость портфеля",
        snapshot_field=None,
        unit_assumption="portfolio-level; not a position market value",
        decision="unresolved",
    ),
    AlfaFieldMapping(
        entity="AssetInfoEntity",
        alfa_field="IdObject",
        official_meaning="Идентификатор выпуска",
        snapshot_field="provider_instrument_id",
        unit_assumption="opaque provider object id",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="AssetInfoEntity",
        alfa_field="ISIN",
        official_meaning="Международный идентификатор",
        snapshot_field="isin",
        unit_assumption="ISIN string when present",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="AssetInfoEntity",
        alfa_field="Ticker",
        official_meaning="Биржевой тикер",
        snapshot_field="ticker",
        unit_assumption="display/reconciliation hint only",
        decision="accepted",
    ),
    AlfaFieldMapping(
        entity="AssetInfoEntity",
        alfa_field="Name",
        official_meaning="Наименование",
        snapshot_field="display_name",
        unit_assumption="display/reconciliation hint only",
        decision="accepted",
    ),
)


def as_decimal(value: object) -> Decimal | None:
    """Exact numeric observation. Binary float is rejected, not recovered."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            parsed = Decimal(value)
        except DecimalException:
            return None
        return parsed if parsed.is_finite() else None
    return None


def as_id(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def as_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def account_has_undocumented_kind_fields(row: dict[str, object]) -> bool:
    documented = {"IdAccount", "DataId", "Version", "Operation"}
    extra = {key for key in row if key not in documented}
    return bool(extra)


def normalize_account(row: dict[str, object]) -> BrokerAccount | None:
    account_id = as_id(row.get("IdAccount"))
    if account_id is None:
        return None
    return BrokerAccount(provider_account_id=account_id)


def normalize_subaccount(row: dict[str, object]) -> BrokerSubAccount | None:
    subaccount_id = as_id(row.get("IdSubAccount"))
    if subaccount_id is None:
        return None
    return BrokerSubAccount(
        provider_subaccount_id=subaccount_id,
        provider_account_id=as_id(row.get("IdAccount")),
    )


def normalize_section(row: dict[str, object]) -> BrokerSection | None:
    section_id = as_id(row.get("IdRazdel"))
    if section_id is None:
        return None
    return BrokerSection(
        provider_section_id=section_id,
        provider_account_id=as_id(row.get("IdAccount")),
        provider_subaccount_id=as_id(row.get("IdSubAccount")),
        section_group=as_int(row.get("IdRazdelGroup")),
        section_code=as_text(row.get("RCode")),
    )


def normalize_position(
    row: dict[str, object],
    *,
    instruments: dict[str, dict[str, object]],
) -> BrokerPosition | None:
    object_id = as_id(row.get("IdObject"))
    info = instruments.get(object_id or "") if object_id is not None else None
    mapped: list[str] = []
    quantity = as_decimal(row.get("TorgPos"))
    if quantity is not None:
        mapped.append("quantity=TorgPos")
    unit_price = as_decimal(row.get("Price"))
    if unit_price is not None:
        mapped.append("broker_unit_price=Price")
    accounting = as_decimal(row.get("UchPrice"))
    if accounting is not None:
        mapped.append("accounting_price=UchPrice")
    nkd = as_decimal(row.get("NKD"))
    if nkd is not None:
        mapped.append("accrued_interest_nkd=NKD")
    unrealized = as_decimal(row.get("NPLtoMarketCurPrice"))
    if unrealized is not None:
        mapped.append("unrealized_result=NPLtoMarketCurPrice")
    is_money = as_bool(row.get("IsMoney"))
    if is_money is not None:
        mapped.append("is_money=IsMoney")
    isin = as_text(info.get("ISIN")) if info else None
    ticker = as_text(info.get("Ticker")) if info else None
    name = as_text(info.get("Name")) if info else None
    if isin is not None:
        mapped.append("isin=AssetInfoEntity.ISIN")
    return BrokerPosition(
        provider_account_id=as_id(row.get("IdAccount")),
        provider_subaccount_id=as_id(row.get("IdSubAccount")),
        provider_section_id=as_id(row.get("IdRazdel")),
        provider_instrument_id=object_id,
        isin=isin,
        ticker=ticker,
        display_name=name,
        quantity=quantity,
        broker_unit_price=unit_price,
        market_value=None,
        accounting_price=accounting,
        accrued_interest_nkd=nkd,
        unrealized_result=unrealized,
        is_money=is_money,
        mapped_fields=tuple(mapped),
    )


def normalize_cash(row: dict[str, object]) -> BrokerCashBalance | None:
    amount = as_decimal(row.get("Money"))
    mapped: list[str] = []
    if amount is not None:
        mapped.append("amount=Money")
        mapped.append("currency=RUB_from_official_Money_rubles")
    return BrokerCashBalance(
        provider_account_id=as_id(row.get("IdAccount")),
        provider_subaccount_id=as_id(row.get("IdSubAccount")),
        currency="RUB" if amount is not None else None,
        amount=amount,
        section_group=as_int(row.get("IdRazdelGroup")),
        mapped_fields=tuple(mapped),
    )
