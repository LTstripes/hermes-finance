import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from hermes_finance.database import create_database
from hermes_finance.persistence import (
    Account,
    Base,
    IncomeEntry,
    Instrument,
    LegacyMigrationRun,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.legacy_excel import (
    LegacyExtractionWarning,
    LegacyMonthExtraction,
    LegacyWorkbookExtraction,
)
from hermes_finance.services.legacy_migration import (
    LegacyMigrationAlreadyAppliedError,
    LegacyMigrationConflictError,
    apply_legacy_migration,
    legacy_review_id,
    load_legacy_decisions,
)


def _extraction() -> LegacyWorkbookExtraction:
    month = LegacyMonthExtraction(
        sheet_name="Январь_2026",
        reporting_month={"year": 2026, "month": 1},
        snapshot_date="2026-01-31",
        salary={"name": "salary", "amount_kopecks": 100_000},
        deposits=(
            {
                "name": "Synthetic deposit",
                "balance_kopecks": 500_000,
                "annual_rate_basis_points": 1_200,
                "expected_monthly_interest_kopecks": 5_000,
            },
        ),
        stocks=(
            {
                "source_row": 61,
                "name": "Synthetic stock",
                "isin": None,
                "account": "Synthetic brokerage",
                "quantity": "2",
                "cost_kopecks": 10_000,
                "market_value_kopecks": 30_000,
            },
        ),
        bonds=(
            {
                "source_row": 46,
                "name": "Synthetic bond",
                "isin": "RU000SYNTH01",
                "account": "Synthetic IIS",
                "quantity": "3",
                "market_value_kopecks": 60_000,
                "monthly_coupon_kopecks": 1_000,
            },
        ),
        gold=(
            {
                "name": "Synthetic gold",
                "grams": "1.5",
                "price_per_gram_kopecks": 20_000,
                "current_value_kopecks": 30_000,
                "purchase_price_per_gram_kopecks": 18_000,
                "pnl_kopecks": 3_000,
            },
        ),
        mandatory_expenses=({"name": "Synthetic expense", "amount_kopecks": 40_000},),
        saving_allocations=({"name": "Synthetic saving", "amount_kopecks": 20_000},),
        cashback=({"name": "Synthetic cashback", "amount_kopecks": 2_000},),
        debts_receivable=(),
        debts_payable=({"name": "Synthetic debt", "amount_kopecks": 7_000},),
        goals=({"name": "Synthetic legacy goal", "amount_kopecks": 90_000},),
        dividends=({"period": "Synthetic average", "monthly_kopecks": 500},),
        comments=({"position": None, "text": "Synthetic comment"},),
        control_totals=(),
    )
    return LegacyWorkbookExtraction(
        source_file="synthetic.xlsx",
        months=(month,),
        warnings=(
            LegacyExtractionWarning(
                code="empty_isin",
                sheet_name=month.sheet_name,
                row=61,
                message="instrument row has no ISIN",
            ),
        ),
    )


def _decisions() -> dict[str, str]:
    return {legacy_review_id(2026, 1, "stocks", 61): "create_without_isin"}


def _database(tmp_path: Path):
    database = create_database(tmp_path / "finance.db")
    Base.metadata.create_all(database.engine)
    return database


def test_applies_legacy_migration_with_backup_and_nullable_isin(tmp_path: Path) -> None:
    database = _database(tmp_path)

    report = apply_legacy_migration(
        database,
        _extraction(),
        source_sha256="a" * 64,
        decisions=_decisions(),
        report_path=tmp_path / "migration-report.json",
    )

    assert report.months_imported == 1
    assert report.counts == {
        "accounts_created": 4,
        "instruments_created": 3,
        "reporting_months": 1,
        "position_snapshots": 3,
        "deposit_snapshots": 1,
        "income_entries": 2,
        "expense_entries": 1,
        "saving_allocations": 1,
        "debts": 1,
        "monthly_comments": 1,
    }
    assert report.not_imported == {"debts_receivable": 0, "dividends": 1, "goals": 1}
    assert report.backup_id
    assert (tmp_path / "backups" / f"{report.backup_id}.sqlite3").is_file()
    assert (tmp_path / "migration-report.json").is_file()

    with database.session_factory() as session:
        nullable = session.scalar(select(Instrument).where(Instrument.isin.is_(None)))
        assert nullable is not None
        assert nullable.name == "Synthetic stock"
        brokerage = session.scalar(select(Account).where(Account.name == "Synthetic brokerage"))
        assert brokerage is not None
        assert (
            session.scalar(
                select(func.count(PositionSnapshot.id)).where(
                    PositionSnapshot.account_id == brokerage.id,
                    PositionSnapshot.instrument_id == nullable.id,
                )
            )
            == 1
        )
        assert session.scalar(select(func.count(LegacyMigrationRun.id))) == 1

    database.engine.dispose()


def test_rejects_same_workbook_hash_without_second_backup(tmp_path: Path) -> None:
    database = _database(tmp_path)
    apply_legacy_migration(
        database,
        _extraction(),
        source_sha256="b" * 64,
        decisions=_decisions(),
        report_path=tmp_path / "first.json",
    )
    backup_count = len(list((tmp_path / "backups").glob("*.sqlite3")))

    with pytest.raises(LegacyMigrationAlreadyAppliedError):
        apply_legacy_migration(
            database,
            _extraction(),
            source_sha256="b" * 64,
            decisions=_decisions(),
            report_path=tmp_path / "second.json",
        )

    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == backup_count
    database.engine.dispose()


def test_rejects_conflicting_period_before_backup(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.session_factory() as session:
        session.add(
            ReportingMonth(
                year=2026,
                month=1,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                snapshot_date=date(2026, 1, 31),
                status="draft",
                source="manual",
            )
        )
        session.commit()

    with pytest.raises(LegacyMigrationConflictError, match="2026-01"):
        apply_legacy_migration(
            database,
            _extraction(),
            source_sha256="c" * 64,
            decisions=_decisions(),
            report_path=tmp_path / "report.json",
        )

    assert not (tmp_path / "backups").exists()
    database.engine.dispose()


def test_explicitly_replaces_draft_manual_period_after_backup(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.session_factory() as session:
        existing = ReportingMonth(
            year=2026,
            month=1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            snapshot_date=date(2026, 1, 31),
            status="draft",
            source="manual",
        )
        session.add(existing)
        session.flush()
        session.add(
            IncomeEntry(
                reporting_month_id=existing.id,
                income_type="other",
                name="Old row that must only survive in backup",
                gross_amount_kopecks=1,
                tax_amount_kopecks=0,
                net_amount_kopecks=1,
                is_recurring=False,
                include_in_cash_flow=True,
                include_in_passive_income=False,
            )
        )
        session.commit()

    report = apply_legacy_migration(
        database,
        _extraction(),
        source_sha256="f" * 64,
        decisions=_decisions(),
        report_path=tmp_path / "report.json",
        replace_periods={(2026, 1)},
    )

    assert report.replaced_periods == ("2026-01",)
    with database.session_factory() as session:
        month = session.scalar(select(ReportingMonth))
        assert month is not None
        assert month.source == "excel_migration"
        assert session.scalar(select(func.count(IncomeEntry.id))) == 2
        assert (
            session.scalar(
                select(func.count(IncomeEntry.id)).where(
                    IncomeEntry.name == "Old row that must only survive in backup"
                )
            )
            == 0
        )

    import sqlite3

    backup_path = tmp_path / "backups" / f"{report.backup_id}.sqlite3"
    connection = sqlite3.connect(backup_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM income_entries WHERE name = ?",
            ("Old row that must only survive in backup",),
        ).fetchone() == (1,)
    finally:
        connection.close()
    database.engine.dispose()


def test_failed_replacement_restores_original_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(tmp_path)
    with database.session_factory() as session:
        existing = ReportingMonth(
            year=2026,
            month=1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            snapshot_date=date(2026, 1, 31),
            status="draft",
            source="manual",
        )
        session.add(existing)
        session.flush()
        session.add(
            IncomeEntry(
                reporting_month_id=existing.id,
                income_type="other",
                name="Original row",
                gross_amount_kopecks=1,
                tax_amount_kopecks=0,
                net_amount_kopecks=1,
                is_recurring=False,
                include_in_cash_flow=True,
                include_in_passive_income=False,
            )
        )
        session.commit()

    from hermes_finance.services import legacy_migration

    monkeypatch.setattr(
        legacy_migration,
        "_import_month",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
    )

    with pytest.raises(RuntimeError, match="synthetic failure"):
        apply_legacy_migration(
            database,
            _extraction(),
            source_sha256="0" * 64,
            decisions=_decisions(),
            report_path=tmp_path / "report.json",
            replace_periods={(2026, 1)},
        )

    with database.session_factory() as session:
        month = session.scalar(select(ReportingMonth))
        assert month is not None
        assert month.source == "manual"
        assert session.scalar(select(func.count(IncomeEntry.id))) == 1
        assert session.scalar(select(func.count(LegacyMigrationRun.id))) == 0
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
    assert not (tmp_path / "report.json").exists()
    database.engine.dispose()


def test_rolls_back_every_database_row_when_import_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(tmp_path)
    from hermes_finance.services import legacy_migration

    original = legacy_migration._import_month

    def fail_after_month(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)
        raise RuntimeError("synthetic import failure")

    monkeypatch.setattr(legacy_migration, "_import_month", fail_after_month)

    with pytest.raises(RuntimeError, match="synthetic import failure"):
        apply_legacy_migration(
            database,
            _extraction(),
            source_sha256="d" * 64,
            decisions=_decisions(),
            report_path=tmp_path / "report.json",
        )

    with database.session_factory() as session:
        assert session.scalar(select(func.count(ReportingMonth.id))) == 0
        assert session.scalar(select(func.count(Account.id))) == 0
        assert session.scalar(select(func.count(Instrument.id))) == 0
        assert session.scalar(select(func.count(LegacyMigrationRun.id))) == 0
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
    assert not (tmp_path / "report.json").exists()
    database.engine.dispose()


def test_loads_only_create_without_isin_review_decisions(tmp_path: Path) -> None:
    manifest = tmp_path / "review.json"
    review_id = legacy_review_id(2026, 1, "stocks", 61)
    manifest.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "review_id": review_id,
                        "decision": "create_without_isin",
                        "target_isin": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert load_legacy_decisions(manifest) == {review_id: "create_without_isin"}


def test_rejects_review_manifest_that_assigns_an_isin(tmp_path: Path) -> None:
    manifest = tmp_path / "review.json"
    manifest.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "review_id": legacy_review_id(2026, 1, "stocks", 61),
                        "decision": "create_without_isin",
                        "target_isin": "RU000SYNTH01",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must not define target_isin"):
        load_legacy_decisions(manifest)


def test_cli_prints_aggregate_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from hermes_finance import legacy_migration_cli
    from hermes_finance.services.legacy_migration import LegacyMigrationReport

    workbook = tmp_path / "synthetic-private-name.xlsx"
    workbook.write_bytes(b"synthetic")
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "review_id": legacy_review_id(2026, 1, "stocks", 61),
                        "decision": "create_without_isin",
                        "target_isin": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(legacy_migration_cli, "extract_legacy_workbook", lambda *_: _extraction())
    monkeypatch.setattr(
        legacy_migration_cli,
        "apply_legacy_migration",
        lambda *_, **__: LegacyMigrationReport(
            source_sha256="e" * 64,
            backup_id="finance_backup_synthetic",
            months_imported=1,
            periods=("2026-01",),
            replaced_periods=(),
            counts={"position_snapshots": 3},
            not_imported={"debts_receivable": 0, "dividends": 1, "goals": 1},
        ),
    )

    assert (
        legacy_migration_cli.main(
            [
                "--workbook",
                str(workbook),
                "--mapping",
                str(tmp_path / "mapping.json"),
                "--review",
                str(review),
                "--report",
                str(tmp_path / "report.json"),
                "--database",
                str(tmp_path / "finance.db"),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert output == (
        "legacy migration committed: months=1 positions=3 "
        "nullable_isin_policy=create_without_isin "
        "backup=finance_backup_synthetic\n"
    )
    assert "synthetic-private-name" not in output
    assert "Synthetic stock" not in output
