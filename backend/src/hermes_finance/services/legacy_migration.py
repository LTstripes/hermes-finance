"""Transactional one-shot migration from the known private legacy workbook (F10)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from hermes_finance.database import Database
from hermes_finance.domain import FINANCIAL_ROUNDING
from hermes_finance.persistence import (
    Account,
    CashBalance,
    Debt,
    DepositSnapshot,
    ExpectedCashFlow,
    ExpenseEntry,
    IncomeEntry,
    Instrument,
    InvestmentCashFlow,
    LegacyMigrationRun,
    MonthlyComment,
    PositionSnapshot,
    PropertySnapshot,
    ReportingMonth,
    SavingAllocation,
)
from hermes_finance.services.backups import create_backup
from hermes_finance.services.legacy_excel import LegacyMonthExtraction, LegacyWorkbookExtraction

POLICY_CREATE_WITHOUT_ISIN = "create_without_isin"


class LegacyMigrationAlreadyAppliedError(ValueError):
    """The exact source workbook was already committed."""


class LegacyMigrationConflictError(ValueError):
    """The destination contains a reporting period from the source workbook."""


@dataclass(frozen=True, slots=True)
class LegacyMigrationReport:
    source_sha256: str
    backup_id: str
    months_imported: int
    periods: tuple[str, ...]
    replaced_periods: tuple[str, ...]
    counts: dict[str, int]
    not_imported: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source_sha256": self.source_sha256,
            "policy": POLICY_CREATE_WITHOUT_ISIN,
            "backup_id": self.backup_id,
            "months_imported": self.months_imported,
            "periods": list(self.periods),
            "replaced_periods": list(self.replaced_periods),
            "counts": self.counts,
            "not_imported": self.not_imported,
        }


@dataclass(slots=True)
class _ImportState:
    accounts: dict[tuple[str, str], Account] = field(default_factory=dict)
    instruments: dict[tuple[str, str, str | None], Instrument] = field(default_factory=dict)


def legacy_review_id(year: int, month: int, section: str, source_row: int) -> str:
    return f"{year:04d}-{month:02d}:{section}:{source_row}"


def load_legacy_decisions(path: Path) -> dict[str, str]:
    """Load the ignored manual-review manifest without returning private row data."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("legacy review manifest could not be read") from error
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("legacy review manifest rows must be a list")
    decisions: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("legacy review manifest row must be an object")
        review_id = row.get("review_id")
        decision = row.get("decision")
        if not isinstance(review_id, str) or not review_id:
            raise ValueError("legacy review_id must be a non-empty string")
        if review_id in decisions:
            raise ValueError("legacy review_id must be unique")
        if decision != POLICY_CREATE_WITHOUT_ISIN:
            raise ValueError("every unresolved instrument must use create_without_isin")
        if row.get("target_isin") not in (None, ""):
            raise ValueError("create_without_isin rows must not define target_isin")
        decisions[review_id] = decision
    return decisions


def _required_decisions(extraction: LegacyWorkbookExtraction) -> set[str]:
    required: set[str] = set()
    for month in extraction.months:
        year = month.reporting_month["year"]
        number = month.reporting_month["month"]
        for section in ("stocks", "bonds"):
            for row in getattr(month, section):
                if not row.get("isin"):
                    required.add(legacy_review_id(year, number, section, int(row["source_row"])))
    return required


def _validate_inputs(
    extraction: LegacyWorkbookExtraction, source_sha256: str, decisions: dict[str, str]
) -> tuple[tuple[int, int], ...]:
    if len(source_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in source_sha256
    ):
        raise ValueError("source_sha256 must be a lowercase SHA-256 hex digest")
    if not extraction.months:
        raise ValueError("legacy extraction must contain at least one month")
    periods = tuple(
        (month.reporting_month["year"], month.reporting_month["month"])
        for month in extraction.months
    )
    if len(set(periods)) != len(periods):
        raise ValueError("legacy extraction reporting periods must be unique")
    required = _required_decisions(extraction)
    if set(decisions) != required:
        raise ValueError("legacy review decisions do not match unresolved instrument rows")
    if any(value != POLICY_CREATE_WITHOUT_ISIN for value in decisions.values()):
        raise ValueError("unsupported legacy instrument decision")
    return periods


def _preflight(
    database: Database,
    extraction: LegacyWorkbookExtraction,
    source_sha256: str,
    decisions: dict[str, str],
    replace_periods: set[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    periods = _validate_inputs(extraction, source_sha256, decisions)
    if not replace_periods.issubset(set(periods)):
        raise ValueError("replacement periods must exist in the legacy extraction")
    with database.session_factory() as session:
        if (
            session.scalar(
                select(LegacyMigrationRun.id).where(
                    LegacyMigrationRun.source_sha256 == source_sha256
                )
            )
            is not None
        ):
            raise LegacyMigrationAlreadyAppliedError("source workbook was already migrated")
        conflicts: dict[tuple[int, int], ReportingMonth] = {}
        for year, month in periods:
            existing = session.scalar(
                select(ReportingMonth).where(
                    ReportingMonth.year == year,
                    ReportingMonth.month == month,
                )
            )
            if existing is not None:
                conflicts[(year, month)] = existing
    unapproved = set(conflicts) - replace_periods
    if unapproved:
        raise LegacyMigrationConflictError(
            "reporting periods already exist: "
            + ", ".join(f"{year:04d}-{month:02d}" for year, month in sorted(unapproved))
        )
    missing = replace_periods - set(conflicts)
    if missing:
        raise ValueError("replacement period does not currently exist")
    unsafe = [
        period
        for period, existing in conflicts.items()
        if period in replace_periods and (existing.status != "draft" or existing.source != "manual")
    ]
    if unsafe:
        raise LegacyMigrationConflictError(
            "only draft/manual periods may be replaced: "
            + ", ".join(f"{year:04d}-{month:02d}" for year, month in sorted(unsafe))
        )
    return periods


_MONTH_CHILD_MODELS = (
    PositionSnapshot,
    DepositSnapshot,
    CashBalance,
    IncomeEntry,
    InvestmentCashFlow,
    ExpectedCashFlow,
    ExpenseEntry,
    SavingAllocation,
    Debt,
    PropertySnapshot,
    MonthlyComment,
)


def _delete_reporting_period(session: Session, year: int, month: int) -> None:
    existing_id = session.scalar(
        select(ReportingMonth.id).where(
            ReportingMonth.year == year,
            ReportingMonth.month == month,
            ReportingMonth.status == "draft",
            ReportingMonth.source == "manual",
        )
    )
    if existing_id is None:
        raise LegacyMigrationConflictError(
            f"replacement period {year:04d}-{month:02d} changed after preflight"
        )
    for model in _MONTH_CHILD_MODELS:
        session.execute(delete(model).where(model.reporting_month_id == existing_id))
    session.execute(delete(ReportingMonth).where(ReportingMonth.id == existing_id))
    session.flush()


def _identity(value: str) -> str:
    return value.strip().casefold()


def _external_code(category: str, name: str) -> str:
    digest = hashlib.sha256(f"{category}\0{_identity(name)}".encode()).hexdigest()[:24]
    return f"legacy:{category}:{digest}"


def _account(
    session: Session,
    state: _ImportState,
    counts: dict[str, int],
    *,
    category: str,
    name: str,
    account_type: str,
) -> Account:
    key = (category, _identity(name))
    cached = state.accounts.get(key)
    if cached is not None:
        return cached
    external_code = _external_code(category, name)
    account = session.scalar(select(Account).where(Account.external_code == external_code))
    if account is None:
        account = Account(
            name=name.strip(),
            account_type=account_type,
            external_code=external_code,
            status="active",
            include_in_capital=True,
            include_in_returns=True,
            notes="Imported from legacy Excel; verify account classification.",
        )
        session.add(account)
        session.flush()
        counts["accounts_created"] += 1
    state.accounts[key] = account
    return account


def _instrument(
    session: Session,
    state: _ImportState,
    counts: dict[str, int],
    *,
    name: str,
    instrument_type: str,
    isin: str | None,
) -> Instrument:
    normalized_isin = isin.strip().upper() if isin else None
    key = (instrument_type, _identity(name), normalized_isin)
    cached = state.instruments.get(key)
    if cached is not None:
        return cached
    instrument = None
    if normalized_isin is not None:
        instrument = session.scalar(select(Instrument).where(Instrument.isin == normalized_isin))
        if instrument is not None and instrument.instrument_type != instrument_type:
            raise ValueError("existing ISIN has a conflicting instrument type")
    if instrument is None:
        instrument = Instrument(
            name=name.strip(),
            instrument_type=instrument_type,
            isin=normalized_isin,
            currency="RUB",
            is_active=True,
            manual_price_allowed=True,
            notes=(
                "Imported from legacy Excel; ISIN requires manual resolution."
                if normalized_isin is None
                else "Imported from legacy Excel."
            ),
        )
        session.add(instrument)
        session.flush()
        counts["instruments_created"] += 1
    state.instruments[key] = instrument
    return instrument


def _per_unit(total_kopecks: int, quantity: Decimal) -> int:
    if quantity <= 0:
        raise ValueError("legacy position quantity must be positive")
    return int((Decimal(total_kopecks) / quantity).to_integral_value(rounding=FINANCIAL_ROUNDING))


def _add_security_position(
    session: Session,
    state: _ImportState,
    counts: dict[str, int],
    month_id: int,
    snapshot_date: date,
    row: dict[str, Any],
    instrument_type: str,
) -> None:
    account_name = str(row.get("account") or "").strip()
    if not account_name:
        raise ValueError("legacy security account must not be empty")
    account = _account(
        session,
        state,
        counts,
        category="investment",
        name=account_name,
        account_type="brokerage",
    )
    instrument = _instrument(
        session,
        state,
        counts,
        name=str(row["name"]),
        instrument_type=instrument_type,
        isin=row.get("isin"),
    )
    quantity = Decimal(str(row["quantity"]))
    market_value = int(row["market_value_kopecks"])
    market_price = _per_unit(market_value, quantity)
    average_cost = (
        int(row["cost_kopecks"])
        if instrument_type == "stock" and row.get("cost_kopecks") is not None
        else market_price
    )
    cost_basis = int(
        (quantity * Decimal(average_cost)).to_integral_value(rounding=FINANCIAL_ROUNDING)
    )
    session.add(
        PositionSnapshot(
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=quantity,
            average_cost_per_unit_kopecks=average_cost,
            market_price_per_unit_kopecks=market_price,
            accrued_interest_kopecks=None,
            market_value_kopecks=market_value,
            cost_basis_kopecks=cost_basis,
            unrealized_result_kopecks=market_value - cost_basis,
            price_date=snapshot_date,
            price_source="manual",
            manual_adjustment=True,
            notes="Imported from legacy Excel; verify price and cost basis.",
        )
    )
    counts["position_snapshots"] += 1


def _add_gold_position(
    session: Session,
    state: _ImportState,
    counts: dict[str, int],
    month_id: int,
    snapshot_date: date,
    row: dict[str, Any],
) -> None:
    account = _account(
        session,
        state,
        counts,
        category="gold",
        name="Физическое золото",
        account_type="other",
    )
    instrument = _instrument(
        session,
        state,
        counts,
        name=str(row["name"]),
        instrument_type="gold",
        isin=None,
    )
    quantity = Decimal(str(row["grams"]))
    average_cost = int(row["purchase_price_per_gram_kopecks"])
    market_price = int(row["price_per_gram_kopecks"])
    market_value = int(row["current_value_kopecks"])
    cost_basis = int(
        (quantity * Decimal(average_cost)).to_integral_value(rounding=FINANCIAL_ROUNDING)
    )
    session.add(
        PositionSnapshot(
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=quantity,
            average_cost_per_unit_kopecks=average_cost,
            market_price_per_unit_kopecks=market_price,
            accrued_interest_kopecks=None,
            market_value_kopecks=market_value,
            cost_basis_kopecks=cost_basis,
            unrealized_result_kopecks=market_value - cost_basis,
            price_date=snapshot_date,
            price_source="manual",
            manual_adjustment=True,
            notes="Imported physical gold snapshot from legacy Excel.",
        )
    )
    counts["position_snapshots"] += 1


def _import_month(
    session: Session,
    month: LegacyMonthExtraction,
    state: _ImportState,
    counts: dict[str, int],
) -> None:
    year = int(month.reporting_month["year"])
    number = int(month.reporting_month["month"])
    period_start = date(year, number, 1)
    period_end = date(year, number, monthrange(year, number)[1])
    snapshot_date = date.fromisoformat(month.snapshot_date)
    reporting_month = ReportingMonth(
        year=year,
        month=number,
        period_start=period_start,
        period_end=period_end,
        snapshot_date=snapshot_date,
        status="draft",
        source="excel_migration",
    )
    session.add(reporting_month)
    session.flush()
    counts["reporting_months"] += 1

    for row in month.deposits:
        name = str(row["name"])
        account = _account(
            session,
            state,
            counts,
            category="deposit",
            name=name,
            account_type="deposit",
        )
        session.add(
            DepositSnapshot(
                reporting_month_id=reporting_month.id,
                account_id=account.id,
                name=name.strip(),
                deposit_type="deposit",
                balance_kopecks=int(row["balance_kopecks"]),
                annual_rate_basis_points=int(row["annual_rate_basis_points"]),
                expected_monthly_interest_kopecks=int(row["expected_monthly_interest_kopecks"]),
                actual_interest_received_kopecks=0,
                notes="Imported from legacy Excel.",
            )
        )
        counts["deposit_snapshots"] += 1

    for row in month.stocks:
        _add_security_position(
            session, state, counts, reporting_month.id, snapshot_date, row, "stock"
        )
    for row in month.bonds:
        _add_security_position(
            session, state, counts, reporting_month.id, snapshot_date, row, "bond"
        )
    for row in month.gold:
        _add_gold_position(session, state, counts, reporting_month.id, snapshot_date, row)

    if month.salary is not None:
        amount = int(month.salary["amount_kopecks"])
        session.add(
            IncomeEntry(
                reporting_month_id=reporting_month.id,
                income_type="salary",
                name=str(month.salary["name"]),
                gross_amount_kopecks=amount,
                tax_amount_kopecks=0,
                net_amount_kopecks=amount,
                received_at=snapshot_date,
                is_recurring=True,
                include_in_cash_flow=True,
                include_in_passive_income=False,
                notes="Imported net-only legacy salary; gross/tax require review.",
            )
        )
        counts["income_entries"] += 1
    for row in month.cashback:
        amount = int(row["amount_kopecks"])
        session.add(
            IncomeEntry(
                reporting_month_id=reporting_month.id,
                income_type="cashback",
                name=str(row["name"]),
                gross_amount_kopecks=amount,
                tax_amount_kopecks=0,
                net_amount_kopecks=amount,
                received_at=snapshot_date,
                is_recurring=False,
                include_in_cash_flow=True,
                include_in_passive_income=False,
                notes=row.get("notes"),
            )
        )
        counts["income_entries"] += 1
    for row in month.mandatory_expenses:
        session.add(
            ExpenseEntry(
                reporting_month_id=reporting_month.id,
                category=str(row["name"]),
                amount_kopecks=int(row["amount_kopecks"]),
                expense_type="mandatory",
                is_recurring=True,
                notes=row.get("notes"),
            )
        )
        counts["expense_entries"] += 1
    for row in month.saving_allocations:
        session.add(
            SavingAllocation(
                reporting_month_id=reporting_month.id,
                destination=str(row["name"]),
                amount_kopecks=int(row["amount_kopecks"]),
                notes=row.get("notes"),
            )
        )
        counts["saving_allocations"] += 1
    for row in month.debts_payable:
        session.add(
            Debt(
                reporting_month_id=reporting_month.id,
                debt_type="other",
                name=str(row["name"]),
                current_balance_kopecks=int(row["amount_kopecks"]),
                include_in_liquid_capital=True,
                notes=row.get("notes"),
            )
        )
        counts["debts"] += 1
    for position, row in enumerate(month.comments, start=1):
        session.add(
            MonthlyComment(
                reporting_month_id=reporting_month.id,
                position=position,
                text=str(row["text"]).strip(),
            )
        )
        counts["monthly_comments"] += 1


def _initial_counts() -> dict[str, int]:
    return {
        "accounts_created": 0,
        "instruments_created": 0,
        "reporting_months": 0,
        "position_snapshots": 0,
        "deposit_snapshots": 0,
        "income_entries": 0,
        "expense_entries": 0,
        "saving_allocations": 0,
        "debts": 0,
        "monthly_comments": 0,
    }


def _write_report(path: Path, report: LegacyMigrationReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def apply_legacy_migration(
    database: Database,
    extraction: LegacyWorkbookExtraction,
    *,
    source_sha256: str,
    decisions: dict[str, str],
    report_path: Path,
    replace_periods: set[tuple[int, int]] | None = None,
) -> LegacyMigrationReport:
    """Back up and import the extraction exactly once in one DB transaction."""
    replacements = set(replace_periods or ())
    periods = _preflight(database, extraction, source_sha256, decisions, replacements)
    backup = create_backup(database)
    counts = _initial_counts()
    not_imported = {
        "debts_receivable": sum(len(month.debts_receivable) for month in extraction.months),
        "dividends": sum(len(month.dividends) for month in extraction.months),
        "goals": sum(len(month.goals) for month in extraction.months),
    }
    report = LegacyMigrationReport(
        source_sha256=source_sha256,
        backup_id=backup.id,
        months_imported=len(extraction.months),
        periods=tuple(f"{year:04d}-{month:02d}" for year, month in periods),
        replaced_periods=tuple(f"{year:04d}-{month:02d}" for year, month in sorted(replacements)),
        counts=counts,
        not_imported=not_imported,
    )
    state = _ImportState()
    with database.session_factory() as session:
        try:
            for year, month in sorted(replacements):
                _delete_reporting_period(session, year, month)
            for month in extraction.months:
                _import_month(session, month, state, counts)
            session.add(
                LegacyMigrationRun(
                    source_sha256=source_sha256,
                    source_file=extraction.source_file,
                    policy=POLICY_CREATE_WITHOUT_ISIN,
                    backup_id=backup.id,
                    month_count=len(extraction.months),
                    summary_json=json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True),
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
    _write_report(report_path, report)
    return report
