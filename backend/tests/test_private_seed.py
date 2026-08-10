import json
from pathlib import Path

from hermes_finance.database import Database, create_database
from hermes_finance.persistence import Account, AppSettings, Base, SalaryTaxYearContext
from hermes_finance.private_seed_cli import main
from hermes_finance.services.private_seed import load_private_seed


def _seed_payload(*, account_code: str = "SYNTH-ACCOUNT-001") -> dict[str, object]:
    return {
        "schema_version": 1,
        "settings": {
            "base_currency": "RUB",
            "locale": "ru-RU",
            "timezone": "Europe/Moscow",
            "passive_income_goal": {"amount": "125000.00", "currency": "RUB"},
            "formula_version": "v1",
        },
        "accounts": [
            {
                "name": "Synthetic Account",
                "account_type": "brokerage",
                "external_code": account_code,
                "status": "active",
                "include_in_capital": True,
                "include_in_returns": True,
                "notes": "Synthetic fixture",
            }
        ],
    }


def _write_seed(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "private_seed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _database(tmp_path: Path) -> Database:
    database = create_database(tmp_path / "data" / "finance.db")
    Base.metadata.create_all(database.engine)
    return database


def test_private_seed_loader_is_idempotent_and_updates_settings(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        seed_path = _write_seed(tmp_path, _seed_payload())

        first = load_private_seed(database, seed_path)
        second = load_private_seed(database, seed_path)

        assert first.accounts_created == 1
        assert first.accounts_updated == 0
        assert second.accounts_created == 0
        assert second.accounts_updated == 1

        with database.session_factory() as session:
            assert session.query(Account).count() == 1
            account = session.query(Account).one()
            settings = session.query(AppSettings).one()
            assert account.external_code == "SYNTH-ACCOUNT-001"
            assert settings.passive_income_goal_kopecks == 12_500_000
    finally:
        database.engine.dispose()


def test_private_seed_loader_is_atomic_when_validation_fails(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        valid_path = _write_seed(tmp_path, _seed_payload())
        load_private_seed(database, valid_path)

        invalid_path = _write_seed(
            tmp_path,
            {
                **_seed_payload(account_code="SYNTH-ACCOUNT-002"),
                "accounts": [
                    _seed_payload()["accounts"][0],
                    _seed_payload()["accounts"][0],
                ],
            },
        )

        try:
            load_private_seed(database, invalid_path)
        except ValueError as error:
            assert str(error) == "private seed contains duplicate account keys"
        else:
            raise AssertionError("invalid private seed was accepted")

        with database.session_factory() as session:
            assert session.query(Account).count() == 1
            assert session.query(Account).one().external_code == "SYNTH-ACCOUNT-001"
    finally:
        database.engine.dispose()


def test_private_seed_cli_does_not_print_external_codes(tmp_path: Path, capsys) -> None:
    database_path = tmp_path / "data" / "finance.db"
    database = create_database(database_path)
    Base.metadata.create_all(database.engine)
    database.engine.dispose()
    seed_path = _write_seed(tmp_path, _seed_payload(account_code="SYNTH-PRIVATE-CODE-001"))

    exit_code = main(["--database", str(database_path), "--seed", str(seed_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "private seed loaded:" in captured.out
    assert "SYNTH-PRIVATE-CODE-001" not in captured.out
    assert captured.err == ""


def test_private_seed_cli_reports_invalid_seed_without_payload(tmp_path: Path, capsys) -> None:
    database_path = tmp_path / "data" / "finance.db"
    database = create_database(database_path)
    Base.metadata.create_all(database.engine)
    database.engine.dispose()
    seed_path = tmp_path / "private_seed.json"
    seed_path.write_text("{not-json", encoding="utf-8")

    exit_code = main(["--database", str(database_path), "--seed", str(seed_path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out.strip() == "private seed load failed: private seed validation failed"
    assert "not-json" not in captured.out
    assert str(seed_path) not in captured.out


def test_private_seed_upserts_salary_tax_opening_context(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        payload = _seed_payload()
        payload["salary_tax_opening_contexts"] = [
            {
                "tax_year": 2031,
                "effective_from_month": 5,
                "opening_taxable_gross": "400000.00",
            }
        ]
        seed_path = _write_seed(tmp_path, payload)

        load_private_seed(database, seed_path)
        load_private_seed(database, seed_path)

        with database.session_factory() as session:
            contexts = session.query(SalaryTaxYearContext).all()
            assert len(contexts) == 1
            assert contexts[0].tax_year == 2031
            assert contexts[0].effective_from_month == 5
            assert contexts[0].opening_taxable_gross_kopecks == 40_000_000
    finally:
        database.engine.dispose()
