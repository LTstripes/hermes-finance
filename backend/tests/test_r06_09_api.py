from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from _statement_pdf import build_income_report_pdf, build_wrong_report_pdf
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_snapshot_apply import BrokerSnapshotApplyFailureCode
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.reporting_months import create_reporting_month

SYN_ISIN = "RU000SYN00001"
SYN_DEPO = "SYN-DEPO-001"


def _context(tmp_path: Path):
    database = create_database(tmp_path / "r06-09-api.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(session, year=2026, month=1, snapshot_date=date(2026, 1, 31))
    account = create_account(
        session, name="Synthetic brokerage", account_type=AccountType.BROKERAGE
    )
    instrument = create_instrument(
        session, name="Synthetic equity", instrument_type=InstrumentType.STOCK, isin=SYN_ISIN
    )
    session.commit()
    session.close()
    return database, month.id, account.id, instrument.id


def test_statement_multipart_prepare_and_apply_are_thin_and_zero_raw_persistence(
    tmp_path: Path,
) -> None:
    database, _month_id, account_id, _instrument_id = _context(tmp_path)
    application = create_app(database)
    document = build_income_report_pdf()
    mapping_json = json.dumps([{"hermes_account_id": account_id, "provider_account_ref": SYN_DEPO}])
    with TestClient(application) as client:
        inspected = client.post(
            "/api/statement-import/inspect",
            files={"document": ("report.pdf", document, "application/pdf")},
        )
        assert inspected.status_code == 200
        assert inspected.json()["rows"][0]["provider_account_ref"] == SYN_DEPO

        prepared = client.post(
            "/api/statement-import/prepare",
            files={"document": ("report.pdf", document, "application/pdf")},
            data={"account_mappings": mapping_json},
        )
        assert prepared.status_code == 200
        body = prepared.json()
        assert body["status"] == "applicable"
        assert body["rows"][0]["status"] == "matched"
        assert body["rows"][0]["provider_account_ref"] is None
        row = body["rows"][0]

        stale = client.post(
            "/api/statement-import/apply",
            files={"document": ("report.pdf", document, "application/pdf")},
            data={
                "account_mappings": mapping_json,
                "selections": json.dumps(
                    [
                        {
                            "natural_identity": row["natural_identity"],
                            "material_fingerprint": row["material_fingerprint"],
                            "expected_hermes_account_id": account_id,
                            "expected_hermes_instrument_id": row["expected_hermes_instrument_id"],
                        }
                    ]
                ),
                "expected_document_sha256": "0" * 64,
            },
        )
        assert stale.status_code == 200
        assert stale.json()["error_code"] == "preview_changed"

        applied = client.post(
            "/api/statement-import/apply",
            files={"document": ("report.pdf", document, "application/pdf")},
            data={
                "account_mappings": mapping_json,
                "selections": json.dumps(
                    [
                        {
                            "natural_identity": row["natural_identity"],
                            "material_fingerprint": row["material_fingerprint"],
                            "expected_hermes_account_id": account_id,
                            "expected_hermes_instrument_id": row["expected_hermes_instrument_id"],
                        }
                    ]
                ),
                "expected_document_sha256": body["document_sha256"],
            },
        )
        assert applied.status_code == 200
        assert applied.json()["success"] is True


def test_broker_snapshot_provider_is_only_called_by_explicit_endpoint(tmp_path: Path) -> None:
    database, month_id, _account_id, _instrument_id = _context(tmp_path)

    class FailingProvider:
        calls = 0

        def fetch_snapshot(self):
            self.calls += 1
            raise RuntimeError("synthetic provider failure")

    provider = FailingProvider()
    application = create_app(database, broker_snapshot_provider=provider)
    assert provider.calls == 0
    with TestClient(application) as client:
        assert provider.calls == 0
        response = client.post(
            f"/api/months/{month_id}/broker-snapshot-preview",
            json={"accounts": [], "instruments": []},
        )
    assert response.status_code == 200
    assert provider.calls == 1
    assert response.json()["error_code"] == "provider_error"
    assert "synthetic provider failure" not in response.text


def test_r06_09_boundaries_and_no_trading_surface(tmp_path: Path) -> None:
    database, month_id, _account_id, _instrument_id = _context(tmp_path)
    with TestClient(create_app(database)) as client:
        too_large = client.post(
            "/api/statement-import/inspect",
            files={"document": ("large.pdf", b"x" * (8 * 1024 * 1024 + 1), "application/pdf")},
        )
        assert too_large.status_code == 413

        malformed = client.post(
            "/api/statement-import/inspect",
            files={"document": ("bad.pdf", b"not a pdf", "application/pdf")},
        )
        assert malformed.status_code == 200
        assert malformed.json()["status"] == "malformed"

        unsupported = client.post(
            "/api/statement-import/inspect",
            files={"document": ("wrong.pdf", build_wrong_report_pdf(), "application/pdf")},
        )
        assert unsupported.status_code == 200
        assert unsupported.json()["status"] in {"unsupported", "non_applicable", "malformed"}

        assert client.get("/api/trading/orders").status_code == 404
        assert client.get("/api/trading").status_code == 404
        assert (
            client.post(
                f"/api/months/{month_id}/broker-snapshot-preview",
                json={"accounts": [], "instruments": []},
            ).status_code
            == 200
        )


def test_snapshot_apply_api_delegates_failure_codes_without_reimplementing_apply(
    tmp_path: Path, monkeypatch
) -> None:
    database, month_id, account_id, instrument_id = _context(tmp_path)
    calls = []

    def fake_apply(*args, **kwargs):
        calls.append((args, kwargs))
        return type(
            "Result",
            (),
            {
                "success": False,
                "selected_count": 1,
                "items": (),
                "error_code": BrokerSnapshotApplyFailureCode.PREVIEW_CHANGED,
                "message": "preview changed",
                "source_as_of": None,
                "captured_at": None,
                "snapshot_status": None,
                "fingerprint": None,
            },
        )()

    monkeypatch.setattr(
        "hermes_finance.api.broker_snapshot.apply_broker_snapshot_preview", fake_apply
    )
    with TestClient(create_app(database)) as client:
        response = client.post(
            f"/api/months/{month_id}/broker-snapshot-apply",
            json={
                "mapping": {"accounts": [], "instruments": []},
                "selections": [
                    {
                        "account_id": account_id,
                        "instrument_id": instrument_id,
                        "fingerprint": "synthetic-fingerprint",
                        "action": "update",
                    }
                ],
            },
        )
    assert response.status_code == 200
    assert response.json()["error_code"] == "preview_changed"
    assert len(calls) == 1
