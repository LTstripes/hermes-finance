"""R06-07 Alfa depository income-report parser + read-only preview."""

from __future__ import annotations

import ast
import hashlib
import inspect
from decimal import Decimal
from pathlib import Path

import pytest
from _statement_pdf import (
    build_blank_pdf,
    build_encrypted_pdf,
    build_income_report_pdf,
    build_text_pdf,
    build_wrong_report_pdf,
)

from hermes_finance.statement_import import (
    REPORT_TITLE,
    AccountMappingInput,
    DuplicateClass,
    HermesAccountView,
    HermesInstrumentView,
    InstrumentMappingInput,
    PriorEventView,
    ReportStatus,
    RowStatus,
    extract_pdf_text_layer,
    parse_income_report,
    preview_income_report,
)
from hermes_finance.statement_import.extract import MAX_PDF_BYTES, MAX_PDF_PAGES
from hermes_finance.statement_import.identity import document_sha256
from hermes_finance.statement_import.money import parse_decimal

SYN_ISIN = "RU000SYN00001"
SYN_DEPO = "SYN-DEPO-001"
PRIVATE_MARKERS = (
    "40817810100000000000",
    "SYNTHETIC BANK",
    "Synthetic Equity One",
    "12,00",
)


def _accounts() -> tuple[HermesAccountView, ...]:
    return (
        HermesAccountView(account_id=10, account_type="brokerage", name="Synthetic Broker"),
        HermesAccountView(account_id=11, account_type="iis", name="Synthetic IIS"),
    )


def _instruments() -> tuple[HermesInstrumentView, ...]:
    return (
        HermesInstrumentView(
            instrument_id=20,
            isin=SYN_ISIN,
            name="Ignored Name",
            ticker="IGNORED",
        ),
    )


def _account_map() -> tuple[AccountMappingInput, ...]:
    return (AccountMappingInput(hermes_account_id=10, provider_account_ref=SYN_DEPO),)


def _preview(document: bytes, **kwargs: object):
    return preview_income_report(
        document,
        hermes_accounts=kwargs.get("hermes_accounts", _accounts()),  # type: ignore[arg-type]
        hermes_instruments=kwargs.get("hermes_instruments", _instruments()),  # type: ignore[arg-type]
        account_mappings=kwargs.get("account_mappings", _account_map()),  # type: ignore[arg-type]
        instrument_mappings=kwargs.get("instrument_mappings", ()),  # type: ignore[arg-type]
        prior_events=kwargs.get("prior_events", ()),  # type: ignore[arg-type]
    )


def _row(**overrides: str) -> dict[str, str]:
    return overrides


def test_report_family_recognition() -> None:
    preview = _preview(build_income_report_pdf())
    assert preview.status is ReportStatus.APPLICABLE
    assert preview.rows[0].status is RowStatus.MATCHED
    assert preview.rows[0].event_kind == "dividend"


def test_wrong_report_rejected() -> None:
    preview = _preview(build_wrong_report_pdf())
    assert preview.status is ReportStatus.NON_APPLICABLE
    assert preview.rows == ()
    assert preview.reason == "wrong_report_family"


def test_no_text_layer_rejected_without_ocr() -> None:
    preview = _preview(build_blank_pdf())
    assert preview.status is ReportStatus.MALFORMED
    assert preview.reason == "pdf_has_no_usable_text_layer"


def test_encrypted_pdf_rejected() -> None:
    preview = _preview(build_encrypted_pdf())
    assert preview.status is ReportStatus.MALFORMED
    assert preview.reason == "encrypted_pdf"


def test_oversized_pdf_rejected() -> None:
    payload = b"%PDF-1.4\n" + (b"x" * (MAX_PDF_BYTES + 1))
    preview = _preview(payload)
    assert preview.status is ReportStatus.MALFORMED
    assert preview.reason == "pdf_exceeds_size_bound"


def test_too_many_pages_rejected() -> None:
    pages = [[(40.0, 800.0, "page")] for _ in range(MAX_PDF_PAGES + 1)]
    preview = _preview(build_text_pdf(pages))
    assert preview.status is ReportStatus.MALFORMED
    assert preview.reason == "pdf_exceeds_page_bound"


def test_exact_dividend_mapping() -> None:
    row = _preview(build_income_report_pdf()).rows[0]
    assert row.event_kind == "dividend"
    assert row.event_date.isoformat() == "2026-01-20"
    assert row.record_date.isoformat() == "2026-01-15"
    assert row.gross_amount == Decimal("11.50")
    assert row.tax_amount == Decimal("1.50")
    assert row.tax_available is True
    assert row.net_amount == Decimal("10.00")


def test_exact_coupon_mapping() -> None:
    pdf = build_income_report_pdf(
        [
            _row(
                payment_kind="погашение купона",
                isin="RU000SYN00002",
                quantity="10",
                per_unit="2,00",
                gross="20,00",
                tax="—",
                tax_rate="—",
                d1="—",
                d2="—",
                net="20,00",
            )
        ]
    )
    instruments = (
        HermesInstrumentView(instrument_id=21, isin="RU000SYN00002"),
        *_instruments(),
    )
    row = _preview(pdf, hermes_instruments=instruments).rows[0]
    assert row.event_kind == "coupon"
    assert row.status is RowStatus.MATCHED
    assert row.tax_available is False
    assert row.tax_amount is None
    assert row.net_amount == Decimal("20.00")


def test_exact_full_redemption_mapping() -> None:
    pdf = build_income_report_pdf(
        [
            _row(
                payment_kind="полное погашение номинала",
                isin="RU000SYN00003",
                quantity="5",
                per_unit="1000,00",
                gross="5000,00",
                tax="—",
                net="5000,00",
            )
        ]
    )
    instruments = (HermesInstrumentView(instrument_id=22, isin="RU000SYN00003"),)
    row = _preview(pdf, hermes_instruments=instruments).rows[0]
    assert row.event_kind == "redemption"
    assert row.status is RowStatus.MATCHED
    assert row.gross_amount == Decimal("5000.00")


def test_unknown_payment_type_unsupported() -> None:
    pdf = build_income_report_pdf([_row(payment_kind="комиссия депозитария")])
    row = _preview(pdf).rows[0]
    assert row.status is RowStatus.UNSUPPORTED
    assert row.event_kind is None
    assert row.reason == "unknown_payment_kind"


def test_partial_amortization_unsupported() -> None:
    pdf = build_income_report_pdf([_row(payment_kind="частичное погашение номинала")])
    row = _preview(pdf).rows[0]
    assert row.status is RowStatus.UNSUPPORTED
    assert row.reason == "unsupported_partial_amortization"


def test_foreign_non_rub_unsupported_without_fx() -> None:
    pdf = build_income_report_pdf(
        [
            _row(
                gross_currency="USD",
                net_currency="USD",
                quantity="10",
                per_unit="1,15",
                gross="11,50",
                tax="1,50",
                net="10,00",
            )
        ]
    )
    row = _preview(pdf).rows[0]
    assert row.status is RowStatus.UNSUPPORTED
    assert row.reason == "unsupported_non_rub_currency"


def test_foreign_section_unsupported() -> None:
    pdf = build_income_report_pdf(
        extra_lines=("Иностранные ценные бумаги",),
    )
    row = _preview(pdf).rows[0]
    assert row.status is RowStatus.UNSUPPORTED
    assert row.reason == "unsupported_foreign"


def test_decree_665_unsupported() -> None:
    pdf = build_income_report_pdf(extra_lines=("Выплаты по Указу № 665",))
    row = _preview(pdf).rows[0]
    assert row.status is RowStatus.UNSUPPORTED
    assert row.reason == "unsupported_decree_665"


def test_normalized_isin_strip_upper() -> None:
    pdf = build_income_report_pdf([_row(isin=" ru000syn00001 ")])
    row = _preview(pdf).rows[0]
    assert row.isin == SYN_ISIN
    assert row.hermes_instrument_id == 20
    assert row.status is RowStatus.MATCHED


def test_explicit_account_mapping_only() -> None:
    pdf = build_income_report_pdf()
    unmatched = _preview(pdf, account_mappings=()).rows[0]
    assert unmatched.status is RowStatus.UNMATCHED
    assert unmatched.reason == "account_unmapped"
    assert unmatched.hermes_account_id is None
    mapped = _preview(pdf).rows[0]
    assert mapped.hermes_account_id == 10
    assert mapped.status is RowStatus.MATCHED


def test_iis_text_is_not_account_inference() -> None:
    pdf = build_income_report_pdf(extra_lines=("Счет ИИС",))
    row = _preview(pdf, account_mappings=()).rows[0]
    assert row.status is RowStatus.UNMATCHED
    assert row.hermes_account_id is None


def test_unique_isin_instrument_match() -> None:
    row = _preview(build_income_report_pdf(), instrument_mappings=()).rows[0]
    assert row.hermes_instrument_id == 20
    assert row.status is RowStatus.MATCHED


def test_duplicate_hermes_isin_ambiguous() -> None:
    instruments = (
        HermesInstrumentView(instrument_id=20, isin=SYN_ISIN),
        HermesInstrumentView(instrument_id=21, isin=SYN_ISIN),
    )
    row = _preview(build_income_report_pdf(), hermes_instruments=instruments).rows[0]
    assert row.status is RowStatus.AMBIGUOUS
    assert row.reason == "instrument_ambiguous"
    assert row.hermes_instrument_id is None


def test_explicit_instrument_mapping_resolves_duplicate_isin() -> None:
    instruments = (
        HermesInstrumentView(instrument_id=20, isin=SYN_ISIN),
        HermesInstrumentView(instrument_id=21, isin=SYN_ISIN),
    )
    mapping = (InstrumentMappingInput(hermes_instrument_id=21, isin=SYN_ISIN),)
    row = _preview(
        build_income_report_pdf(),
        hermes_instruments=instruments,
        instrument_mappings=mapping,
    ).rows[0]
    assert row.status is RowStatus.MATCHED
    assert row.hermes_instrument_id == 21


def test_missing_isin_unmatched() -> None:
    pdf = build_income_report_pdf([_row(isin="")])
    row = _preview(pdf).rows[0]
    assert row.status is RowStatus.UNMATCHED
    assert row.reason == "missing_isin"
    assert row.hermes_instrument_id is None


def test_ticker_name_do_not_auto_match() -> None:
    instruments = (
        HermesInstrumentView(
            instrument_id=99,
            isin="RU000OTHER001",
            name="Synthetic Equity One",
            ticker="SYN",
        ),
    )
    row = _preview(build_income_report_pdf(), hermes_instruments=instruments).rows[0]
    assert row.status is RowStatus.UNMATCHED
    assert row.hermes_instrument_id is None


def test_exact_decimal_float_hostile_values() -> None:
    pdf = build_income_report_pdf(
        [
            _row(
                quantity="3",
                per_unit="0,10",
                gross="0,30",
                tax="—",
                net="0,30",
            )
        ]
    )
    row = _preview(pdf).rows[0]
    assert row.quantity == Decimal("3")
    assert row.per_unit == Decimal("0.10")
    assert row.gross_amount == Decimal("0.30")
    assert row.net_amount == Decimal("0.30")
    assert row.gross_amount == row.per_unit * row.quantity


def test_parse_decimal_rejects_binary_float() -> None:
    with pytest.raises(TypeError, match="float"):
        parse_decimal(1.15)  # type: ignore[arg-type]


def test_explicit_gross_tax_net_arithmetic_valid() -> None:
    row = _preview(build_income_report_pdf()).rows[0]
    assert row.status is RowStatus.MATCHED
    assert row.gross_amount - row.tax_amount == row.net_amount


def test_arithmetic_contradiction_malformed() -> None:
    pdf = build_income_report_pdf([_row(net="9,00")])
    row = _preview(pdf).rows[0]
    assert row.status is RowStatus.MALFORMED
    assert row.reason == "arithmetic_contradiction"


def test_dash_tax_distinct_from_explicit_zero() -> None:
    dash_pdf = build_income_report_pdf(
        [
            _row(
                quantity="10",
                per_unit="1,15",
                gross="11,50",
                tax="—",
                net="11,50",
            )
        ]
    )
    zero_pdf = build_income_report_pdf(
        [
            _row(
                quantity="10",
                per_unit="1,15",
                gross="11,50",
                tax="0,00",
                net="11,50",
            )
        ]
    )
    dash = _preview(dash_pdf).rows[0]
    zero = _preview(zero_pdf).rows[0]
    assert dash.tax_available is False
    assert dash.tax_amount is None
    assert zero.tax_available is True
    assert zero.tax_amount == Decimal("0.00")
    assert dash.material_fingerprint != zero.material_fingerprint


def test_missing_payment_date_is_malformed() -> None:
    pdf = build_income_report_pdf([_row(payment_date="—")])
    row = _preview(pdf).rows[0]
    assert row.status is RowStatus.MALFORMED
    assert row.reason == "missing_payment_date"


def test_client_payment_date_is_realized_event_date() -> None:
    row = _preview(build_income_report_pdf()).rows[0]
    assert row.event_date.isoformat() == "2026-01-20"
    assert row.record_date.isoformat() == "2026-01-15"
    assert row.event_date != row.record_date


def test_natural_identity_stable_when_material_changes() -> None:
    first = _preview(build_income_report_pdf()).rows[0]
    second_pdf = build_income_report_pdf(
        [
            _row(
                payment_date="25.01.2026",
                quantity="20",
                per_unit="1,15",
                gross="23,00",
                tax="3,00",
                net="20,00",
            )
        ]
    )
    second = _preview(second_pdf).rows[0]
    assert first.natural_identity == second.natural_identity
    assert first.natural_identity == f"10|dividend|{SYN_ISIN}|2026-01-15"
    assert first.material_fingerprint != second.material_fingerprint


def test_material_fingerprint_changes_on_tax_and_net() -> None:
    base = _preview(build_income_report_pdf()).rows[0]
    changed = _preview(build_income_report_pdf([_row(tax="2,00", net="9,50")])).rows[0]
    assert base.natural_identity == changed.natural_identity
    assert base.material_fingerprint != changed.material_fingerprint


def test_colliding_source_rows_fail_closed() -> None:
    pdf = build_income_report_pdf(
        [
            _row(
                quantity="10",
                per_unit="1,15",
                gross="11,50",
                tax="1,50",
                net="10,00",
            ),
            _row(
                quantity="20",
                per_unit="1,15",
                gross="23,00",
                tax="3,00",
                net="20,00",
            ),
        ]
    )
    rows = _preview(pdf).rows
    assert len(rows) == 2
    assert {row.status for row in rows} == {RowStatus.AMBIGUOUS}
    assert {row.reason for row in rows} == {"natural_identity_collision"}


def test_mapped_natural_identity_collision_across_provider_refs() -> None:
    pdf = build_income_report_pdf(
        [
            _row(
                depo_account="SYN-DEPO-001",
                quantity="10",
                per_unit="1,15",
                gross="11,50",
                tax="1,50",
                net="10,00",
            ),
            _row(
                depo_account="SYN-DEPO-002",
                quantity="20",
                per_unit="1,15",
                gross="23,00",
                tax="3,00",
                net="20,00",
            ),
        ]
    )
    mappings = (
        AccountMappingInput(hermes_account_id=10, provider_account_ref="SYN-DEPO-001"),
        AccountMappingInput(hermes_account_id=10, provider_account_ref="SYN-DEPO-002"),
    )
    identity = f"10|dividend|{SYN_ISIN}|2026-01-15"
    prior = (
        PriorEventView(
            natural_identity=identity,
            material_fingerprint="synthetic-prior-fingerprint",
        ),
    )
    rows = _preview(pdf, account_mappings=mappings, prior_events=prior).rows
    assert len(rows) == 2
    assert {row.provider_account_ref for row in rows} == {"SYN-DEPO-001", "SYN-DEPO-002"}
    assert {row.hermes_account_id for row in rows} == {10}
    assert {row.natural_identity for row in rows} == {identity}
    assert {row.status for row in rows} == {RowStatus.AMBIGUOUS}
    assert {row.reason for row in rows} == {"natural_identity_collision"}
    assert all(row.duplicate_class is None for row in rows)


def test_document_fingerprint_deterministic() -> None:
    pdf = build_income_report_pdf()
    first = _preview(pdf)
    second = _preview(pdf)
    assert first.document_sha256 == hashlib.sha256(pdf).hexdigest()
    assert first.document_sha256 == second.document_sha256
    assert first.document_sha256 == document_sha256(pdf)
    other = _preview(build_income_report_pdf([_row(payment_date="21.01.2026")]))
    assert other.document_sha256 != first.document_sha256


def test_no_private_fields_in_normalized_output() -> None:
    preview = _preview(build_income_report_pdf())
    dumped = repr(preview)
    for marker in PRIVATE_MARKERS:
        assert marker not in dumped
    row = preview.rows[0]
    assert not hasattr(row, "d1")
    assert not hasattr(row, "d2")
    assert not hasattr(row, "beneficiary_account")
    assert not hasattr(row, "beneficiary_bank")
    assert not hasattr(row, "security_name")
    assert not hasattr(row, "raw_text")
    assert "Отчет о произведенных" not in dumped


def test_repeated_preview_is_pure_and_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _blocked(*_args: object, **_kwargs: object) -> None:
        calls.append("write")
        raise AssertionError("persistent write")

    monkeypatch.setattr(
        "hermes_finance.services.investment_cash_flows.create_investment_cash_flow",
        _blocked,
        raising=False,
    )
    pdf = build_income_report_pdf()
    first = _preview(pdf)
    second = _preview(pdf)
    assert first == second
    assert calls == []
    assert first.rows[0].status is RowStatus.MATCHED


def test_package_has_no_persistence_ocr_or_network_imports() -> None:
    root = Path(inspect.getfile(preview_income_report)).resolve().parent
    forbidden_modules = {
        "hermes_finance.persistence",
        "hermes_finance.services.investment_cash_flows",
        "hermes_finance.broker_data.alfa_pro.adapter",
        "httpx",
        "httpx2",
        "requests",
        "pytesseract",
        "easyocr",
        "pdf2image",
        "ocrmypdf",
    }
    forbidden_tokens = (
        "pytesseract",
        "easyocr",
        "pdf2image",
        "ocrmypdf",
        "ClientOperationEntity",
    )
    for path in sorted(root.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_modules
                    assert alias.name not in forbidden_modules
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden_modules
                assert not any(
                    node.module == name or node.module.startswith(f"{name}.")
                    for name in forbidden_modules
                )


def test_missing_schema_is_malformed() -> None:
    pdf = build_income_report_pdf(include_header=False)
    preview = _preview(pdf)
    assert preview.status is ReportStatus.MALFORMED
    assert preview.reason == "missing_required_schema"


def test_duplicate_and_correction_against_prior_view() -> None:
    first = _preview(build_income_report_pdf()).rows[0]
    prior = (
        PriorEventView(
            natural_identity=first.natural_identity or "",
            material_fingerprint=first.material_fingerprint or "",
        ),
    )
    duplicate = _preview(build_income_report_pdf(), prior_events=prior).rows[0]
    assert duplicate.duplicate_class is DuplicateClass.DUPLICATE
    changed = _preview(
        build_income_report_pdf([_row(payment_date="25.01.2026")]),
        prior_events=prior,
    ).rows[0]
    assert changed.natural_identity == first.natural_identity
    assert changed.duplicate_class is DuplicateClass.CORRECTION


def test_extract_then_parse_split_boundary() -> None:
    pdf = build_income_report_pdf()
    extracted = extract_pdf_text_layer(pdf)
    parsed = parse_income_report(extracted)
    assert parsed.status is ReportStatus.APPLICABLE
    assert parsed.rows[0].event_kind == "dividend"
    assert REPORT_TITLE.split()[0] not in (parsed.reason or "")
