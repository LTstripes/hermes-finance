"""Durable source journal boundaries; only fabricated originals and disposable DBs."""

import json
from datetime import UTC, date, datetime
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_statement_import_mybroker import FILENAME, repo_fixture
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _all_month_tables as _tables,
)
from test_statement_import_mybroker_endpoints import (
    _broker_month_apply,
    _broker_month_preview,
    _broker_month_setup,
    _public_inbox_fixture,
    _source_inbox_xml,
    broker_month_xml,
)

from hermes_finance.main import create_app
from hermes_finance.services import source_intake

BASE = "/api/broker-months/intakes"


@pytest.fixture(autouse=True)
def isolated_public_cache(monkeypatch):
    from hermes_finance.services import public_security_registry as registry

    monkeypatch.setattr(registry, "_cache", {})
    monkeypatch.setattr(registry, "_current", {})


def _all_month_tables(database):
    return {k: v for k, v in _tables(database).items() if not k.startswith("source_intake_")}


def upload(client, path, xml, field, value):
    return client.post(
        path, files={"file": (FILENAME, xml, "application/xml")}, data={field: json.dumps(value)}
    )


def save(client, xml, scope, request_id="save-1"):
    response = upload(client, BASE, xml, "intent", {**scope, "request_id": request_id})
    assert response.status_code == 200, response.text
    ack = response.json()
    response = client.get(f"{BASE}/{ack['intake_id']}")
    assert response.status_code == 200, response.text
    return response.json()


def intent(view, **changes):
    state = view["state"]
    return {
        "expected_head_seq": view["head_seq"],
        "account_id": state["account_id"],
        "reporting_month_id": state["reporting_month_id"],
        "default_enabled": state["default_enabled"],
        "account_currency": state["account_currency"],
        "overrides": [{"isin": k, "currency": v} for k, v in state["overrides"].items()],
        "instrument_decisions": state["instrument_decisions"],
        "deferred_isins": state["deferred_isins"],
        **changes,
    }


def review(client, view, xml, requested, request_id="decision-1", *, link=False):
    response = upload(client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested)
    assert response.status_code == 200, response.text
    plan = response.json()
    response = upload(
        client,
        f"{BASE}/{view['id']}/{'finance-link' if link else 'decisions'}",
        xml,
        "confirmation",
        {**requested, "request_id": request_id, "confirmation_digest": plan["confirmation_digest"]},
    )
    return response


def test_intake_full_inventory_reload_default_override_no_economic_writes(database):
    scope = _broker_month_setup(database)
    xml = _source_inbox_xml(database)
    app = create_app(database=database)
    client = TestClient(app)
    before = _all_month_tables(database)
    view = save(client, xml, scope)
    assert len(view["proposals"]) == 13
    assert any(p["currency_assessment"]["basis"] == "owner_default_rub" for p in view["proposals"])
    assert all(not p["currency_assessment"]["denomination_proven"] for p in view["proposals"])
    assert len(view["document"]["positions"]) == 13
    assert _all_month_tables(database) == before
    assert view["original_required"] and view["financial_authority"] == "none"
    assert source_intake.PENDING in view["exceptions"]
    missing = next(p["isin"] for p in view["proposals"] if p["hermes_id"] is None)
    response = review(
        client, view, xml, intent(view, overrides=[{"isin": missing, "currency": "USD"}])
    )
    assert response.status_code == 200, response.text
    # New app/session has no File or public cache dependency for saved progress.
    restored = TestClient(create_app(database=database)).get(f"{BASE}/{view['id']}").json()
    assumed = next(p["currency_assessment"] for p in restored["proposals"] if p["isin"] == missing)
    assert (assumed["effective_currency"], assumed["basis"], assumed["provisional"]) == (
        "USD",
        "owner_selected",
        True,
    )
    assert restored["state"]["overrides"] == {missing: "USD"}
    assert _all_month_tables(database) == before
    again = save(client, xml, scope, "save-again")
    assert [o["id"] for o in again["observations"]] == [o["id"] for o in view["observations"]]
    assert again["state"]["overrides"] == {missing: "USD"}


@pytest.mark.parametrize("unsupported", [False, True])
def test_finance_link_validates_own_receipt_without_circular_readiness(database, unsupported):
    scope = _broker_month_setup(database)
    xml = broker_month_xml(unsupported=unsupported)
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope)
    plan = _broker_month_preview(client, scope, xml)
    assert plan["can_apply"]
    assert source_intake.PENDING in plan["exceptions"]
    applied = _broker_month_apply(client, scope, plan, xml)
    assert applied.status_code == 200, applied.text
    before_link = _all_month_tables(database)
    response = review(
        client, view, xml, intent(view, finance_request_id="synthetic-batch"), link=True
    )
    assert response.status_code == 200, response.text
    linked = client.get(f"{BASE}/{view['id']}").json()
    assert linked["finance_link"]["request_id"] == "synthetic-batch"
    assert source_intake.PENDING not in linked["exceptions"]
    assert bool(linked["exceptions"]) == unsupported
    assert _all_month_tables(database) == before_link
    with database.session_factory() as session:
        assert source_intake.scoped_status(session, scope["reporting_month_id"])["status"] == (
            "partial" if unsupported else "complete"
        )


def test_intake_delete_rebind_close_and_period_guards(database):
    scope = _broker_month_setup(database)
    xml = broker_month_xml()
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope)
    month_id = scope["reporting_month_id"]
    from hermes_finance.services.reporting_months import (
        close_reporting_month,
        delete_reporting_month,
        update_reporting_month,
    )

    with database.session_factory() as session:
        with pytest.raises(ValueError, match="source_intake_bound_month"):
            delete_reporting_month(session, month_id)
        with pytest.raises(ValueError, match="source_intake_bound_month"):
            update_reporting_month(session, month_id, snapshot_date=date(2030, 2, 1))
        with pytest.raises(ValueError, match="MyBroker"):
            close_reporting_month(session, month_id)
    requested = intent(view, account_id=999)
    response = upload(client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested)
    assert response.status_code == 409
    assert "rebind" in response.text
    assert client.get(f"{BASE}/{view['id']}").json()["head_seq"] == view["head_seq"]


def test_review_aba_and_original_mismatch_never_accept_stale(database):
    scope = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml()
    view = save(client, xml, scope)
    requested = intent(view)
    preview = upload(client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested).json()
    from hermes_finance.services.instruments import update_instrument

    with database.session_factory() as session:
        update_instrument(session, 1, currency="USD")
        update_instrument(session, 1, currency="RUB")
    response = upload(
        client,
        f"{BASE}/{view['id']}/decisions",
        xml,
        "confirmation",
        {**requested, "request_id": "stale", "confirmation_digest": preview["confirmation_digest"]},
    )
    assert response.status_code == 409 and "stale" in response.text
    response = upload(
        client, f"{BASE}/{view['id']}/review-preview", xml + b" ", "intent", requested
    )
    assert response.status_code == 409 and "original_mismatch" in response.text


def test_native_repo_partner_and_opaque_attributes_are_observations_only(database):
    xml = repo_fixture()
    root = ET.fromstring(xml)
    row = root.find(".//{MyBroker}Details[@trade_no]")
    row.set("opaque_native_zero", "0")
    client = TestClient(create_app(database=database))
    before = _all_month_tables(database)
    view = save(client, ET.tostring(root), {})
    refs = [o["facts"].get("native_references", {}) for o in view["observations"]]
    assert any(r.get("repo_no") == "B1002" for r in refs)
    assert any(
        any(a["name"] == "opaque_native_zero" for a in o["facts"].get("attributes", []))
        for o in view["observations"]
    )
    assert any(t["repo_observed"] and t["identity"] is None for t in view["document"]["trades"])
    assert _all_month_tables(database) == before


def test_official_fx_never_becomes_rub_assumption_after_cache_expiry(database, monkeypatch):
    from hermes_finance.services import public_security_registry as registry

    scope = _broker_month_setup(database)
    xml = _source_inbox_xml(database)
    _public_inbox_fixture(monkeypatch, currency="USD")
    client = TestClient(create_app(database=database))
    looked = client.post(
        "/api/broker-months/public-identity-lookup",
        json={"consent": True, "isins": ["RU000A000001"]},
    )
    assert looked.status_code == 200
    view = save(client, xml, scope)
    assessed = next(
        p["currency_assessment"] for p in view["proposals"] if p["isin"] == "RU000A000001"
    )
    assert assessed["effective_currency"] == "USD" and assessed["basis"] == "official_proven"
    requested = intent(view)
    old_plan = upload(
        client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested
    ).json()
    monkeypatch.setattr(registry, "_now", lambda: datetime(2099, 1, 1, tzinfo=UTC))
    reread = client.get(f"{BASE}/{view['id']}").json()
    stale = next(
        p["currency_assessment"] for p in reread["proposals"] if p["isin"] == "RU000A000001"
    )
    assert stale["effective_currency"] == "USD" and stale["basis"] != "owner_default_rub"
    assert "source_intake_public_proof_stale" in reread["exceptions"]
    assert not reread["bookkeeping_ready"]
    rejected = upload(
        client,
        f"{BASE}/{view['id']}/decisions",
        xml,
        "confirmation",
        {
            **requested,
            "request_id": "expired-public-review",
            "confirmation_digest": old_plan["confirmation_digest"],
        },
    )
    assert rejected.status_code == 409 and "stale" in rejected.text


def test_existing_numeric_return_and_presence_claim_get_scoped_pending_defect(database):
    from test_statement_import_broker_statement_return import prepared

    from hermes_finance.persistence import ReportingMonth
    from hermes_finance.services.portfolio_source_coverage import (
        portfolio_source_coverage_for_month,
    )

    client, xml = prepared(database, covered=True)
    path = "/api/broker-statement-returns?account_id=1&request_id=synthetic-batch"
    before = client.get(path).json()
    assert before["status"] == "indicative"
    with database.session_factory() as session:
        month_id = session.scalar(select(ReportingMonth.id))
    view = save(client, xml, {"account_id": 1, "reporting_month_id": month_id})
    unavailable = client.get(path).json()
    assert (
        unavailable["rate_fraction"] is None
        and source_intake.PENDING in unavailable["reason_codes"]
    )
    with database.session_factory() as session:
        coverage = portfolio_source_coverage_for_month(session, month_id)
        assert coverage.status == "complete"  # Existing presence contract is unchanged.
        assert coverage.source_account_financial_coverage["status"] == "partial"
        assert source_intake.scoped_status(session, month_id, 999)["status"] == "complete"
    bundle = client.post("/api/export/ai-analysis-bundle?generated_at=2030-02-01T00:00:00Z")
    assert bundle.status_code == 200, bundle.text
    assert source_intake.PENDING in bundle.json()["current_portfolio"]["coverage"]["reason_codes"]
    linked = review(
        client, view, xml, intent(view, finance_request_id="synthetic-batch"), link=True
    )
    assert linked.status_code == 200, linked.text
    assert client.get(path).json()["status"] == "indicative"


def test_restore_preserves_queue_but_retires_old_confirmations(database):
    from hermes_finance.services.backups import create_backup, restore_backup

    scope = _broker_month_setup(database)
    xml = broker_month_xml()
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope)
    requested = intent(view)
    plan = upload(client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested).json()
    backup = create_backup(database)
    changed = review(client, view, xml, intent(view, default_enabled=False), "change-after-backup")
    assert changed.status_code == 200
    restore_backup(database, backup.id)
    restored = client.get(f"{BASE}/{view['id']}").json()
    assert restored["observations"] == view["observations"] and restored["state"] == view["state"]
    response = upload(
        client,
        f"{BASE}/{view['id']}/decisions",
        xml,
        "confirmation",
        {**requested, "request_id": "old-form", "confirmation_digest": plan["confirmation_digest"]},
    )
    assert response.status_code == 409 and "stale" in response.text


def test_failed_decision_rolls_back_policy_and_all_journal_changes(database, monkeypatch):
    scope = _broker_month_setup(database)
    xml = broker_month_xml()
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope)
    before = _tables(database)
    append = source_intake._append

    def fail(*args, **kwargs):
        row = append(*args, **kwargs)
        if kwargs["operation"] == "decision":
            raise RuntimeError("synthetic late failure")
        return row

    monkeypatch.setattr(source_intake, "_append", fail)
    with pytest.raises(RuntimeError, match="late failure"):
        review(client, view, xml, intent(view, default_enabled=False))
    assert _tables(database) == before


def test_link_replay_aba_and_unrelated_account_isolation(database):
    scope = _broker_month_setup(database)
    xml = broker_month_xml()
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope)
    plan = _broker_month_preview(client, scope, xml)
    assert _broker_month_apply(client, scope, plan, xml).status_code == 200
    requested = intent(view, finance_request_id="synthetic-batch")
    plan = upload(client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested).json()
    confirmed = {
        **requested,
        "request_id": "link-replay",
        "confirmation_digest": plan["confirmation_digest"],
    }
    before = _all_month_tables(database)
    first = upload(client, f"{BASE}/{view['id']}/finance-link", xml, "confirmation", confirmed)
    duplicate = upload(client, f"{BASE}/{view['id']}/finance-link", xml, "confirmation", confirmed)
    assert first.status_code == duplicate.status_code == 200 and duplicate.json()["duplicate"]
    assert _all_month_tables(database) == before
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.instruments import update_instrument

    with database.session_factory() as session:
        create_account(session, name="Unrelated synthetic", account_type="brokerage")
    assert client.get(f"{BASE}/{view['id']}").json()["finance_link"] is not None
    with database.session_factory() as session:
        update_instrument(session, 1, currency="USD")
        update_instrument(session, 1, currency="RUB")
    stale = client.get(f"{BASE}/{view['id']}").json()
    assert stale["finance_link"] is None and source_intake.PENDING in stale["exceptions"]


def test_unbound_bind_once_and_concurrent_decisions_are_atomic(database):
    from concurrent.futures import ThreadPoolExecutor

    scope = _broker_month_setup(database)
    xml = broker_month_xml()
    client = TestClient(create_app(database=database))
    view = save(client, xml, {})
    with database.session_factory() as session:
        assert (
            source_intake.scoped_status(session, scope["reporting_month_id"])["status"]
            == "complete"
        )
    requested = intent(view, **scope)
    plan = upload(client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested).json()

    def confirm(index):
        return upload(
            client,
            f"{BASE}/{view['id']}/decisions",
            xml,
            "confirmation",
            {
                **requested,
                "request_id": f"race-{index}",
                "confirmation_digest": plan["confirmation_digest"],
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(response.status_code for response in pool.map(confirm, range(2)))
    assert statuses == [200, 409]
    reread = client.get(f"{BASE}/{view['id']}").json()
    assert reread["state"]["account_id"] == scope["account_id"] and len(reread["history"]) == 2


def test_close_waits_for_journal_writer_and_rechecks_new_pending(database, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from hermes_finance.persistence import ReportingMonth
    from hermes_finance.services.reporting_months import close_reporting_month

    scope = _broker_month_setup(database)
    xml = broker_month_xml()
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope)
    plan = _broker_month_preview(client, scope, xml)
    assert _broker_month_apply(client, scope, plan, xml).status_code == 200
    assert (
        review(
            client, view, xml, intent(view, finance_request_id="synthetic-batch"), link=True
        ).status_code
        == 200
    )
    linked = client.get(f"{BASE}/{view['id']}").json()
    assert linked["bookkeeping_ready"]
    held, release, closing = Event(), Event(), Event()
    append = source_intake._append

    def pause(*args, **kwargs):
        row = append(*args, **kwargs)
        if kwargs["operation"] == "decision":
            held.set()
            assert release.wait(3)
        return row

    def close():
        closing.set()
        with database.session_factory() as session:
            return close_reporting_month(session, scope["reporting_month_id"])

    monkeypatch.setattr(source_intake, "_append", pause)
    before = _all_month_tables(database)
    with ThreadPoolExecutor(max_workers=2) as pool:
        changing = pool.submit(
            review, client, linked, xml, intent(linked, default_enabled=False), "held-decision"
        )
        assert held.wait(3)
        closing_result = pool.submit(close)
        assert closing.wait(3) and not closing_result.done()
        release.set()
        assert changing.result().status_code == 200
        with pytest.raises(ValueError, match="MyBroker"):
            closing_result.result()
    with database.session_factory() as session:
        assert session.get(ReportingMonth, scope["reporting_month_id"]).status == "draft"
    assert _all_month_tables(database) == before
