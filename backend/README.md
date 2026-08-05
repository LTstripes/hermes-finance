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

## Test

```bash
uv run python -I -m pytest
```

The repository root [README](../README.md) contains the full development notes and privacy requirements.
