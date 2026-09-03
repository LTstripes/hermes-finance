"""Synthetic integration tests for the R08 portfolio-review package."""

from __future__ import annotations

import json
import socket
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from startup_network_guard import NETWORK_FORBIDDEN, install_network_guard
from test_ai_analysis_bundle_export import (
    GENERATED_AT,
    _forbid_sql_writes,
    _seed_history,
    _table_counts,
)

from hermes_finance.database import Database, create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services import portfolio_review_package as package_service
from hermes_finance.services.portfolio_review_package import (
    portfolio_review_package_filename,
    render_portfolio_review_markdown,
)

pytestmark = [
    pytest.mark.api,
    pytest.mark.import_export,
    pytest.mark.network_free,
]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "portfolio_review_package.schema.json"
FORBIDDEN_KEYS = {
    "api_key",
    "api_token",
    "backup_path",
    "cookie",
    "credential",
    "database_id",
    "database_path",
    "debug_payload",
    "external_code",
    "file_hash",
    "filesystem_path",
    "password",
    "provider_account_id",
    "provider_identity_key",
    "provider_instrument_uid",
    "raw_payload",
    "reconciliation_id",
    "secret",
    "session_token",
}


@contextmanager
def _forbid_full_network() -> Iterator[None]:
    install_network_guard()
    with pytest.raises(AssertionError, match=NETWORK_FORBIDDEN):
        socket.create_connection(("example.com", 443), timeout=1)
    yield


@pytest.fixture
def app_context(tmp_path: Path) -> Generator[tuple[TestClient, Database], None, None]:
    database = create_database(tmp_path / "portfolio_review_package.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            yield client, database
    finally:
        database.engine.dispose()


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _walk(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _package(client: TestClient, profile: str) -> tuple[object, dict[str, object]]:
    response = client.get(
        "/api/export/portfolio-review-package",
        params={"profile": profile, "generated_at": GENERATED_AT},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return response, payload


def test_full_package_is_schema_valid_read_only_and_privacy_safe(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    _seed_history(client)
    before = _table_counts(database)

    with _forbid_full_network(), _forbid_sql_writes(database.engine):
        response, package = _package(client, "full")

    _validator().validate(package)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert package["schema_name"] == "hermes.finance.portfolio_review_package"
    assert package["schema_version"] == "1.0.0"
    assert package["metadata"]["source_contract_version"] == "1.1.0"
    assert package["profile"] == "full"
    assert package["scope"]["selection_reason"] == "latest_closed"
    assert package["scope"]["requested_sections"] == [
        "capital",
        "positions",
        "dynamics",
        "passive_income",
        "future_cash_flows",
        "freshness",
        "allocation",
        "context",
        "deterministic_insights",
    ]

    sections = package["sections"]
    assert sections["capital"]["data"]["total_net_worth"]["value"] is None
    assert sections["capital"]["data"]["total_net_worth"]["precision"] == "unknown"
    assert sections["dynamics"]["data"]["history"]
    assert (
        sections["passive_income"]["data"]["actual_history_metric_path"]
        == "sections.dynamics.data.history[].passive_income_actual"
    )
    assert all(
        isinstance(item["price_date"], dict) for item in sections["positions"]["data"]["items"]
    )
    allocation = sections["allocation"]["data"]
    assert allocation["allocation_by_account"]["items"]
    assert all(
        item["account_ref"] is None or item["account_ref"].startswith("acct-")
        for metric_name in (
            "allocation_by_asset_class",
            "allocation_by_account",
            "top_positions",
            "payout_concentration",
            "redemption_concentration",
        )
        for item in allocation[metric_name]["items"]
    )
    assert all(
        "evidence" not in item and "comparison_period" not in item
        for item in sections["deterministic_insights"]["data"]["items"]
    )
    assert "evidence" not in json.dumps(package, ensure_ascii=False)
    assert "comparison_period" not in json.dumps(package, ensure_ascii=False)

    keys = {key for value in _walk(package) if isinstance(value, dict) for key in value}
    assert keys.isdisjoint(FORBIDDEN_KEYS)
    serialized = json.dumps(package, ensure_ascii=False).lower()
    assert "d:\\" not in serialized
    assert "c:\\" not in serialized
    assert "file://" not in serialized
    assert "account:" not in serialized
    assert "position:" not in serialized
    assert not any(isinstance(value, float) for value in _walk(package))
    assert before == _table_counts(database)

    post_response = client.post("/api/export/portfolio-review-package")
    assert post_response.status_code == 405


def test_concise_package_marks_full_only_sections_omitted_without_calling_them(
    app_context: tuple[TestClient, Database],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _database = app_context
    _seed_history(client)

    def _unexpected_call(*_args, **_kwargs):
        raise AssertionError("concise profile assembled a full-only source")

    monkeypatch.setattr(package_service, "risk_allocation_for_month", _unexpected_call)
    monkeypatch.setattr(package_service, "build_deterministic_insights", _unexpected_call)

    _response, package = _package(client, "concise")
    _validator().validate(package)
    assert package["scope"]["requested_sections"] == [
        "capital",
        "positions",
        "dynamics",
        "passive_income",
        "future_cash_flows",
        "freshness",
    ]
    for name in ("allocation", "context", "deterministic_insights"):
        assert package["sections"][name] == {
            "status": "omitted",
            "reason_codes": ["profile_concise"],
            "data": None,
        }
    assert {item["path"] for item in package["field_states"] if item["status"] == "omitted"} == {
        "sections.allocation",
        "sections.context",
        "sections.deterministic_insights",
    }


def test_full_package_marks_unavailable_optional_read_model_explicitly(
    app_context: tuple[TestClient, Database],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _database = app_context
    _seed_history(client)

    def _unavailable(*_args, **_kwargs):
        raise LookupError("synthetic read-model absence")

    monkeypatch.setattr(package_service, "risk_allocation_for_month", _unavailable)
    _response, package = _package(client, "full")
    _validator().validate(package)

    assert package["sections"]["allocation"] == {
        "status": "unavailable",
        "reason_codes": ["risk_allocation_unavailable"],
        "data": None,
    }
    assert any(
        item["path"] == "sections.allocation" and item["status"] == "unavailable"
        for item in package["field_states"]
    )


def test_markdown_download_is_rendered_from_the_same_dto_and_keeps_privacy_boundary(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    _seed_history(client)
    before = _table_counts(database)

    with _forbid_full_network(), _forbid_sql_writes(database.engine):
        response = client.get(
            "/api/export/portfolio-review-package/markdown",
            params={"profile": "concise", "generated_at": GENERATED_AT},
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="hermes-portfolio-review-2026-04-30-concise.md"'
    )
    report = response.text
    assert "# Hermes Finance — пакет для анализа (concise)" in report
    assert "Чистый ликвидный капитал: 1386001.00 ₽" in report, report
    assert "Распределение и концентрация**: опущен профилем" in report
    assert "Совокупный капитал: недоступно" in report
    assert "Никакие данные не отправляются автоматически" in report
    assert "d:\\" not in report.lower()
    assert "file://" not in report.lower()
    assert before == _table_counts(database)


def test_json_download_has_a_profiled_filename_and_markdown_renderer_revalidates_dto(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    _seed_history(client)
    response, package = _package(client, "full")

    assert response.status_code == 200
    assert (
        portfolio_review_package_filename(
            as_of_date=date.fromisoformat(package["metadata"]["as_of_date"]),
            profile="full",
            media="json",
        )
        == "hermes-portfolio-review-2026-04-30-full.json"
    )
    report = render_portfolio_review_markdown(package)
    assert "## Детерминированные сигналы" in report
    assert "## Ограничения" in report

    download = client.get(
        "/api/export/portfolio-review-package/json",
        params={"profile": "full", "generated_at": GENERATED_AT},
    )
    assert download.status_code == 200, download.text
    assert download.headers["content-disposition"] == (
        'attachment; filename="hermes-portfolio-review-2026-04-30-full.json"'
    )
    assert download.json() == package
