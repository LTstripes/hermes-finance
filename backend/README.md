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

## Test

```bash
uv run python -I -m pytest
```

The repository root [README](../README.md) contains the full development notes and privacy requirements.
