"""Read-only import preview. Zero persistence writes. No network."""

from __future__ import annotations

from collections import defaultdict

from hermes_finance.statement_import.dto import (
    AccountMappingInput,
    DuplicateClass,
    HermesAccountView,
    HermesInstrumentView,
    IncomeReportPreview,
    InstrumentMappingInput,
    ParsedReport,
    ParsedRow,
    PreviewRow,
    PriorEventView,
    ReportStatus,
    RowStatus,
)
from hermes_finance.statement_import.extract import extract_pdf_text_layer
from hermes_finance.statement_import.identity import mapped_identity_key, normalize_isin
from hermes_finance.statement_import.parse import parse_income_report
from hermes_finance.statement_import.schema import (
    PROVIDER,
    REASON_ACCOUNT_AMBIGUOUS,
    REASON_ACCOUNT_UNMAPPED,
    REASON_INSTRUMENT_AMBIGUOUS,
    REASON_INSTRUMENT_UNMATCHED,
    REASON_MISSING_ISIN,
)

_TERMINAL = {RowStatus.MALFORMED, RowStatus.UNSUPPORTED}


def _account_maps(
    mappings: tuple[AccountMappingInput, ...],
) -> tuple[dict[str, int], set[str]]:
    resolved: dict[str, int] = {}
    conflicting: set[str] = set()
    for entry in mappings:
        ref = entry.provider_account_ref.strip()
        if not ref:
            continue
        if ref in resolved and resolved[ref] != entry.hermes_account_id:
            conflicting.add(ref)
        elif ref not in resolved:
            resolved[ref] = entry.hermes_account_id
    return resolved, conflicting


def _instrument_maps(
    mappings: tuple[InstrumentMappingInput, ...],
) -> tuple[dict[str, int], set[str]]:
    resolved: dict[str, int] = {}
    conflicting: set[str] = set()
    for entry in mappings:
        isin = normalize_isin(entry.isin)
        if not isin:
            continue
        if isin in resolved and resolved[isin] != entry.hermes_instrument_id:
            conflicting.add(isin)
        elif isin not in resolved:
            resolved[isin] = entry.hermes_instrument_id
    return resolved, conflicting


def _isin_index(
    instruments: tuple[HermesInstrumentView, ...],
) -> dict[str, list[HermesInstrumentView]]:
    index: dict[str, list[HermesInstrumentView]] = defaultdict(list)
    for instrument in instruments:
        isin = normalize_isin(instrument.isin)
        if isin:
            index[isin].append(instrument)
    return index


def _resolve_account(
    *,
    provider_account_ref: str | None,
    resolved: dict[str, int],
    conflicting: set[str],
    hermes_ids: set[int],
) -> tuple[int | None, str | None]:
    if not provider_account_ref:
        return None, REASON_ACCOUNT_UNMAPPED
    if provider_account_ref in conflicting:
        return None, REASON_ACCOUNT_AMBIGUOUS
    if provider_account_ref not in resolved:
        return None, REASON_ACCOUNT_UNMAPPED
    hermes_id = resolved[provider_account_ref]
    if hermes_id not in hermes_ids:
        return None, REASON_ACCOUNT_AMBIGUOUS
    return hermes_id, None


def _resolve_instrument(
    *,
    isin: str | None,
    explicit: dict[str, int],
    conflicting: set[str],
    isin_index: dict[str, list[HermesInstrumentView]],
    hermes_ids: set[int],
    hermes_isin_by_id: dict[int, str | None],
) -> tuple[int | None, str | None]:
    if not isin:
        return None, REASON_MISSING_ISIN
    if isin in conflicting:
        return None, REASON_INSTRUMENT_AMBIGUOUS
    if isin in explicit:
        hermes_id = explicit[isin]
        if hermes_id not in hermes_ids:
            return hermes_id, REASON_INSTRUMENT_AMBIGUOUS
        hermes_isin = hermes_isin_by_id.get(hermes_id)
        if hermes_isin is not None and hermes_isin != isin:
            return hermes_id, REASON_INSTRUMENT_AMBIGUOUS
        return hermes_id, None
    matches = isin_index.get(isin, [])
    if len(matches) == 1:
        return matches[0].instrument_id, None
    if len(matches) > 1:
        return None, REASON_INSTRUMENT_AMBIGUOUS
    return None, REASON_INSTRUMENT_UNMATCHED


def _duplicate_class(
    natural_identity: str | None,
    fingerprint: str | None,
    prior: tuple[PriorEventView, ...],
) -> DuplicateClass | None:
    if not natural_identity or not fingerprint:
        return None
    for event in prior:
        if event.natural_identity != natural_identity:
            continue
        if event.material_fingerprint == fingerprint:
            return DuplicateClass.DUPLICATE
        return DuplicateClass.CORRECTION
    return None


def _preview_row(
    parsed: ParsedRow,
    *,
    account_id: int | None,
    instrument_id: int | None,
    status: RowStatus,
    reason: str | None,
    prior: tuple[PriorEventView, ...],
) -> PreviewRow:
    natural = mapped_identity_key(
        hermes_account_id=account_id,
        event_kind=parsed.event_kind,
        isin=parsed.isin,
        record_date=parsed.record_date,
    )
    return PreviewRow(
        status=status,
        event_kind=parsed.event_kind,
        hermes_account_id=account_id,
        hermes_instrument_id=instrument_id,
        provider_account_ref=parsed.provider_account_ref,
        isin=parsed.isin,
        record_date=parsed.record_date,
        event_date=parsed.event_date,
        quantity=parsed.quantity,
        per_unit=parsed.per_unit,
        gross_amount=parsed.gross_amount,
        gross_currency=parsed.gross_currency,
        tax_amount=parsed.tax_amount,
        tax_available=parsed.tax_available,
        tax_rate=parsed.tax_rate,
        net_amount=parsed.net_amount,
        net_currency=parsed.net_currency,
        natural_identity=natural,
        material_fingerprint=parsed.material_fingerprint,
        duplicate_class=_duplicate_class(natural, parsed.material_fingerprint, prior),
        reason=reason,
    )


def build_preview_from_parsed(
    parsed: ParsedReport,
    *,
    hermes_accounts: tuple[HermesAccountView, ...],
    hermes_instruments: tuple[HermesInstrumentView, ...],
    account_mappings: tuple[AccountMappingInput, ...],
    instrument_mappings: tuple[InstrumentMappingInput, ...] = (),
    prior_events: tuple[PriorEventView, ...] = (),
) -> IncomeReportPreview:
    if (
        parsed.status is not ReportStatus.APPLICABLE
        and parsed.status is not ReportStatus.UNSUPPORTED
    ):
        return IncomeReportPreview(
            status=parsed.status,
            provider=PROVIDER,
            document_sha256=parsed.document_sha256,
            rows=(),
            warnings=parsed.warnings,
            reason=parsed.reason,
        )

    accounts_resolved, accounts_conflict = _account_maps(account_mappings)
    instruments_resolved, instruments_conflict = _instrument_maps(instrument_mappings)
    hermes_account_ids = {account.account_id for account in hermes_accounts}
    hermes_instrument_ids = {instrument.instrument_id for instrument in hermes_instruments}
    isin_index = _isin_index(hermes_instruments)
    hermes_isin_by_id = {
        instrument.instrument_id: normalize_isin(instrument.isin)
        for instrument in hermes_instruments
    }

    rows: list[PreviewRow] = []
    for parsed_row in parsed.rows:
        account_id, account_reason = _resolve_account(
            provider_account_ref=parsed_row.provider_account_ref,
            resolved=accounts_resolved,
            conflicting=accounts_conflict,
            hermes_ids=hermes_account_ids,
        )
        instrument_id, instrument_reason = _resolve_instrument(
            isin=parsed_row.isin,
            explicit=instruments_resolved,
            conflicting=instruments_conflict,
            isin_index=isin_index,
            hermes_ids=hermes_instrument_ids,
            hermes_isin_by_id=hermes_isin_by_id,
        )
        if parsed_row.status in _TERMINAL:
            rows.append(
                _preview_row(
                    parsed_row,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    status=parsed_row.status,
                    reason=parsed_row.reason,
                    prior=prior_events,
                )
            )
            continue
        if parsed_row.status is RowStatus.AMBIGUOUS:
            rows.append(
                _preview_row(
                    parsed_row,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    status=RowStatus.AMBIGUOUS,
                    reason=parsed_row.reason,
                    prior=prior_events,
                )
            )
            continue
        if (
            account_reason == REASON_ACCOUNT_AMBIGUOUS
            or instrument_reason == REASON_INSTRUMENT_AMBIGUOUS
        ):
            reason = account_reason or instrument_reason
            rows.append(
                _preview_row(
                    parsed_row,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    status=RowStatus.AMBIGUOUS,
                    reason=reason,
                    prior=prior_events,
                )
            )
            continue
        if account_reason or instrument_reason:
            reason = account_reason or instrument_reason
            rows.append(
                _preview_row(
                    parsed_row,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    status=RowStatus.UNMATCHED,
                    reason=reason,
                    prior=prior_events,
                )
            )
            continue
        rows.append(
            _preview_row(
                parsed_row,
                account_id=account_id,
                instrument_id=instrument_id,
                status=RowStatus.MATCHED,
                reason=None,
                prior=prior_events,
            )
        )

    return IncomeReportPreview(
        status=parsed.status,
        provider=PROVIDER,
        document_sha256=parsed.document_sha256,
        rows=tuple(rows),
        warnings=parsed.warnings,
        reason=parsed.reason,
    )


def preview_income_report(
    document: bytes,
    *,
    hermes_accounts: tuple[HermesAccountView, ...],
    hermes_instruments: tuple[HermesInstrumentView, ...],
    account_mappings: tuple[AccountMappingInput, ...] = (),
    instrument_mappings: tuple[InstrumentMappingInput, ...] = (),
    prior_events: tuple[PriorEventView, ...] = (),
) -> IncomeReportPreview:
    extracted = extract_pdf_text_layer(document)
    parsed = parse_income_report(extracted)
    return build_preview_from_parsed(
        parsed,
        hermes_accounts=hermes_accounts,
        hermes_instruments=hermes_instruments,
        account_mappings=account_mappings,
        instrument_mappings=instrument_mappings,
        prior_events=prior_events,
    )
