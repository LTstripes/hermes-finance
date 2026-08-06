# Hermes Finance Backend

Minimal local FastAPI backend for Hermes Finance.

Requires Python 3.13 and `uv`. Python 3.13 is pinned in `.python-version` so editable installs work correctly from Windows paths containing non-ASCII characters.

## Install

```bash
uv sync --group dev
```

## Run

```bash
uv run hermes-finance-api
```

The default address is `http://127.0.0.1:8000`. Local overrides can be placed in `.env`; use `.env.example` as the safe template.

The default SQLite path is the repository-root `data/finance.db`. Starting the local CLI creates its parent directory, configures a SQLAlchemy 2 engine and session factory, and enables SQLite foreign keys for every connection. Override the path with `HERMES_FINANCE_DATABASE_PATH`; tests must always point it at temporary synthetic data and never open the production path.

## Migrations

Alembic tracks schema history. B02 provides an empty service baseline; B04 adds the `app_settings` singleton; B05 adds `reporting_months`; B06 adds `accounts`; B07 adds IIS profiles, contributions and tax benefits; B08 adds the `instruments` reference table; B09 adds `position_snapshots`; B10 adds `deposit_snapshots`; B11 adds `cash_balances`; B12 adds `income_entries`; later backlog tasks add domain tables in new migrations.

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic downgrade base
```

All commands use `HERMES_FINANCE_DATABASE_PATH` or the default database path. Run destructive downgrade commands only against a backup or synthetic database.

## Financial value types

`hermes_finance.domain` exposes `RubleAmount` and `PercentageRate` without depending on FastAPI or SQLAlchemy. API inputs are decimal strings, domain calculations use `Decimal`, and persistence-facing values are integer kopecks or basis points. Binary `float`, non-finite decimals and malformed API strings are rejected.

Conversions to the nearest kopeck or basis point use `ROUND_HALF_UP`, so exact half values round away from zero. API output always uses two decimal places: `RubleAmount.to_api()` returns RUB major units and `PercentageRate.to_api()` returns percentage points.

## Test

```bash
uv run python -I -m pytest
```

The repository root [README](../README.md) contains the full development notes and privacy requirements.
