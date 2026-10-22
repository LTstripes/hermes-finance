"""Durable source journal boundaries; only fabricated originals and disposable DBs."""

import json
import logging
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


def test_save_conflict_returns_reason_and_logs_only_reason_and_request_id(database, caplog):
    client = TestClient(create_app(database=database))
    request_id = "synthetic-conflict-request"
    filename = FILENAME.replace("1234567", "7654321")
    document = b"<Report><Amount>987654.32</Amount><ISIN>SYNTH000001</ISIN>"
    with caplog.at_level(logging.WARNING, logger="hermes_finance.api.source_intake"):
        response = client.post(
            BASE,
            files={"file": (filename, document, "application/xml")},
            data={"intent": json.dumps({"request_id": request_id})},
        )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "conflict",
        "message": "xml_invalid",
        "details": [],
    }
    records = [r for r in caplog.records if r.name == "hermes_finance.api.source_intake"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    assert record.getMessage() == f"reason=xml_invalid request_id={request_id}"
    assert record.args == ("xml_invalid", request_id)
    assert record.exc_info is None
    for sensitive in (filename, "7654321", "987654.32", "SYNTH000001", document.decode()):
        assert sensitive not in repr(record.__dict__)


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


@pytest.mark.parametrize("choice", ["incompatible", "defer"])
@pytest.mark.parametrize("legacy_link", [False, True])
def test_current_journal_choice_cannot_be_laundered_by_strict_receipt(
    database, choice, legacy_link
):
    from test_statement_import_broker_statement_return import prepared

    from hermes_finance.persistence import (
        CashBoundaryCoverage,
        ReportingMonth,
        SourceIntakeOriginal,
    )
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.broker_months import broker_month_close_blockers
    from hermes_finance.services.instruments import create_instrument
    from hermes_finance.services.reporting_months import close_reporting_month
    from hermes_finance.services.source_cash_coverage import read_source_cash_coverage

    with database.session_factory() as session:
        wrong = create_instrument(
            session, name="Different synthetic stock", instrument_type="stock", isin="RU000A000002"
        )
        other = create_account(
            session, name="Unaffected synthetic account", account_type="brokerage"
        )
    # The clean strict SOURCE and effective actual cash proof precede the intake.
    client, xml = prepared(database, covered=True)
    returns_url = "/api/broker-statement-returns?account_id=1&request_id=synthetic-batch"
    assert client.get(returns_url).json()["status"] == "indicative"
    with database.session_factory() as session:
        month_id = session.scalar(select(ReportingMonth.id))
        coverage_id = session.scalar(select(CashBoundaryCoverage.id))
        assert read_source_cash_coverage(session, coverage_id)["effective_state"] == "accepted"
        assert broker_month_close_blockers(session, month_id) == ()
    view = save(client, xml, {"account_id": 1, "reporting_month_id": month_id})
    proposal = view["proposals"][0]
    with database.session_factory() as session:
        clean_link = source_intake._link_authority(
            session, session.get(SourceIntakeOriginal, view["id"]), view["state"], "synthetic-batch"
        )
    economic_before = _all_month_tables(database)
    changes = (
        {"instrument_decisions": [{"isin": proposal["isin"], "hermes_id": wrong.id}]}
        if choice == "incompatible"
        else {"deferred_isins": [proposal["isin"]]}
    )
    assert (
        review(client, view, xml, intent(view, **changes), "unresolved-choice").status_code == 200
    )
    pending = client.get(f"{BASE}/{view['id']}").json()
    if legacy_link:
        # Fabricate an old-version journal link that omitted identity choices from
        # its signature. GET must revalidate current state, not trust old acceptance.
        with database.session_factory() as session:
            source_intake._append(
                session,
                request_id="legacy-link",
                fingerprint="a" * 64,
                operation="finance_link",
                payload={"state": pending["state"], "link": clean_link},
                original=session.get(SourceIntakeOriginal, view["id"]),
                account_id=1,
                month_id=month_id,
                predecessor=pending["head_seq"],
            )
            session.commit()
    else:
        requested = intent(pending, finance_request_id="synthetic-batch")
        before_attempt = _tables(database)
        preview = upload(client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested)
        assert preview.status_code == 409, preview.text
        confirmed = upload(
            client,
            f"{BASE}/{view['id']}/finance-link",
            xml,
            "confirmation",
            {**requested, "request_id": "refused-link", "confirmation_digest": "0" * 64},
        )
        assert confirmed.status_code == 409, confirmed.text
        assert _tables(database) == before_attempt
    current = client.get(f"{BASE}/{view['id']}").json()
    expected = (
        "instrument_owner_selection_incompatible"
        if choice == "incompatible"
        else "source_intake_identity_deferred"
    )
    assert current["finance_link"] is None and not current["bookkeeping_ready"]
    assert not current["can_close"] and {source_intake.PENDING, expected} <= set(
        current["exceptions"]
    )
    listed = client.get(f"{BASE}?reporting_month_id={month_id}").json()
    assert listed[0]["exceptions"] == current["exceptions"]
    with database.session_factory() as session:
        assert source_intake.scoped_status(session, month_id, 1)["status"] == "partial"
        assert source_intake.scoped_status(session, month_id, other.id)["status"] == "complete"
        assert (
            source_intake.interval_blockers(
                session, date(2029, 12, 31), date(2030, 1, 31), [other.id]
            )
            == []
        )
        cash = read_source_cash_coverage(session, coverage_id)
        assert (
            cash["effective_state"] == "invalidated" and source_intake.PENDING in cash["blockers"]
        )
        assert source_intake.PENDING in {
            code for code, _ in broker_month_close_blockers(session, month_id)
        }
        with pytest.raises(ValueError, match="MyBroker"):
            close_reporting_month(session, month_id)
    affected = client.get(returns_url).json()
    assert affected["rate_fraction"] is None and source_intake.PENDING in affected["reason_codes"]
    exact = client.get(
        "/api/performance/xirr?scope=account&account_id=1&start_date=2029-12-31&end_date=2030-01-31"
    ).json()
    # Source-native XIRR already refuses earlier for its unproved exact basis.
    assert exact["quality"] == "unavailable" and exact["value"] is None
    assert _all_month_tables(database) == economic_before
    # Only an explicit compatible decision/removal of deferral permits a fresh
    # link to the SAME strict receipt; no new financial Apply is involved.
    compatible = [{"isin": proposal["isin"], "hermes_id": proposal["hermes_id"]}]
    assert (
        review(
            client,
            current,
            xml,
            intent(current, instrument_decisions=compatible, deferred_isins=[]),
            "resolve-choice",
        ).status_code
        == 200
    )
    resolved = client.get(f"{BASE}/{view['id']}").json()
    requested = intent(resolved, finance_request_id="synthetic-batch")
    plan = upload(client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested).json()
    confirmed = {
        **requested,
        "request_id": "resolved-link",
        "confirmation_digest": plan["confirmation_digest"],
    }
    assert (
        upload(
            client, f"{BASE}/{view['id']}/finance-link", xml, "confirmation", confirmed
        ).status_code
        == 200
    )
    replay = upload(client, f"{BASE}/{view['id']}/finance-link", xml, "confirmation", confirmed)
    assert replay.status_code == 200 and replay.json()["duplicate"]
    complete = client.get(f"{BASE}/{view['id']}").json()
    assert complete["finance_link"] and not complete["exceptions"] and complete["bookkeeping_ready"]
    assert client.get(returns_url).json()["status"] == "indicative"
    # Equal restored choices cannot resurrect an older accepted link or its ACK.
    assert (
        review(client, complete, xml, intent(complete, **changes), "aba-choice").status_code == 200
    )
    interrupted = client.get(f"{BASE}/{view['id']}").json()
    assert (
        review(
            client,
            interrupted,
            xml,
            intent(interrupted, instrument_decisions=compatible, deferred_isins=[]),
            "aba-resolve",
        ).status_code
        == 200
    )
    replay = upload(client, f"{BASE}/{view['id']}/finance-link", xml, "confirmation", confirmed)
    assert replay.status_code == 200 and replay.json()["duplicate"]
    restored = client.get(f"{BASE}/{view['id']}").json()
    assert restored["finance_link"] is None and source_intake.PENDING in restored["exceptions"]
    assert client.get(returns_url).json()["rate_fraction"] is None
    assert (
        review(
            client,
            restored,
            xml,
            intent(restored, finance_request_id="synthetic-batch"),
            "aba-fresh-link",
            link=True,
        ).status_code
        == 200
    )
    assert client.get(returns_url).json()["status"] == "indicative"
    assert _all_month_tables(database) == economic_before
    with database.session_factory() as session:
        assert broker_month_close_blockers(session, month_id) == ()


@pytest.mark.parametrize("changed_proof", ["expired", "different"])
def test_saved_creation_proof_reconciles_only_to_exact_current_receipt_proof(
    database, monkeypatch, changed_proof
):
    from datetime import timedelta

    from hermes_finance.persistence import BrokerMonthApply
    from hermes_finance.services import broker_months
    from hermes_finance.services import public_security_registry as registry

    scope = _broker_month_setup(database)
    xml = broker_month_xml(bond=True)
    _public_inbox_fixture(monkeypatch)
    client = TestClient(create_app(database=database))
    proof = client.post(
        "/api/broker-months/public-identity-lookup",
        json={"consent": True, "isins": ["RU000A000001"]},
    ).json()[0]
    view = save(client, xml, scope)
    decisions = [{"isin": "RU000A000001", "proof_id": proof["proof_id"]}]
    assert (
        review(
            client, view, xml, intent(view, instrument_decisions=decisions), "save-proof-choice"
        ).status_code
        == 200
    )
    saved = client.get(f"{BASE}/{view['id']}").json()
    financial_intent = {**scope, "instrument_decisions": decisions}
    plan = _broker_month_preview(client, financial_intent, xml)
    assert plan["can_apply"], plan
    assert _broker_month_apply(client, financial_intent, plan, xml).status_code == 200
    financial_get = client.get("/api/broker-months/synthetic-batch")
    assert financial_get.status_code == 200
    before = _all_month_tables(database)
    requested = intent(saved, finance_request_id="synthetic-batch")
    link_plan = upload(
        client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested
    ).json()
    assert (
        review(
            client,
            saved,
            xml,
            intent(saved, finance_request_id="synthetic-batch"),
            "proof-link",
            link=True,
        ).status_code
        == 200
    )
    linked = client.get(f"{BASE}/{view['id']}").json()
    assert linked["finance_link"] and source_intake.PENDING not in linked["exceptions"]
    assert linked["state"] == saved["state"]  # No transformed decision is persisted.
    replay = upload(
        client,
        f"{BASE}/{view['id']}/finance-link",
        xml,
        "confirmation",
        {
            **requested,
            "request_id": "proof-link",
            "confirmation_digest": link_plan["confirmation_digest"],
        },
    )
    assert replay.status_code == 200 and replay.json()["duplicate"]
    with database.session_factory() as session:
        # Any financial/NKD limitation is retained verbatim, never waived by proof.
        receipt = session.get(BrokerMonthApply, "synthetic-batch")
        assert set(linked["exceptions"]) == set(broker_months._readiness(session, receipt))
    assert _all_month_tables(database) == before
    if changed_proof == "expired":
        monkeypatch.setattr(registry, "_now", lambda: datetime(2099, 1, 1, tzinfo=UTC))
    else:
        later = datetime.now(UTC) + timedelta(minutes=1)
        monkeypatch.setattr(registry, "_now", lambda: later)
        registry._cache.clear()
        next_proof = client.post(
            "/api/broker-months/public-identity-lookup",
            json={"consent": True, "isins": ["RU000A000001"]},
        ).json()[0]
        assert next_proof["proof_id"] != proof["proof_id"]
        assert (
            review(
                client,
                linked,
                xml,
                intent(
                    linked,
                    instrument_decisions=[
                        {"isin": "RU000A000001", "proof_id": next_proof["proof_id"]}
                    ],
                ),
                "different-proof-choice",
            ).status_code
            == 200
        )
    stale = client.get(f"{BASE}/{view['id']}").json()
    assert stale["finance_link"] is None and source_intake.PENDING in stale["exceptions"]
    rejected = upload(
        client,
        f"{BASE}/{view['id']}/review-preview",
        xml,
        "intent",
        intent(stale, finance_request_id="synthetic-batch"),
    )
    assert rejected.status_code == 409
    assert _all_month_tables(database) == before


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
    from hermes_finance.services.cash import create_cash_balance, update_cash_balance
    from hermes_finance.services.instruments import update_instrument

    with database.session_factory() as session:
        other = create_account(session, name="Unrelated synthetic", account_type="brokerage")
        cash = create_cash_balance(
            session,
            reporting_month_id=scope["reporting_month_id"],
            account_id=other.id,
            name="Unrelated cash",
            amount="1.00",
        )
        update_cash_balance(session, cash.id, amount="2.00")
        update_cash_balance(session, cash.id, amount="1.00")
    assert client.get(f"{BASE}/{view['id']}").json()["finance_link"] is not None
    with database.session_factory() as session:
        update_instrument(session, 1, currency="USD")
        update_instrument(session, 1, currency="RUB")
    stale = client.get(f"{BASE}/{view['id']}").json()
    assert stale["finance_link"] is None and source_intake.PENDING in stale["exceptions"]


@pytest.mark.parametrize(
    ("table", "writer"),
    [("cash_balances", "service"), ("cash_balances", "sql"), ("position_snapshots", "sql")],
)
def test_financial_projection_aba_requires_fresh_explicit_link(database, table, writer):
    from sqlalchemy import text

    from hermes_finance.services.reporting_months import close_reporting_month

    scope = _broker_month_setup(database)
    xml = broker_month_xml()
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope)
    plan = _broker_month_preview(client, scope, xml)
    assert _broker_month_apply(client, scope, plan, xml).status_code == 200
    requested = intent(view, finance_request_id="synthetic-batch")
    assert review(client, view, xml, requested, "initial-link", link=True).status_code == 200
    assert client.get(f"{BASE}/{view['id']}").json()["finance_link"] is not None
    field = "amount_kopecks" if table == "cash_balances" else "market_value_kopecks"
    with database.session_factory() as session:
        row_id, original = session.execute(text(f"SELECT id, {field} FROM {table} LIMIT 1")).one()

    def edit(value):
        with database.session_factory() as session:
            if writer == "service":
                from hermes_finance.services.cash import update_cash_balance

                update_cash_balance(session, row_id, amount=f"{value // 100}.{value % 100:02}")
            else:
                # SQL-level guards also cover writes outside ORM listeners.
                session.execute(text(f"UPDATE {table} SET {field} = :value"), {"value": value})
                session.commit()

    edit(original + 1)
    assert client.get(f"{BASE}/{view['id']}").json()["finance_link"] is None
    edit(original)
    stale = client.get(f"{BASE}/{view['id']}").json()
    assert stale["finance_link"] is None and source_intake.PENDING in stale["exceptions"]
    with database.session_factory() as session:
        with pytest.raises(ValueError, match="MyBroker"):
            close_reporting_month(session, scope["reporting_month_id"])
    # Equal economic values restore own receipt authority, never old review authority.
    response = review(
        client,
        stale,
        xml,
        intent(stale, finance_request_id="synthetic-batch"),
        "fresh-link",
        link=True,
    )
    assert response.status_code == 200, response.text
    assert client.get(f"{BASE}/{view['id']}").json()["finance_link"] is not None


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


def test_old_shape_intake_nominal_reattaches_for_review_without_manifest_upgrade(
    database, monkeypatch
):
    from hermes_finance.statement_import import mybroker

    scope = _broker_month_setup(database)
    root = ET.fromstring(broker_month_xml())
    root.find(".//{MyBroker}Details[@ISIN1]").set("nominal", "500")
    root.find(".//{MyBroker}Details[@trade_no]").set("nominal", "1000")
    xml = ET.tostring(root)
    client = TestClient(create_app(database=database))
    with monkeypatch.context() as old:
        old.setattr(mybroker, "_face_value_fields", lambda *args, **kwargs: {})
        view = save(client, xml, scope)
    before = _tables(database)
    response = upload(client, f"{BASE}/{view['id']}/review-preview", xml, "intent", intent(view))
    assert response.status_code == 200, response.text
    assert response.json()["manifest_digest"] == view["manifest_digest"]
    assert response.json()["financial_effects"] == 0
    assert _tables(database) == before
    restored = client.get(f"{BASE}/{view['id']}").json()
    assert restored["document"] == view["document"]
    assert restored["manifest_digest"] == view["manifest_digest"]


# Real multipart Save -> ACK -> independent GET -> source-return APIs. The UI's
# multi-file picker sends one independent request per file, including duplicates.
@pytest.fixture
def history_client(tmp_path):
    from test_statement_import_broker_statement_provisional import _free_database

    db = _free_database(tmp_path)
    with TestClient(create_app(database=db)) as client:
        yield client, db
    db.engine.dispose()


def _history_batch(client, originals):
    from concurrent.futures import ThreadPoolExecutor

    def upload_one(item):
        index, (filename, xml) = item
        return client.post(
            BASE,
            files={"file": (filename, xml, "application/xml")},
            data={"intent": json.dumps({"request_id": f"history-upload-{index}"})},
        )

    with ThreadPoolExecutor(max_workers=4) as workers:
        return list(workers.map(upload_one, enumerate(originals)))


def _history_returns(client, account, kind):
    response = client.get(f"/api/source-returns/{kind}", params={"source_account": account})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["financial_authority"] == "none"
    return result


def test_history_native_eight_file_batch_is_saved_with_empty_account_and_filename_period(
    history_client,
):
    from history_import_fixtures import ACCOUNTS, LONG_END, LONG_START, history_trade, history_xml
    from test_source_monthly_returns_service import snapshot
    from test_statement_import_broker_statement_provisional import _finite_tables

    client, db = history_client
    financial_before = _finite_tables(db)
    originals = []
    for index, account in enumerate(ACCOUNTS):
        empty = index == 3
        trade = history_trade(date(2026, 6, 15), index + 1, repo="90001" if index < 2 else "")
        money = (
            (date(2026, 6, 15), "Перевод", "Synthetic own-account transfer", "500"),
            (date(2026, 6, 16), "Комиссия", "Synthetic fee", "-2"),
            (date(2026, 6, 17), "НДФЛ", "Synthetic tax", "-3"),
        )
        for start, end in ((LONG_START, LONG_END), (date(2026, 6, 1), date(2026, 6, 30))):
            originals.append(
                history_xml(
                    account=account,
                    start=start,
                    end=end,
                    trades=(trade,),
                    money=money,
                    empty=empty,
                    native_structure=True,
                )
            )
    responses = _history_batch(client, originals)
    assert [r.status_code for r in responses] == [200] * 8, [r.text for r in responses]
    for index, response in enumerate(responses):
        view = client.get(f"{BASE}/{response.json()['intake_id']}").json()
        assert view["state"]["account_id"] is None
        assert view["state"]["reporting_month_id"] is None
        assert view["financial_authority"] == "none" and view["exceptions"]
        assert view["covered_from"] == (LONG_START.isoformat() if index % 2 == 0 else "2026-06-01")
        assert view["covered_to"] == (LONG_END.isoformat() if index % 2 == 0 else "2026-06-30")
        if index >= 6:
            assert view["document"]["positions"] == []
            assert view["document"]["trades"] == []
            assert view["document"]["money"] == []
            assert not any(
                o["facts"].get("native_references", {}).get("acc_code")
                for o in view["observations"]
            )
    assert len(client.get(BASE, params={"include_unbound": True}).json()) == 8
    before = snapshot(db)
    for account in (*ACCOUNTS[:3], ACCOUNTS[3].split("-")[0]):
        monthly = _history_returns(client, account, "monthly")
        instruments = _history_returns(client, account, "instruments")
        if account == ACCOUNTS[3].split("-")[0]:
            assert instruments["instruments"] == []
            assert all(m["growth_kopecks"] is None for m in monthly["months"])
        else:
            assert "unrecognized_money" in {g["code"] for g in monthly["gaps"]}
            assert all(
                m["total_kopecks"] is None for i in instruments["instruments"] for m in i["months"]
            )
    assert snapshot(db) == before
    assert _finite_tables(db) == financial_before


def test_history_partial_long_report_keeps_calendar_and_dated_flows(history_client):
    from history_import_fixtures import ACCOUNTS, history_trade, history_xml

    client, _ = history_client
    day = date(2026, 6, 15)
    report = history_xml(
        trades=(history_trade(day, 1),),
        money=((day, "Внесено по распоряжению Клиента", "Synthetic funding", "500"),),
    )
    (response,) = _history_batch(client, [report])
    assert response.status_code == 200, response.text
    result = _history_returns(client, ACCOUNTS[0], "monthly")
    assert len(result["months"]) == 32
    assert result["months"][0]["closing_date"] == "2024-03-31"
    assert result["months"][-1]["closing_date"] == "2026-10-31"
    assert all(
        m["growth_kopecks"] is None and m["modified_dietz_return"] is None for m in result["months"]
    )
    june = next(m for m in result["months"] if m["closing_date"] == "2026-06-30")
    assert june["contributions_kopecks"] == 50_000
    assert result["period"]["contributions_kopecks"] == 50_000
    assert result["period"]["chained_return"] is None
    assert "partial_month_source" in {g["code"] for g in result["gaps"]}


def test_history_long_monthly_overlap_deduplicates_trades_income_and_reupload(history_client):
    from history_import_fixtures import ACCOUNTS, BOND, history_trade, history_xml
    from test_statement_import_mybroker import ISIN

    client, db = history_client
    day = date(2026, 6, 15)
    trades = (
        history_trade(day, 1),
        history_trade(day, 2, isin=BOND, price="100", amount="1020", nkd="20"),
    )
    money = (
        (day, "Внесено по распоряжению Клиента", "Synthetic funding", "500"),
        (day, "Купон", f"Payment {BOND}", "30"),
    )
    long = history_xml(trades=trades, money=money)
    monthly = history_xml(start=date(2026, 6, 1), end=date(2026, 6, 30), trades=trades, money=money)
    responses = _history_batch(client, [long, monthly, monthly])
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert responses[1].json()["intake_id"] == responses[2].json()["intake_id"]
    assert len(client.get(BASE, params={"include_unbound": True}).json()) == 2
    account = ACCOUNTS[0]
    result = _history_returns(client, account, "monthly")
    june = next(m for m in result["months"] if m["closing_date"] == "2026-06-30")
    assert june["contributions_kopecks"] == 50_000 and june["coupons_kopecks"] == 3_000
    assert len(result["flows"]) == 1 and len(result["flows"][0]["source_references"]) == 2
    assert "overlap_flow_deduplicated" in {g["code"] for g in result["gaps"]}
    result = _history_returns(client, account, "instruments")
    instruments = {i["isin"]: i for i in result["instruments"]}
    stock = next(m for m in instruments[ISIN]["months"] if m["month"] == "2026-06-01")
    bond = next(m for m in instruments[BOND]["months"] if m["month"] == "2026-06-01")
    assert stock["buys_cost_kopecks"] == 10_100  # Stock omits NKD.
    assert bond["buys_cost_kopecks"] == 102_100  # Included NKD counted once.
    assert bond["coupons_kopecks"] == 3_000
    assert instruments[ISIN]["all_time"]["buys_cost_kopecks"] == 10_100
    # New app/session reload, duplicate ACK and return reads do not add observations.
    from test_source_monthly_returns_service import snapshot

    before = snapshot(db)
    with TestClient(create_app(database=db)) as restarted:
        assert _history_returns(restarted, account, "instruments") == result
    assert snapshot(db) == before


def test_history_sparse_trade_months_do_not_invent_month_end_returns(history_client):
    from history_import_fixtures import ACCOUNTS, history_trade, history_xml
    from test_statement_import_mybroker import ISIN

    client, _ = history_client
    days = (
        date(2024, 3, 26),
        date(2024, 4, 15),
        date(2025, 2, 15),
        date(2026, 5, 15),
        date(2026, 7, 15),
    )
    two_months = (date(2024, 4, 16), date(2026, 7, 16))
    reports = [
        history_xml(
            account=account,
            trades=tuple(history_trade(day, index + 1) for index, day in enumerate(dates)),
        )
        for account, dates in ((ACCOUNTS[0], days), (ACCOUNTS[2], two_months))
    ]
    assert all(r.status_code == 200 for r in _history_batch(client, reports))
    for account in (ACCOUNTS[0], ACCOUNTS[2]):
        monthly = _history_returns(client, account, "monthly")
        assert len(monthly["months"]) == 32
        for month in ("2024-05-01", "2025-01-01", "2026-06-01"):
            row = next(m for m in monthly["months"] if m["closing_date"][:7] == month[:7])
            assert row["opening_kopecks"] is None and row["closing_kopecks"] is None
            assert row["growth_kopecks"] is None and "missing_endpoint" in row["flags"]
        instrument = next(
            i
            for i in _history_returns(client, account, "instruments")["instruments"]
            if i["isin"] == ISIN
        )
        row = next(m for m in instrument["months"] if m["month"] == "2026-06-01")
        assert row["total_kopecks"] is None and row["return_percent"] is None
        assert "2026-06-01" in instrument["all_time"]["partial_months"]
        assert instrument["all_time"]["return_percent"] is None


@pytest.mark.parametrize("account_index", [0, 1])
def test_history_repo_withholds_affected_instrument_month(history_client, account_index):
    from history_import_fixtures import ACCOUNTS, history_trade, history_xml
    from test_statement_import_mybroker import ISIN

    client, _ = history_client
    day = date(2026, 6, 15)
    report = history_xml(
        account=ACCOUNTS[account_index],
        start=date(2026, 6, 1),
        end=date(2026, 6, 30),
        trades=(history_trade(day, 1, repo="987654"),),
    )
    (response,) = _history_batch(client, [report])
    assert response.status_code == 200, response.text
    view = client.get(f"{BASE}/{response.json()['intake_id']}").json()
    assert view["document"]["trades"][0]["repo_observed"]
    result = _history_returns(client, ACCOUNTS[account_index], "instruments")
    row = next(i for i in result["instruments"] if i["isin"] == ISIN)["months"][0]
    assert row["buys_cost_kopecks"] is None and row["total_kopecks"] is None
    assert "repo_trade_unsupported" in row["flags"]


def test_history_non_1000_bond_is_withheld_without_poisoning_stock(history_client):
    from history_import_fixtures import ACCOUNTS, BOND, history_trade, history_xml
    from test_statement_import_mybroker import ISIN

    client, _ = history_client
    day = date(2026, 6, 15)
    report = history_xml(
        start=date(2026, 6, 1),
        end=date(2026, 6, 30),
        trades=(
            history_trade(day, 1),
            history_trade(day, 2, isin=BOND, price="100", amount="820", nkd="20"),
        ),
    )
    (response,) = _history_batch(client, [report])
    assert response.status_code == 200, response.text
    result = _history_returns(client, ACCOUNTS[0], "instruments")
    instruments = {i["isin"]: i for i in result["instruments"]}
    bond, stock = instruments[BOND]["months"][0], instruments[ISIN]["months"][0]
    for field in (
        "buys_cost_kopecks",
        "sells_proceeds_kopecks",
        "price_effect_kopecks",
        "total_kopecks",
        "return_percent",
    ):
        assert bond[field] is None
    assert "trade_nkd_basis_unknown" in bond["flags"]
    assert stock["buys_cost_kopecks"] == 10_100 and stock["total_kopecks"] == 9_900


def test_history_month_boundary_own_transfer_requires_explicit_classification(history_client):
    from history_import_fixtures import ACCOUNTS, history_xml

    client, _ = history_client
    outgoing, incoming = date(2026, 5, 31), date(2026, 6, 1)
    reports = [
        history_xml(
            account=account,
            start=date(2026, 5, 1),
            end=date(2026, 6, 30),
            money=((day, "Перевод", f"Synthetic own transfer {counterparty}", amount),),
        )
        for account, day, counterparty, amount in (
            (ACCOUNTS[0], outgoing, ACCOUNTS[1], "-500"),
            (ACCOUNTS[1], incoming, ACCOUNTS[0], "500"),
        )
    ]
    responses = _history_batch(client, reports)
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    for account, response, day in zip(ACCOUNTS, responses, (outgoing, incoming)):
        before = _history_returns(client, account, "monthly")
        row = next(m for m in before["months"] if m["closing_date"][:7] == day.isoformat()[:7])
        assert row["contributions_kopecks"] is None and row["withdrawals_kopecks"] is None
        assert "unknown_flow" in row["flags"]
        intake = client.get(f"{BASE}/{response.json()['intake_id']}").json()
        choice = intake["money_classifications"][0]
        assert choice["classification"] == "unknown" and choice["date"] == day.isoformat()
        update = client.put(
            f"/api/source-intakes/{intake['id']}/money-classifications/{choice['source_reference']}",
            json={"classification": "internal_transfer"},
        )
        assert update.status_code == 200, update.text
        after = _history_returns(client, account, "monthly")
        assert not after["flows"]
        assert update.json()["classification"] == "internal_transfer"
        assert update.json()["origin"] == "user_choice"
        assert after["period"]["contributions_kopecks"] is None
        assert after["period"]["withdrawals_kopecks"] is None
        assert any("unknown_flow" in m["flags"] for m in after["months"])
        # A manual label alone does not establish that both accounts are in scope.
        classification = "external_withdrawal" if day == outgoing else "external_deposit"
        corrected = client.put(
            f"/api/source-intakes/{intake['id']}/money-classifications/{choice['source_reference']}",
            json={"classification": classification},
        )
        assert corrected.status_code == 200, corrected.text
        corrected = _history_returns(client, account, "monthly")
        assert len(corrected["flows"]) == 1
        assert corrected["period"]["contributions_kopecks"] == (0 if day == outgoing else 50000)
        assert corrected["period"]["withdrawals_kopecks"] == (50000 if day == outgoing else 0)
        assert all("unknown_flow" not in m["flags"] for m in corrected["months"])


def test_history_malformed_file_does_not_rollback_other_batch_saves(history_client):
    from history_import_fixtures import ACCOUNTS, history_xml

    client, _ = history_client
    valid = [history_xml(account=account) for account in ACCOUNTS[:3]]
    responses = _history_batch(
        client,
        [
            valid[0],
            ("Брокерский 4567890 (01.06.26-30.06.26).xml", b"<Report><Positions>"),
            *valid[1:],
        ],
    )
    assert [r.status_code for r in responses] == [200, 409, 200, 200], [r.text for r in responses]
    assert responses[1].json()["error"]["message"] == "xml_invalid"
    saved = client.get(BASE, params={"include_unbound": True}).json()
    assert len(saved) == 3
    for response, account in zip((responses[0], *responses[2:]), ACCOUNTS):
        readback = client.get(f"{BASE}/{response.json()['intake_id']}")
        assert readback.status_code == 200 and readback.json()["observations"]
        assert _history_returns(client, account, "instruments")["instruments"]
