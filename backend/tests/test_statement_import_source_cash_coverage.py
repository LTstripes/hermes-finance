"""Private-free H2-A2 acceptance matrix over synthetic accepted S1/H2-A1."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select, text
from test_statement_import_historical_owner_flows import (
    DAY,
    accept,
    attest,
    count,
    source,
    target,
    xml,
)
from test_statement_import_mybroker import (
    FILENAME,
    apply,
    fixture,
    preview,
)
from test_statement_import_mybroker import database as database

from hermes_finance.domain.historical_owner_flows import COMPATIBLE_FLOW_CONTRACT, OwnerFlowIntent
from hermes_finance.domain.source_cash_coverage import CLAIMS, SourceCashIntent
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    CashBoundaryCoverage,
    ExternalFlow,
    HistoricalOwnerFlowApply,
    HistoricalOwnerFlowOccurrence,
    HistoricalOwnerFlowRevision,
    InKindMovement,
    InvestmentCashFlow,
    MyBrokerImport,
    ReportingMonth,
    SourceCashCoverageApply,
    SourceCashCoverageRevision,
)
from hermes_finance.services.cash_boundary_coverage import (
    assess_cash_boundary_coverage,
    create_cash_boundary_coverage,
    update_cash_boundary_coverage,
)
from hermes_finance.services.historical_owner_flows import (
    apply_historical_owner_flow,
    preview_historical_owner_flow,
    read_historical_owner_flow,
)
from hermes_finance.services.source_cash_coverage import (
    apply_source_cash_coverage,
    preview_source_cash_coverage,
    read_source_cash_coverage,
)
from hermes_finance.statement_import.mybroker import MyBrokerError

A, B = date(2030, 1, 16), DAY


def continuous_membership(session, account_id):
    for row in session.scalars(
        select(AccountPerformanceScopeMembership).where(
            AccountPerformanceScopeMembership.account_id == account_id
        )
    ):
        session.delete(row)
    session.add(
        AccountPerformanceScopeMembership(
            account_id=account_id,
            effective_from=date(2029, 1, 1),
            effective_to=date(2031, 1, 1),
            include_in_returns=True,
        )
    )
    session.commit()


def prepared(session, *, old=False, **kwargs):
    raw = source(session, **kwargs)
    continuous_membership(session, raw.account_id)
    if not old:
        raw = raw.model_copy(update={"evidence_version": COMPATIBLE_FLOW_CONTRACT})
    intent = attest(session, raw)
    flow = accept(session, intent)["readback"]
    return intent, flow, SourceCashIntent(account_id=raw.account_id, opening_date=A, closing_date=B)


def claims(session, intent, *, zero=False):
    plan = preview_source_cash_coverage(session, intent)
    return SourceCashIntent.model_validate(
        {
            **intent.model_dump(mode="json"),
            "claims": {
                "reference": "synthetic-coverage-review",
                "review_context_digest": plan["review_context_digest"],
                **dict.fromkeys(CLAIMS, True),
                "zero_owner_cash_crossings": zero,
            },
        }
    )


def certify(session, intent, request="coverage-apply"):
    plan = preview_source_cash_coverage(session, intent)
    assert plan["can_apply"], plan["blockers"]
    result = apply_source_cash_coverage(
        session, intent, confirmation_digest=plan["confirmation_digest"], request_id=request
    )
    assert result["readback"] == read_source_cash_coverage(
        session, result["readback"]["coverage_id"]
    )
    return result


def quiet_intent(session, filename=FILENAME):
    raw = fixture(quiet=True)
    result = apply(session, raw, preview(session, raw, filename), filename)
    account_id = next(m["hermes_id"] for m in result["mappings"] if m["kind"] == "account")
    continuous_membership(session, account_id)
    return SourceCashIntent(account_id=account_id, opening_date=A, closing_date=B)


def renew(intent, view):
    return intent.model_copy(
        update={
            "operation": "reaffirm",
            "coverage_id": view["coverage_id"],
            "expected_revision": view["revision"],
            "claims": None,
        }
    )


def section_quiet_xml():
    from xml.etree import ElementTree as ET

    from test_statement_import_mybroker_endpoints import broker_month_xml
    from test_statement_import_mybroker_metadata import metadata_xml

    root = ET.fromstring(broker_month_xml())
    for parent in root.iter():
        for child in list(parent):
            if "trade_no" in child.attrib or child.tag == "{MyBroker}rn":
                parent.remove(child)
    cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
    cash.set("income_rest", "400.00")
    security = root.find(".//{MyBroker}Details[@ISIN1]")
    security.set("income_rest", security.get("real_rest"))
    return metadata_xml(ET.tostring(root, encoding="utf-8"))


def section_quiet_setup(database, *, raw=None):
    from test_statement_import_mybroker_metadata import section_setup

    raw = raw or section_quiet_xml()
    client, section, raw = section_setup(database, raw=raw)
    with database.session_factory() as session:
        continuous_membership(session, section["account_id"])
    return (
        client,
        section,
        raw,
        SourceCashIntent(
            account_id=section["account_id"],
            opening_date=date(2029, 12, 31),
            closing_date=date(2030, 1, 31),
        ),
    )


def section_coverage_assert(session, intent, state):
    view = read_source_cash_coverage(session, intent.coverage_id)
    assert view["coverage_state"] == state
    membership = list(session.scalars(select(AccountPerformanceScopeMembership)))
    shared = assess_cash_boundary_coverage(
        session,
        scope="account",
        account_id=intent.account_id,
        start_date=date(2030, 1, 1),
        end_date=intent.closing_date,
        rows_by_account={intent.account_id: membership},
        ledger_binding=COMPATIBLE_FLOW_CONTRACT,
    )
    assert shared.status == state
    return view


def section_cash_prepared(database):
    from test_statement_import_historical_owner_flows import section_cash_setup
    from test_statement_import_mybroker_metadata import _section_accept

    client, section, document, raw = section_cash_setup(database)
    with database.session_factory() as session:
        continuous_membership(session, raw.account_id)
    _section_accept(client, section, document, "proof-A")
    with database.session_factory() as session:
        flow_intent = attest(session, raw)
        flow = accept(session, flow_intent)["readback"]
    interval = SourceCashIntent(
        account_id=raw.account_id, opening_date=date(2029, 12, 31), closing_date=date(2030, 1, 31)
    )
    return client, section, document, flow_intent, flow, interval


def test_v3_real_a2_reader_shared_assessor_and_directed_reaffirmation(database):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.services.source_cash_coverage import LEGACY_CONTRACT, inventory

    client, section, document, flow_intent, flow, raw = section_cash_prepared(database)
    with database.session_factory() as session:
        legacy = inventory(
            session, raw.account_id, raw.opening_date, raw.closing_date, contract=LEGACY_CONTRACT
        )
        assert "reviewed_flow_compatibility_required" in legacy["blockers"]
        accepted = certify(session, claims(session, raw))["readback"]
        assert accepted["effective_state"] == "accepted"
        dependency = accepted["evidence"]["dependencies"]["flows"][0]
        assert dependency["contract_version"] == "h2-a1-owner-rub-v3"
        assert dependency["revision_id"] == flow["revision_id"]
        section_coverage_assert(session, renew(raw, accepted), "complete")
        assert read_historical_owner_flow(session, flow["flow_id"])["revision"] == 1
        before = _all_month_tables(database)
        for _ in range(10):
            section_coverage_assert(session, renew(raw, accepted), "complete")
            assert (
                read_historical_owner_flow(session, flow["flow_id"])["effective_state"]
                == "accepted"
            )
        assert _all_month_tables(database) == before
        revoke = SourceCashIntent(
            operation="revoke",
            coverage_id=accepted["coverage_id"],
            expected_revision=1,
            reason_code="attestation_withdrawn",
        )
        withdrawn = certify(session, revoke, "withdraw-a2")["readback"]
        assert read_historical_owner_flow(session, flow["flow_id"])["revision"] == 1
        restored = certify(session, claims(session, renew(raw, withdrawn)), "reaffirm-a2")[
            "readback"
        ]
        assert restored["effective_state"] == "accepted"
        assert read_historical_owner_flow(session, flow["flow_id"])["revision"] == 1


@pytest.mark.parametrize("closed", [True, False])
def test_v3_late_receipt_retires_a1_and_a2_transactionally_even_closed(database, closed):
    from datetime import UTC, datetime

    from test_statement_import_mybroker_metadata import _section_accept

    from hermes_finance.persistence import BrokerMonthApply
    from hermes_finance.services.accounts import create_account
    from hermes_finance.statement_import.mybroker import canonical

    # Create unrelated catalogue support before granting #800: its shared token matters.
    with database.session_factory() as session:
        other_id = create_account(session, name="Synthetic unrelated", account_type="brokerage").id
    client, section, document, flow_intent, flow, raw = section_cash_prepared(database)
    with database.session_factory() as session:
        accepted = certify(session, claims(session, raw))["readback"]
        month = session.get(ReportingMonth, section["reporting_month_id"])
        if closed:
            month.status = "closed"
            session.commit()
        assert read_historical_owner_flow(session, flow["flow_id"])["effective_state"] == "accepted"

        def receipt(request, relevant=False):
            return BrokerMonthApply(
                request_id=request,
                request_fingerprint="a" * 64,
                confirmation_digest="b" * 64,
                account_id=raw.account_id if relevant else other_id,
                reporting_month_id=section["reporting_month_id"],
                import_id=section["import_id"],
                accepted_at=datetime.now(UTC),
                projection_json=canonical(
                    {
                        "contract_version": "broker_money_dependency_v1",
                        "base_request_id": section["base_request_id"]
                        if relevant
                        else "foreign-base",
                        "reason_code": "synthetic-late",
                    }
                ),
            )

        session.add(receipt("unrelated"))
        session.commit()
        assert read_historical_owner_flow(session, flow["flow_id"])["revision"] == 1
        section_coverage_assert(session, renew(raw, accepted), "complete")

        def late_listener(current, _context, _instances):
            if current is session and not current.info.get("v3_late"):
                current.info["v3_late"] = True
                current.add(receipt("late-receipt", True))

        event.listen(type(session), "before_flush", late_listener)
        try:
            session.add(receipt("unrelated-trigger"))
            session.commit()
        finally:
            event.remove(type(session), "before_flush", late_listener)
        retired_flow = read_historical_owner_flow(session, flow["flow_id"])
        retired = section_coverage_assert(session, renew(raw, accepted), "unknown")
        assert retired_flow["acceptance_state"] == retired["acceptance_state"] == "retired"
        assert retired_flow["revision"] == retired["revision"] == 2
        if closed:
            assert month.status == "closed"
            assert (
                "closed_reporting_month_requires_reopen"
                in preview_source_cash_coverage(session, renew(raw, retired))["blockers"]
            )
            month.status = "draft"
            session.commit()
    _section_accept(
        client,
        {
            **section,
            "sections": [{**s, "expected_predecessor": "proof-A"} for s in section["sections"]],
        },
        document,
        "proof-B",
    )
    with database.session_factory() as session:
        assert read_historical_owner_flow(session, flow["flow_id"])["effective_state"] == "retired"
        assert (
            read_source_cash_coverage(session, accepted["coverage_id"])["effective_state"]
            == "retired"
        )
        assert (
            "reviewed_reaffirmation_required"
            in preview_historical_owner_flow(
                session, attest(session, target(flow_intent, retired_flow, "corroborate"))
            )["blockers"]
        )
        renewed_flow = accept(
            session, attest(session, target(flow_intent, retired_flow)), "reaffirm-v3"
        )["readback"]
        assert renewed_flow["revision"] == 3
        assert (
            read_source_cash_coverage(session, accepted["coverage_id"])["effective_state"]
            == "retired"
        )
        renewed = certify(session, claims(session, renew(raw, retired)), "reaffirm-coverage")[
            "readback"
        ]
        assert renewed["effective_state"] == "accepted"
        assert read_historical_owner_flow(session, flow["flow_id"])["revision"] == 3


def test_v3_transaction_failure_rolls_back_dependency_and_both_retirements(database):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.persistence import Account

    _, section, _, _, flow, raw = section_cash_prepared(database)
    with database.session_factory() as session:
        accepted = certify(session, claims(session, raw))["readback"]
        before = _all_month_tables(database)

        def fail(_mapper, _connection, revision):
            if revision.operation == "retire":
                raise RuntimeError("synthetic-retirement-failure")

        event.listen(SourceCashCoverageRevision, "before_insert", fail)
        try:
            session.get(Account, raw.account_id).name += " changed"
            with pytest.raises(RuntimeError, match="synthetic-retirement-failure"):
                session.commit()
            session.rollback()
        finally:
            event.remove(SourceCashCoverageRevision, "before_insert", fail)
        assert _all_month_tables(database) == before
        assert read_historical_owner_flow(session, flow["flow_id"])["effective_state"] == "accepted"
        section_coverage_assert(session, renew(raw, accepted), "complete")


def test_section_aware_quiet_real_reader_shared_assessor_and_ten_gets_no_writes(database):
    from test_statement_import_mybroker_endpoints import _all_month_tables
    from test_statement_import_mybroker_metadata import _section_accept

    client, section, raw, intent = section_quiet_setup(database)
    codes = {"4_Transfers_unsupported", "5_UFSR_unsupported"}
    with database.session_factory() as session:
        plan = preview_source_cash_coverage(session, claims(session, intent, zero=True))
        assert codes <= set(plan["blockers"])
        authority = plan["evidence"]["dependencies"]["sources"][0]["section_authority"]
        assert authority["absent_sections"] == ["4_Transfers", "5_UFSR"]
    _section_accept(client, {**section, "sections": section["sections"][:1]}, raw, "transfers")
    with database.session_factory() as session:
        assert "5_UFSR_unsupported" in preview_source_cash_coverage(session, intent)["blockers"]
        assert (
            "4_Transfers_unsupported"
            not in preview_source_cash_coverage(session, intent)["blockers"]
        )
    _section_accept(client, {**section, "sections": section["sections"][1:]}, raw, "ufsr")
    with database.session_factory() as session:
        assert (
            "owner_cash_coverage_claims_missing"
            in preview_source_cash_coverage(session, intent)["blockers"]
        )
        no_zero = preview_source_cash_coverage(session, claims(session, intent))
        assert "zero_owner_cash_crossings_unconfirmed" in no_zero["blockers"]
        accepted = certify(session, claims(session, intent, zero=True))["readback"]
        assert accepted["effective_state"] == "accepted"
        assert accepted["portfolio_scope"] == "unknown"
        assert accepted["evidence"]["contract_version"] == "h2-a2-source-cash-rub-v3"
        authority = accepted["evidence"]["dependencies"]["sources"][0]["section_authority"]
        assert codes <= set(authority["raw_blockers"])
        assert authority["effective_blockers"] == [] and authority["period_scope"] == "unknown"
        from hermes_finance.services.broker_statement_return import read_statement_return

        s3 = read_statement_return(
            session, request_id=section["base_request_id"], account_id=intent.account_id
        )
        assert s3.cash_coverage_state == "complete"
        assert s3.rate_fraction is None
        assert "material_account_exposure_unassessed" in s3.reason_codes
        target = renew(intent, accepted)
        before = _all_month_tables(database)
        for _ in range(10):
            section_coverage_assert(session, target, "complete")
        assert _all_month_tables(database) == before


@pytest.mark.parametrize("safe_first", [True, False])
def test_section_aware_safe_a_never_clears_unsafe_b_both_orders(database, safe_first):
    from xml.etree import ElementTree as ET

    from test_statement_import_mybroker_metadata import _section_accept, _section_second_source

    safe = section_quiet_xml()
    root = ET.fromstring(safe)
    root.find("{MyBroker}Trades3/{MyBroker}Report/{MyBroker}Tablix1").set("volume", "5.00")
    unsafe = ET.tostring(root, encoding="utf-8")
    client, first, _, intent = section_quiet_setup(database, raw=safe if safe_first else unsafe)
    if safe_first:
        _section_accept(client, first, safe, "initial-safe")
    second = _section_second_source(client, first, unsafe if safe_first else safe, "second-base")
    section, unsafe_section = (first, second) if safe_first else (second, first)
    if safe_first:
        section = {
            **section,
            "sections": [
                {**s, "expected_predecessor": "initial-safe"} for s in section["sections"]
            ],
        }
    _section_accept(client, section, safe, "current-safe")
    with database.session_factory() as session:
        plan = preview_source_cash_coverage(session, claims(session, intent, zero=True))
        assert "4_Transfers_unsupported" in plan["blockers"] and not plan["can_apply"]
        sources = {s["import_id"]: s for s in plan["evidence"]["dependencies"]["sources"]}
        assert len(sources) == 2
        assert sources[section["import_id"]]["section_authority"]["effective_blockers"] == []
        assert (
            "4_Transfers_unsupported"
            in sources[unsafe_section["import_id"]]["section_authority"]["effective_blockers"]
        )


@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize("change", ["account", "cash", "snapshot", "source", "mapping"])
def test_section_aware_dependency_aba_retirement_closed_replay_and_reviewed_reaffirm(
    database,
    change,
    closed,
):
    from test_statement_import_mybroker_metadata import _section_accept, section_apply

    from hermes_finance.persistence import CashBalance

    client, section, document, raw = section_quiet_setup(database)
    section_plan = _section_accept(client, section, document, "proof-A")
    with database.session_factory() as session:
        accepted_intent = claims(session, raw, zero=True)
        accepted_plan = preview_source_cash_coverage(session, accepted_intent)
        accepted = certify(session, accepted_intent)["readback"]
        envelope = session.get(SourceCashCoverageRevision, accepted["revision_id"]).evidence_json
        month = session.get(ReportingMonth, section["reporting_month_id"])
        if closed:
            month.status = "closed"
            session.commit()
            section_coverage_assert(session, renew(raw, accepted), "complete")
        row, field, replacement = {
            "account": (session.get(Account, raw.account_id), "name", "synthetic ABA"),
            "cash": (session.scalar(select(CashBalance)), "amount_kopecks", 40001),
            "snapshot": (month, "snapshot_date", date(2030, 1, 30)),
            "source": (
                session.get(MyBrokerImport, section["import_id"]),
                "confirmation_digest",
                "a" * 64,
            ),
            "mapping": (session.scalar(select(BrokerIdentityMapping)), "source_as_of", B),
        }[change]
        previous = getattr(row, field)
        setattr(row, field, replacement)
        session.commit()
        retired = section_coverage_assert(session, renew(raw, accepted), "unknown")
        assert retired["acceptance_state"] == "retired" and retired["revision"] == 2
        assert (
            session.get(SourceCashCoverageRevision, accepted["revision_id"]).evidence_json
            == envelope
        )
        setattr(row, field, previous)
        session.commit()
        section_coverage_assert(session, renew(raw, retired), "unknown")
        replay = apply_source_cash_coverage(
            session,
            accepted_intent,
            confirmation_digest=accepted_plan["confirmation_digest"],
            request_id="coverage-apply",
        )
        assert replay["replayed"] and replay["committed_revision_id"] == accepted["revision_id"]
        assert replay["readback"]["effective_state"] == "retired"
        fresh = renew(raw, retired)
        if closed:
            assert (
                "closed_reporting_month_requires_reopen"
                in preview_source_cash_coverage(session, fresh)["blockers"]
            )
            month.status = "draft"
            session.commit()
    replay = section_apply(client, section, document, section_plan, request_id="proof-A")
    assert all(s["disposition_status"] == "blocked" for s in replay.json()["sections"])
    successor = {
        **section,
        "sections": [{**s, "expected_predecessor": "proof-A"} for s in section["sections"]],
    }
    _section_accept(client, successor, document, "proof-B")
    with database.session_factory() as session:
        section_coverage_assert(session, fresh, "unknown")
        assert (
            "claim_binding_mismatch"
            in preview_source_cash_coverage(session, accepted_intent)["blockers"]
        )
        renewed = certify(session, claims(session, fresh, zero=True), "reviewed-new-context")[
            "readback"
        ]
        assert renewed["revision"] == 3
        section_coverage_assert(session, renew(raw, renewed), "complete")


@pytest.mark.parametrize(
    "problem",
    ["fork", "missing-predecessor", "invalid", "wrong-month", "wrong-account", "wrong-source"],
)
def test_section_aware_bad_receipt_scope_or_chain_real_reader_fails_closed(database, problem):
    from copy import deepcopy

    from test_statement_import_mybroker_metadata import _insert_section_history, _section_accept

    client, section, document, raw = section_quiet_setup(database)
    plan = _section_accept(client, section, document, "valid-proof")
    with database.session_factory() as session:
        accepted = certify(session, claims(session, raw, zero=True))["readback"]
    bad = deepcopy(plan["proof"])
    scoped = dict(section)
    if problem == "missing-predecessor":
        for decision in bad["intent"]["sections"]:
            decision["expected_predecessor"] = "missing"
    elif problem == "invalid":
        bad["sections"][0]["derived_movements"] = 1
    elif problem == "wrong-month":
        scoped["reporting_month_id"] = 999
    elif problem == "wrong-account":
        scoped["account_id"] = 2
    elif problem == "wrong-source":
        scoped["import_id"] = 999
    if problem in {"wrong-month", "wrong-account", "wrong-source"}:
        # A mismatched/invalid row cannot donate authority to its new grain.
        with database.session_factory() as session:
            from hermes_finance.services.broker_sections import coverage_disposition

            source_row = session.get(MyBrokerImport, section["import_id"])
            if problem == "wrong-account":
                authority = coverage_disposition(
                    session, source_row, 2, ["4_Transfers_unsupported"]
                )
                assert authority["effective_blockers"] == ["4_Transfers_unsupported"]
            else:
                # Persisting a sealed row at a different identity fails proof validation.
                bad["intent"]["reporting_month_id" if problem == "wrong-month" else "import_id"] = (
                    999
                )
                _insert_section_history(database, section, "bad-scope", bad)
                section_coverage_assert(session, renew(raw, accepted), "unknown")
        return
    _insert_section_history(database, scoped, "bad-head", bad)
    with database.session_factory() as session:
        view = section_coverage_assert(session, renew(raw, accepted), "unknown")
        assert view["acceptance_state"] == "retired"
        fresh = preview_source_cash_coverage(session, claims(session, renew(raw, view), zero=True))
        assert "4_Transfers_unsupported" in fresh["blockers"] and not fresh["can_apply"]


def test_section_aware_stale_apply_and_retirement_rollback_are_atomic(database):
    from test_statement_import_mybroker_endpoints import _all_month_tables
    from test_statement_import_mybroker_metadata import _section_accept

    from hermes_finance.persistence import CashBalance

    client, section, document, raw = section_quiet_setup(database)
    _section_accept(client, section, document)
    with database.session_factory() as session:
        reviewed = claims(session, raw, zero=True)
        stale = preview_source_cash_coverage(session, reviewed)
        cash = session.scalar(select(CashBalance))
        old = cash.amount_kopecks
        cash.amount_kopecks += 1
        session.commit()
        before = _all_month_tables(database)
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply_source_cash_coverage(
                session,
                reviewed,
                confirmation_digest=stale["confirmation_digest"],
                request_id="stale",
            )
        assert _all_month_tables(database) == before
        cash.amount_kopecks = old
        session.commit()
    successor = {
        **section,
        "sections": [{**s, "expected_predecessor": "section-proof"} for s in section["sections"]],
    }
    _section_accept(client, successor, document, "replacement")
    with database.session_factory() as session:
        accepted = certify(session, claims(session, raw, zero=True))["readback"]
        before = _all_month_tables(database)
        cash = session.scalar(select(CashBalance))
        cash.amount_kopecks += 1
        session.flush()
        session.flush()  # post-flush retirement stays in the same transaction
        assert (
            session.get(CashBoundaryCoverage, accepted["coverage_id"]).coverage_state == "unknown"
        )
        session.rollback()
        assert _all_month_tables(database) == before
        section_coverage_assert(session, renew(raw, accepted), "complete")


@pytest.mark.parametrize("version", ["h2-a2-source-cash-rub-v1", "h2-a2-source-cash-rub-v2"])
def test_section_aware_legacy_v1_real_inventory_read_replay_and_explicit_version_reaffirm(
    database,
    monkeypatch,
    version,
):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.services import source_cash_coverage as service

    # Simulate only the legacy producer's version selection. Both versions use
    # the real inventory, claims, writer and reader; no financial result is mocked.
    with database.session_factory() as session:
        raw = quiet_intent(session)
        evidence_builder = service._evidence
        with monkeypatch.context() as legacy:
            legacy.setattr(service, "CONTRACT", version)

            def legacy_evidence(*args, **kwargs):
                return evidence_builder(*args, **{**kwargs, "contract": version})

            legacy.setattr(service, "_evidence", legacy_evidence)
            old_intent = claims(session, raw, zero=True)
            old_plan = preview_source_cash_coverage(session, old_intent)
            old = certify(session, old_intent, "v1-original")["readback"]
        revision = session.get(SourceCashCoverageRevision, old["revision_id"])
        envelope, signature = revision.evidence_json, revision.material_signature
        assert old["evidence"]["contract_version"] == version
        assert (
            read_source_cash_coverage(session, old["coverage_id"])["effective_state"] == "accepted"
        )
        frozen = _all_month_tables(database)
        replay = apply_source_cash_coverage(
            session,
            old_intent,
            confirmation_digest=old_plan["confirmation_digest"],
            request_id="v1-original",
        )
        assert replay["replayed"] and replay["committed_revision_id"] == old["revision_id"]
        assert replay["readback"]["evidence"]["contract_version"] == version
        assert _all_month_tables(database) == frozen
        assert (
            "claim_binding_mismatch"
            in preview_source_cash_coverage(session, old_intent)["blockers"]
        )
        new = certify(session, claims(session, renew(raw, old), zero=True), "v2-reviewed")[
            "readback"
        ]
        assert new["coverage_id"] == old["coverage_id"] and new["revision"] == 2
        assert new["evidence"]["contract_version"] == service.CONTRACT
        assert revision.evidence_json == envelope and revision.material_signature == signature


def test_section_aware_legacy_raw_blockers_never_inherit_grant(database):
    from test_statement_import_mybroker_metadata import _section_accept

    from hermes_finance.services.source_cash_coverage import LEGACY_CONTRACT, _evidence

    client, section, document, intent = section_quiet_setup(database)
    _section_accept(client, section, document)
    with database.session_factory() as session:
        legacy = _evidence(
            session,
            intent,
            intent.account_id,
            intent.opening_date,
            intent.closing_date,
            contract=LEGACY_CONTRACT,
        )
        assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(
            legacy["dependencies"]["blockers"]
        )
        assert "section_authority" not in legacy["dependencies"]["sources"][0]
        assert preview_source_cash_coverage(session, claims(session, intent, zero=True))[
            "can_apply"
        ]


def test_section_aware_late_listener_receipt_retires_in_same_transaction_and_unrelated_does_not(
    database,
):
    from datetime import UTC, datetime

    from test_statement_import_mybroker_metadata import _section_accept

    from hermes_finance.persistence import BrokerMonthApply
    from hermes_finance.services.accounts import create_account
    from hermes_finance.statement_import.mybroker import canonical

    client, section, document, intent = section_quiet_setup(database)
    with database.session_factory() as session:
        unrelated_account = create_account(
            session, name="Unrelated synthetic", account_type="brokerage"
        ).id
    _section_accept(client, section, document)
    with database.session_factory() as session:
        accepted = certify(session, claims(session, intent, zero=True))["readback"]

        def dependency(request_id, account_id):
            return BrokerMonthApply(
                request_id=request_id,
                request_fingerprint="a" * 64,
                confirmation_digest="b" * 64,
                account_id=account_id,
                import_id=section["import_id"],
                reporting_month_id=section["reporting_month_id"],
                projection_json=canonical(
                    {
                        "contract_version": "broker_money_dependency_v1",
                        "base_request_id": section["base_request_id"],
                        "reason_code": "late-dependency",
                    }
                ),
                accepted_at=datetime.now(UTC),
            )

        # Another account's unrelated receipt has no authority at this source grain.
        unrelated = dependency("unrelated", unrelated_account)
        unrelated.projection_json = canonical(
            {
                "contract_version": "broker_money_dependency_v1",
                "base_request_id": "other-base",
                "reason_code": "unrelated",
            }
        )
        session.add(unrelated)
        session.commit()
        section_coverage_assert(session, renew(intent, accepted), "complete")

        def late_listener(current, _context, _instances):
            if current is session and any(isinstance(r, BrokerMonthApply) for r in current.new):
                if not current.info.get("late_test_receipt"):
                    current.info["late_test_receipt"] = True
                    current.add(dependency("late-receipt", intent.account_id))

        event.listen(type(session), "before_flush", late_listener)
        try:
            session.add(dependency("unrelated-trigger", unrelated_account))
            session.commit()
        finally:
            event.remove(type(session), "before_flush", late_listener)
        retired = section_coverage_assert(session, renew(intent, accepted), "unknown")
        assert retired["acceptance_state"] == "retired" and retired["revision"] == 2


def test_section_aware_extra_quiet_report_retirement_keeps_overlapping_source_inventory(database):
    from test_statement_import_mybroker_metadata import _section_accept

    client, section, document, raw = section_quiet_setup(database)
    _section_accept(client, section, document, "proof-A")
    with database.session_factory() as session:
        accepted = certify(session, claims(session, raw, zero=True))["readback"]
        quiet = fixture(quiet=True)
        apply(session, quiet, preview(session, quiet))
        retired = section_coverage_assert(session, renew(raw, accepted), "unknown")
        assert retired["acceptance_state"] == "retired"
        assert (
            len(preview_source_cash_coverage(session, raw)["evidence"]["dependencies"]["sources"])
            == 2
        )
    successor = {
        **section,
        "sections": [{**s, "expected_predecessor": "proof-A"} for s in section["sections"]],
    }
    _section_accept(client, successor, document, "proof-B")
    with database.session_factory() as session:
        updated = certify(
            session, claims(session, renew(raw, retired), zero=True), "overlap-reviewed"
        )["readback"]
        deps = updated["evidence"]["dependencies"]
        assert len(deps["sources"]) == 2
        assert deps["source_range_union"] == [["2030-01-01", "2030-01-31"]]
        section_coverage_assert(session, renew(raw, updated), "complete")


@pytest.mark.parametrize("problem", ["pending", "repo", "coupon", "nkd", "custody"])
def test_section_aware_grants_do_not_waive_money_or_material_exposure(database, problem):
    from xml.etree import ElementTree as ET

    from test_statement_import_mybroker_endpoints import broker_month_xml
    from test_statement_import_mybroker_metadata import _section_accept, metadata_xml, section_setup

    raw = broker_month_xml()
    root = ET.fromstring(raw)
    if problem in {"pending", "repo"}:
        trade = root.find(".//{MyBroker}Details[@trade_no]")
        trade.set(
            "save_settlement_date" if problem == "pending" else "repo_no",
            "18.01.2030" if problem == "pending" else "123",
        )
    elif problem in {"coupon", "nkd"}:
        root.find(".//{MyBroker}comment").set(
            "comment", "Купон" if problem == "coupon" else "НКД по сделке"
        )
    else:
        root.find("{MyBroker}Trades3/{MyBroker}Report").set("custody", "unresolved")
    raw = metadata_xml(ET.tostring(root, encoding="utf-8"))
    if problem == "repo":
        from test_statement_import_mybroker_endpoints import (
            _broker_month_apply,
            _broker_month_preview,
            _broker_month_setup,
        )

        client = TestClient(create_app(database=database))
        scope = _broker_month_setup(database)
        plan = _broker_month_preview(client, scope, raw)
        assert _broker_month_apply(client, scope, plan, raw).status_code == 409
        # REPO already prevents the base authority required for a section grant.
        with database.session_factory() as session:
            imported = apply(session, raw, preview(session, raw))
            account_id = imported["mappings"][0]["hermes_id"]
            continuous_membership(session, account_id)
            intent = SourceCashIntent(account_id=account_id, opening_date=A, closing_date=B)
            coverage = preview_source_cash_coverage(session, claims(session, intent, zero=True))
            assert "money_disposition_unresolved" in coverage["blockers"]
            assert not coverage["can_apply"]
        return
    client, section, document = section_setup(database, raw=raw)
    if problem != "custody":
        _section_accept(client, section, document)
    with database.session_factory() as session:
        continuous_membership(session, section["account_id"])
        intent = SourceCashIntent(account_id=section["account_id"], opening_date=A, closing_date=B)
        plan = preview_source_cash_coverage(session, claims(session, intent, zero=True))
        assert not plan["can_apply"]
        assert (
            "4_Transfers_unsupported" if problem == "custody" else "money_disposition_unresolved"
        ) in plan["blockers"]
        assert count(session, SourceCashCoverageRevision) == 0


def test_section_aware_no_month_get_never_creates_scope_and_legacy_warnings_stay(database):
    from test_statement_import_mybroker_metadata import metadata_xml

    with database.session_factory() as session:
        document = metadata_xml(fixture(quiet=True))
        imported = apply(session, document, preview(session, document))
        account_id = imported["mappings"][0]["hermes_id"]
        continuous_membership(session, account_id)
        intent = SourceCashIntent(account_id=account_id, opening_date=A, closing_date=B)
        for _ in range(10):
            plan = preview_source_cash_coverage(session, claims(session, intent, zero=True))
            assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(plan["blockers"])
            authority = plan["evidence"]["dependencies"]["sources"][0]["section_authority"]
            assert authority["scopes"] == []
            assert count(session, ReportingMonth) == 0


@pytest.mark.parametrize("version", [COMPATIBLE_FLOW_CONTRACT, "h2-a1-owner-rub-v3"])
def test_section_aware_signed_pair_stays_two_dated_crossings_and_a1_frozen_gate(database, version):
    from test_statement_import_mybroker_metadata import metadata_xml

    with database.session_factory() as session:
        raw = source(session, amount="100.00", extra_amounts=("-100.00",))
        continuous_membership(session, raw.account_id)
        flows = []
        for ordinal in (0, 1):
            intent = raw.model_copy(
                update={
                    "evidence_version": version,
                    "seed": raw.seed.model_copy(update={"ordinal": ordinal}),
                }
            )
            flows.append(
                accept(session, attest(session, intent), "signed-" + str(ordinal))["readback"]
            )
        intent = SourceCashIntent(account_id=raw.account_id, opening_date=A, closing_date=B)
        accepted = certify(session, claims(session, intent))["readback"]
        assert len(accepted["evidence"]["dependencies"]["effective_flow_ids"]) == 2
        assert [f["core"]["signed_source_amount"] for f in flows] == ["100", "-100"]
        assert (
            "zero_owner_cash_crossings_conflicts"
            in preview_source_cash_coverage(session, claims(session, intent, zero=True))["blockers"]
        )
        # Safe metadata syntax on a newly accepted source does not alter A1.
        document = metadata_xml(xml(amount="100.00"))
        imported = apply(session, document, preview(session, document))
        blocked_a1 = OwnerFlowIntent(
            account_id=raw.account_id,
            evidence_version=COMPATIBLE_FLOW_CONTRACT,
            seed={"import_id": imported["import_id"], "ordinal": 0},
        )
        assert (
            "4_Transfers_unsupported"
            in preview_historical_owner_flow(session, blocked_a1)["blockers"]
        )


def test_positive_one_day_directed_dependency_and_legacy_reader_refusal(database):
    with database.session_factory() as session:
        flow_intent, flow, raw = prepared(session)
        intent = claims(session, raw)
        first = certify(session, intent)["readback"]
        assert first["coverage_state"] == "complete"
        row = session.get(CashBoundaryCoverage, first["coverage_id"])
        assert (row.covered_from, row.covered_to) == (B, B)
        assert read_historical_owner_flow(session, flow["flow_id"]) == flow
        assert count(session, ReportingMonth) == count(session, InvestmentCashFlow) == 0
        membership = list(session.scalars(select(AccountPerformanceScopeMembership)))
        for binding, expected in [
            (COMPATIBLE_FLOW_CONTRACT, "complete"),
            ("external_flow", "unknown"),
        ]:
            view = assess_cash_boundary_coverage(
                session,
                scope="account",
                account_id=raw.account_id,
                start_date=B,
                end_date=B,
                rows_by_account={raw.account_id: membership},
                ledger_binding=binding,
            )
            assert view.status == expected
        revoke = SourceCashIntent(
            operation="revoke",
            coverage_id=first["coverage_id"],
            expected_revision=1,
            reason_code="attestation_withdrawn",
        )
        assert certify(session, revoke, "revoke")["readback"]["coverage_state"] == "unknown"
        assert read_historical_owner_flow(session, flow["flow_id"]) == flow
        reaffirm = claims(
            session, renew(raw, read_source_cash_coverage(session, first["coverage_id"]))
        )
        assert certify(session, reaffirm, "renew")["readback"]["revision"] == 3
        assert read_historical_owner_flow(session, flow["flow_id"]) == flow
        assert flow_intent.evidence_version == COMPATIBLE_FLOW_CONTRACT


def test_v1_requires_explicit_same_core_version_reaffirmation_and_preserves_receipt(database):
    with database.session_factory() as session:
        old_intent, flow, raw = prepared(session, old=True)
        old_plan = preview_historical_owner_flow(session, old_intent)
        assert (
            "reviewed_flow_compatibility_required"
            in preview_source_cash_coverage(session, claims(session, raw))["blockers"]
        )
        revision = session.get(HistoricalOwnerFlowRevision, flow["revision_id"])
        envelope, signature = revision.evidence_json, revision.material_signature
        upgraded = target(old_intent, flow).model_copy(
            update={"evidence_version": COMPATIBLE_FLOW_CONTRACT}
        )
        corroborate = attest(session, upgraded.model_copy(update={"operation": "corroborate"}))
        assert (
            "reviewed_version_reaffirmation_required"
            in preview_historical_owner_flow(session, corroborate)["blockers"]
        )
        accepted = accept(session, attest(session, upgraded), "version-reaffirm")["readback"]
        assert accepted["revision"] == 2 and accepted["core"] == flow["core"]
        assert revision.evidence_json == envelope and revision.material_signature == signature
        assert certify(session, claims(session, raw))["readback"]["coverage_state"] == "complete"
        # Replay uses the original v1 digest without an added default version key.
        receipt = session.scalar(
            select(HistoricalOwnerFlowApply).where(
                HistoricalOwnerFlowApply.request_id == "synthetic-apply"
            )
        )
        replay = apply_historical_owner_flow(
            session,
            old_intent,
            confirmation_digest=receipt.confirmation_digest,
            request_id="synthetic-apply",
        )
        assert replay["committed_revision_id"] == flow["revision_id"]
        assert replay["readback"]["revision"] == 2
        assert old_plan["flow_id"] is None


def test_eod_window_excludes_opening_and_after_closing_preserves_multiplicity(database):
    from xml.etree import ElementTree as ET

    with database.session_factory() as session:
        root = ET.fromstring(xml(extra_amounts=("23.45", "34.56", "45.67")))
        collection = root.find(".//{MyBroker}rn_Collection")
        for node, day in zip(
            list(collection), ("2030-01-16", "2030-01-17", "2030-01-18", "2030-01-19"), strict=True
        ):
            # Each date has its own accepted posted-cash group.
            group = root.find(".//{MyBroker}settlement_date")
            if day == "2030-01-16":
                group.set("settlement_date", day + "T00:00:00")
            else:
                other = ET.SubElement(
                    root.find(".//{MyBroker}settlement_date_Collection"),
                    "{MyBroker}settlement_date",
                    {"settlement_date": day + "T00:00:00"},
                )
                ET.SubElement(other, "{MyBroker}rn_Collection").append(node)
                collection.remove(node)
        raw = ET.tostring(root, encoding="utf-8")
        result = apply(session, raw, preview(session, raw))
        account_id = result["mappings"][0]["hermes_id"]
        continuous_membership(session, account_id)
        ids = []
        for ordinal in range(4):
            intent = OwnerFlowIntent(
                account_id=account_id,
                evidence_version=COMPATIBLE_FLOW_CONTRACT,
                seed={"import_id": result["import_id"], "ordinal": ordinal},
            )
            ids.append(
                accept(session, attest(session, intent), "flow-" + str(ordinal))["readback"][
                    "flow_id"
                ]
            )
        interval = SourceCashIntent(
            account_id=account_id, opening_date=A, closing_date=date(2030, 1, 18)
        )
        first = certify(session, claims(session, interval))["readback"]
        deps = first["evidence"]["dependencies"]
        assert deps["effective_flow_ids"] == sorted(ids[1:3])
        assert [r["row"]["date"] for r in deps["money_dispositions"]] == [
            "2030-01-17",
            "2030-01-18",
        ]
        assert len(deps["flows"]) == 2


def test_distinct_same_day_and_corroboration_bind_each_flow_once_every_occurrence(database):
    with database.session_factory() as session:
        raw = source(session, extra_amounts=("-7.89",))
        continuous_membership(session, raw.account_id)
        source(session, stamp="11", extra_amounts=("-7.89",))
        for ordinal in (0, 1):
            intent = raw.model_copy(
                update={
                    "evidence_version": COMPATIBLE_FLOW_CONTRACT,
                    "seed": raw.seed.model_copy(update={"ordinal": ordinal}),
                }
            )
            accept(session, attest(session, intent), "flow-" + str(ordinal))
        intent = SourceCashIntent(account_id=raw.account_id, opening_date=A, closing_date=B)
        deps = certify(session, claims(session, intent))["readback"]["evidence"]["dependencies"]
        assert len(deps["flows"]) == 2 and len(deps["money_dispositions"]) == 4
        assert count(session, HistoricalOwnerFlowOccurrence) == 4
        assert all(r["disposition"] == "effective_owner_flow" for r in deps["money_dispositions"])


@pytest.mark.parametrize("missing", [*CLAIMS, "zero_owner_cash_crossings"])
def test_quiet_zero_requires_each_affirmative_claim(database, missing):
    with database.session_factory() as session:
        raw = quiet_intent(session)
        valid = claims(session, raw, zero=True)
        bad = valid.model_copy(update={"claims": valid.claims.model_copy(update={missing: False})})
        plan = preview_source_cash_coverage(session, bad)
        assert missing + "_unconfirmed" in plan["blockers"]
        with pytest.raises(MyBrokerError):
            apply_source_cash_coverage(
                session, bad, confirmation_digest=plan["confirmation_digest"], request_id="blocked"
            )
        assert (
            count(session, SourceCashCoverageRevision)
            == count(session, SourceCashCoverageApply)
            == 0
        )
        assert certify(session, valid)["readback"]["coverage_state"] == "complete"


@pytest.mark.parametrize(
    "ranges,expected",
    [
        (((1, 5), (5, 10), (11, 31)), []),
        (((1, 5), (7, 31)), [["2030-01-06", "2030-01-06"]]),
    ],
)
def test_full_ranges_clipped_union_exact_gap_not_hull(database, ranges, expected):
    from xml.etree import ElementTree as ET

    with database.session_factory() as session:
        for index, (start, end) in enumerate(ranges):
            root = ET.fromstring(fixture(quiet=True))
            root.set("synthetic_stamp", str(index))
            raw = ET.tostring(root, encoding="utf-8")
            filename = FILENAME.replace("01.01.30-31.01.30", f"{start:02}.01.30-{end:02}.01.30")
            result = apply(session, raw, preview(session, raw, filename), filename)
        account_id = result["mappings"][0]["hermes_id"]
        continuous_membership(session, account_id)
        intent = SourceCashIntent(
            account_id=account_id, opening_date=date(2029, 12, 31), closing_date=date(2030, 1, 31)
        )
        plan = preview_source_cash_coverage(session, claims(session, intent, zero=True))
        assert plan["evidence"]["dependencies"]["source_gaps"] == expected
        assert plan["can_apply"] == (not expected)
        assert len(plan["evidence"]["dependencies"]["sources"]) == len(ranges)


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"extra_amounts": ("7.89",)}, "money_disposition_unresolved"),
        ({"opaque": True}, "4_Transfers_unsupported"),
        ({"currency": "USD"}, "source_currency_unsupported"),
        ({"duplicate": True}, "money_disposition_unresolved"),
        ({"linked": True, "pending": True}, "money_disposition_unresolved"),
    ],
)
def test_unresolved_money_opaque_currency_multiplicity_or_link_cannot_be_dismissed(
    database, kwargs, reason
):
    with database.session_factory() as session:
        raw = source(session, **kwargs)
        continuous_membership(session, raw.account_id)
        intent = SourceCashIntent(account_id=raw.account_id, opening_date=A, closing_date=B)
        plan = preview_source_cash_coverage(session, claims(session, intent, zero=True))
        assert reason in plan["blockers"], plan["blockers"]
        assert not plan["can_apply"]


def test_exact_existing_trade_link_excludes_non_owner_cash_binds_trade_lifecycle(database):
    with database.session_factory() as session:
        raw = fixture()
        result = apply(session, raw, preview(session, raw))
        account_id = result["mappings"][0]["hermes_id"]
        continuous_membership(session, account_id)
        intent = SourceCashIntent(account_id=account_id, opening_date=A, closing_date=B)
        first = certify(session, claims(session, intent, zero=True))["readback"]
        row = first["evidence"]["dependencies"]["money_dispositions"][0]
        assert row["disposition"] == "accepted_non_owner_trade_cash"
        assert row["linked_trade"]["cash_available"]


def trade_cash_with_commission_limitation(*, missing=False, commission_row=False):
    from copy import deepcopy
    from xml.etree import ElementTree as ET

    root = ET.fromstring(fixture())
    trade = root.find(".//{MyBroker}Details[@trade_no]")
    if missing:
        del trade.attrib["bank_tax"]
    else:
        trade.set("bank_tax", "1.23")
    if commission_row:
        row = deepcopy(root.find(".//{MyBroker}rn"))
        row.find(".//{MyBroker}comment").set("comment", "Комиссия по сделке 10000000001")
        row.find(".//{MyBroker}p_code[@volume]").set("volume", "-1.23")
        root.find(".//{MyBroker}rn_Collection").append(row)
    return ET.tostring(root, encoding="utf-8")


@pytest.mark.parametrize(
    "missing,commission_row,limitation,kinds",
    [
        (True, False, "commission_missing", ["settlement"]),
        (False, False, "commission_basis_unresolved", ["settlement"]),
        (False, True, "commission_basis_unresolved", ["settlement", "commission"]),
    ],
)
def test_exact_settled_trade_cash_preserves_commission_limitations_without_owner_crossing(
    database, missing, commission_row, limitation, kinds
):
    with database.session_factory() as session:
        document = trade_cash_with_commission_limitation(
            missing=missing, commission_row=commission_row
        )
        reviewed = preview(session, document)
        assert limitation in reviewed["blockers"] and reviewed["can_apply"]
        result = apply(session, document, reviewed)
        account_id = result["mappings"][0]["hermes_id"]
        continuous_membership(session, account_id)
        raw = SourceCashIntent(account_id=account_id, opening_date=A, closing_date=B)
        intent = claims(session, raw, zero=True)
        plan = preview_source_cash_coverage(session, intent)
        assert plan["can_apply"], plan["blockers"]
        rows = plan["evidence"]["dependencies"]["money_dispositions"]
        assert [row["row"]["kind"] for row in rows] == kinds
        for row in rows:
            assert row["disposition"] == "accepted_non_owner_trade_cash"
            assert row["owners"] == []
            assert not row["linked_trade"]["cash_available"]
            assert row["linked_trade"]["blockers"] == [limitation]
        first = certify(session, intent)["readback"]
        assert first["coverage_state"] == "complete"
        assert first["evidence"]["dependencies"]["money_dispositions"] == rows
        assert first["evidence"]["dependencies"]["effective_flow_ids"] == []
        assert count(session, HistoricalOwnerFlowOccurrence) == 0


@pytest.mark.parametrize(
    "problem",
    [
        "incomplete",
        "missing",
        "pending",
        "ambiguous",
        "settlement_missing",
        "direction",
        "date",
        "currency",
        "repo",
    ],
)
def test_commission_limitation_does_not_dismiss_material_trade_linkage_blockers(database, problem):
    from copy import deepcopy
    from xml.etree import ElementTree as ET

    with database.session_factory() as session:
        root = ET.fromstring(trade_cash_with_commission_limitation(commission_row=True))
        trade = root.find(".//{MyBroker}Details[@trade_no]")
        if problem == "incomplete":
            trade.set("trade_no", "10000000001")
        elif problem in ("missing", "pending"):
            report = root.find("{MyBroker}Trades/{MyBroker}Report")
            for child in list(report):
                report.remove(child)
            if problem == "pending":
                pending = ET.fromstring(fixture(pending=True))
                report.append(pending.find(".//{MyBroker}Tablix3"))
                report.find(".//{MyBroker}Details2").set("bank_tax2", "1.23")
        elif problem == "ambiguous":
            root.find(".//{MyBroker}rn_Collection").append(deepcopy(root.find(".//{MyBroker}rn")))
        elif problem == "settlement_missing":
            root.find(".//{MyBroker}rn_Collection").remove(root.find(".//{MyBroker}rn"))
        elif problem == "direction":
            root.find(".//{MyBroker}p_code[@volume]").set("volume", "1000.00")
        elif problem == "date":
            trade.set("save_settlement_date", "18.01.2030")
        elif problem == "currency":
            trade.set("curr_calc", "USD")
        else:
            trade.set("repo_no", "123")
        document = ET.tostring(root, encoding="utf-8")
        result = apply(session, document, preview(session, document))
        account_id = result["mappings"][0]["hermes_id"]
        continuous_membership(session, account_id)
        raw = SourceCashIntent(account_id=account_id, opening_date=A, closing_date=B)
        plan = preview_source_cash_coverage(session, claims(session, raw, zero=True))
        assert not plan["can_apply"]
        assert "money_disposition_unresolved" in plan["blockers"]
        rows = plan["evidence"]["dependencies"]["money_dispositions"]
        assert all(row["disposition"] == "unresolved" for row in rows)
        assert count(session, SourceCashCoverageRevision) == 0


@pytest.mark.parametrize("conflict", ["primary_identity_ambiguous", "immutable_trade_conflict"])
def test_commission_limited_cash_fails_closed_on_conflicting_accepted_trade_support(
    database, conflict
):
    import json
    from copy import deepcopy

    from hermes_finance.statement_import.mybroker import PROVIDER, canonical, digest

    with database.session_factory() as session:
        document = trade_cash_with_commission_limitation(commission_row=True)
        result = apply(session, document, preview(session, document))
        account_id = result["mappings"][0]["hermes_id"]
        continuous_membership(session, account_id)
        source_row = session.get(MyBrokerImport, result["import_id"])
        accepted = json.loads(source_row.normalized_json)
        conflicting = deepcopy(accepted["trades"][0])
        if conflict == "primary_identity_ambiguous":
            conflicting["ids"][1] = "2000000002"
            conflicting["identity"] = digest(
                [PROVIDER, conflicting["core"]["source_account"], conflicting["ids"]]
            )
        else:
            conflicting["core"]["price"] = "101.00"
        accepted["trades"].append(conflicting)
        # Simulate contradictory persisted support; Preview cannot trust old linkage.
        source_row.normalized_json = canonical(accepted)
        session.commit()
        raw = SourceCashIntent(account_id=account_id, opening_date=A, closing_date=B)
        plan = preview_source_cash_coverage(session, claims(session, raw, zero=True))
        assert not plan["can_apply"]
        assert "money_disposition_unresolved" in plan["blockers"]
        rows = plan["evidence"]["dependencies"]["money_dispositions"]
        assert all(row["disposition"] == "unresolved" for row in rows)
        if conflict == "immutable_trade_conflict":
            assert "immutable_trade_conflict" in rows[0]["linked_trade"]["blockers"]


@pytest.mark.parametrize(
    "change",
    [
        "quiet_source",
        "mapping",
        "membership",
        "flow_revoke",
        "flow_reaffirm",
        "legacy",
        "competing",
        "in_kind",
    ],
)
def test_dependency_loss_retires_transactionally_no_a_b_a_or_receipt_revival(database, change):
    with database.session_factory() as session:
        flow_intent, flow, raw = prepared(session)
        intent = claims(session, raw)
        plan = preview_source_cash_coverage(session, intent)
        first = certify(session, intent)["readback"]
        changed = None
        if change == "quiet_source":
            document = fixture(quiet=True)
            apply(session, document, preview(session, document))
        elif change == "mapping":
            changed = session.scalar(
                select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
            )
            changed.source_as_of = date(2030, 1, 1)
            session.commit()
            changed.source_as_of = None
            session.commit()
        elif change == "membership":
            changed = session.scalar(select(AccountPerformanceScopeMembership))
            changed.include_in_returns = False
            session.commit()
            changed.include_in_returns = True
            session.commit()
        elif change in ("flow_revoke", "flow_reaffirm"):
            if change == "flow_revoke":
                operation = OwnerFlowIntent(
                    operation="revoke",
                    flow_id=flow["flow_id"],
                    expected_revision=1,
                    reason_code="attestation_withdrawn",
                )
            else:
                operation = target(flow_intent, flow)
                operation = attest(session, operation).model_copy(
                    update={
                        "claims": attest(session, operation).claims.model_copy(
                            update={"reference": "another-review"}
                        )
                    }
                )
            accept(session, operation, "changed-flow")
        elif change == "competing":
            changed = CashBoundaryCoverage(
                account_id=raw.account_id,
                covered_from=date(2030, 1, 15),
                covered_to=B,
                coverage_state="unknown",
                provenance_kind="owner_attestation",
            )
            session.add(changed)
            session.commit()
            session.delete(changed)
            session.commit()
        else:
            month = ReportingMonth(
                year=2030,
                month=1,
                period_start=date(2030, 1, 1),
                period_end=date(2030, 1, 31),
                snapshot_date=date(2030, 1, 31),
            )
            session.add(month)
            session.commit()
            if change == "legacy":
                changed = ExternalFlow(
                    reporting_month_id=month.id,
                    account_id=raw.account_id,
                    event_date=B,
                    boundary_amount_kopecks=1,
                    direction="contribution",
                    kind="external_contribution",
                    source="manual",
                )
            else:
                changed = InKindMovement(
                    reporting_month_id=month.id,
                    event_date=B,
                    destination_account_id=raw.account_id,
                    movement_kind="external_in",
                    provenance_kind="owner_attestation",
                )
            session.add(changed)
            session.commit()
            session.delete(changed)
            session.commit()
        retired = read_source_cash_coverage(session, first["coverage_id"])
        assert retired["acceptance_state"] == "retired" and retired["coverage_state"] == "unknown"
        assert retired["revision"] == 2
        assert session.get(CashBoundaryCoverage, first["coverage_id"]).coverage_state == "unknown"
        replay = apply_source_cash_coverage(
            session,
            intent,
            confirmation_digest=plan["confirmation_digest"],
            request_id="coverage-apply",
        )
        assert (
            replay["committed_revision_id"] == first["revision_id"]
            and replay["readback"] == retired
        )
        assert count(session, SourceCashCoverageRevision) == 2


def test_retired_unresolved_flow_is_not_zero_and_apply_never_revives_it(database):
    with database.session_factory() as session:
        flow_intent, flow, raw = prepared(session)
        first = certify(session, claims(session, raw))["readback"]
        revoke = OwnerFlowIntent(
            operation="revoke",
            flow_id=flow["flow_id"],
            expected_revision=1,
            reason_code="attestation_withdrawn",
        )
        accept(session, revoke, "flow-revoke")
        retired = read_source_cash_coverage(session, first["coverage_id"])
        bad = preview_source_cash_coverage(session, claims(session, renew(raw, retired), zero=True))
        assert "historical_flow_not_effective" in bad["blockers"]
        assert "money_disposition_unresolved" in bad["blockers"]
        assert read_historical_owner_flow(session, flow["flow_id"])["effective_state"] == "revoked"
        assert count(session, HistoricalOwnerFlowRevision) == 2


def test_direct_sql_mismatch_read_and_list_assessor_fail_closed_without_repair(database):
    with database.session_factory() as session:
        _, _, raw = prepared(session)
        first = certify(session, claims(session, raw))["readback"]
        session.execute(
            text(
                "UPDATE broker_identity_mappings SET source_as_of = '2030-01-01' WHERE subject_kind = 'account'"
            )
        )
        session.commit()
        assert (
            read_source_cash_coverage(session, first["coverage_id"])["effective_state"]
            == "invalidated"
        )
        assert count(session, SourceCashCoverageRevision) == 1
        membership = list(session.scalars(select(AccountPerformanceScopeMembership)))
        assert (
            assess_cash_boundary_coverage(
                session,
                scope="account",
                account_id=raw.account_id,
                start_date=B,
                end_date=B,
                rows_by_account={raw.account_id: membership},
                ledger_binding=COMPATIBLE_FLOW_CONTRACT,
            ).status
            == "unknown"
        )
    client = TestClient(create_app(database=database))
    view = client.get(f"/api/cash-boundary-coverages/{first['coverage_id']}").json()
    assert view["coverage_state"] == view["source_acceptance"]["coverage_state"] == "unknown"
    assert client.get("/api/cash-boundary-coverages").json()[0]["coverage_state"] == "unknown"


def test_stale_preview_closed_guard_and_dependency_retirement_across_closed_interval(database):
    with database.session_factory() as session:
        _, _, raw = prepared(session)
        intent = claims(session, raw)
        plan = preview_source_cash_coverage(session, intent)
        month = ReportingMonth(
            year=2030,
            month=1,
            period_start=date(2030, 1, 1),
            period_end=date(2030, 1, 31),
            snapshot_date=date(2030, 1, 31),
            status="closed",
        )
        session.add(month)
        session.commit()
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply_source_cash_coverage(
                session,
                intent,
                confirmation_digest=plan["confirmation_digest"],
                request_id="closed",
            )
        assert (
            "closed_reporting_month_requires_reopen"
            in preview_source_cash_coverage(session, intent)["blockers"]
        )
        month.status = "draft"
        session.commit()
        first = certify(session, claims(session, raw))["readback"]
        month.status = "closed"
        session.commit()
        assert (
            read_source_cash_coverage(session, first["coverage_id"])["coverage_state"] == "complete"
        )
        revoke = SourceCashIntent(
            operation="revoke",
            coverage_id=first["coverage_id"],
            expected_revision=1,
            reason_code="evidence_disputed",
        )
        assert (
            "closed_reporting_month_requires_reopen"
            in preview_source_cash_coverage(session, revoke)["blockers"]
        )
        row = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
        )
        row.source_as_of = B
        session.commit()
        assert (
            read_source_cash_coverage(session, first["coverage_id"])["acceptance_state"]
            == "retired"
        )
        assert month.status == "closed"


def test_same_identity_legacy_reaffirm_preserves_id_and_forbids_legacy_forgery_edits(database):
    with database.session_factory() as session:
        raw = quiet_intent(session)
        legacy = create_cash_boundary_coverage(
            session,
            account_id=raw.account_id,
            covered_from=B,
            covered_to=B,
            coverage_state="unknown",
        )
        raw = raw.model_copy(
            update={"operation": "reaffirm", "coverage_id": legacy.id, "expected_revision": 0}
        )
        first = certify(session, claims(session, raw, zero=True))["readback"]
        assert first["coverage_id"] == legacy.id
        assert first["history"][0]["previous_projection"]["provenance_kind"] == "owner_attestation"
        with pytest.raises(ValueError, match="Preview/Apply"):
            update_cash_boundary_coverage(session, legacy.id, coverage_state="complete")
        session.rollback()
        with pytest.raises(ValueError, match="Preview/Apply"):
            create_cash_boundary_coverage(
                session,
                account_id=raw.account_id,
                covered_from=A,
                covered_to=A,
                provenance_kind="owner_attested_source_cash_history",
            )
        session.rollback()
        forged = CashBoundaryCoverage(
            account_id=raw.account_id,
            covered_from=date(2030, 2, 1),
            covered_to=date(2030, 2, 1),
            coverage_state="complete",
            provenance_kind="owner_attested_source_cash_history",
        )
        session.add(forged)
        session.commit()
        assert read_source_cash_coverage(session, forged.id)["coverage_state"] == "unknown"


def test_stale_request_conflict_noop_and_concurrent_writer_atomicity(database):
    with database.session_factory() as session:
        raw = quiet_intent(session)
        intent = claims(session, raw, zero=True)
        plan = preview_source_cash_coverage(session, intent)
    barrier = Barrier(2)

    def worker(request_id):
        with database.session_factory() as session:
            barrier.wait(timeout=5)
            try:
                return apply_source_cash_coverage(
                    session,
                    intent,
                    confirmation_digest=plan["confirmation_digest"],
                    request_id=request_id,
                )
            except MyBrokerError as error:
                return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, ("writer-a", "writer-b")))
    assert sum(isinstance(r, dict) for r in results) == 1 and "preview_stale" in results
    with database.session_factory() as session:
        assert (
            count(session, CashBoundaryCoverage)
            == count(session, SourceCashCoverageRevision)
            == count(session, SourceCashCoverageApply)
            == 1
        )
        result = certify(session, intent, "fresh-identical")
        assert result["result_action"] == "noop" and count(session, SourceCashCoverageRevision) == 1
        changed = intent.model_copy(
            update={"claims": intent.claims.model_copy(update={"reference": "another-review"})}
        )
        with pytest.raises(MyBrokerError, match="idempotency_conflict"):
            apply_source_cash_coverage(
                session,
                changed,
                confirmation_digest=plan["confirmation_digest"],
                request_id="fresh-identical",
            )


def test_receipt_failure_rolls_back_projection_revision_and_receipt(database):
    with database.session_factory() as session:
        raw = quiet_intent(session)
        intent = claims(session, raw, zero=True)
        plan = preview_source_cash_coverage(session, intent)

        def fail(_mapper, _connection, _target):
            raise RuntimeError("synthetic-write-failure")

        event.listen(SourceCashCoverageApply, "before_insert", fail)
        try:
            with pytest.raises(RuntimeError, match="synthetic-write-failure"):
                apply_source_cash_coverage(
                    session,
                    intent,
                    confirmation_digest=plan["confirmation_digest"],
                    request_id="failed",
                )
        finally:
            event.remove(SourceCashCoverageApply, "before_insert", fail)
        assert (
            count(session, CashBoundaryCoverage)
            == count(session, SourceCashCoverageRevision)
            == count(session, SourceCashCoverageApply)
            == 0
        )


def test_api_preview_apply_get_strict_inputs_and_writer_before_authoritative_reads(database):
    with database.session_factory() as session:
        raw = quiet_intent(session)
        intent = claims(session, raw, zero=True)
    client = TestClient(create_app(database=database))
    body = intent.model_dump(mode="json")
    plan = client.post("/api/cash-boundary-coverages/preview", json=body)
    assert plan.status_code == 200
    statements = []

    def record(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", record)
    try:
        result = client.post(
            "/api/cash-boundary-coverages/apply",
            json={
                **body,
                "confirmation_digest": plan.json()["confirmation_digest"],
                "request_id": "api",
            },
        )
    finally:
        event.remove(database.engine, "before_cursor_execute", record)
    assert result.status_code == 200, result.text
    assert statements[0].startswith("UPDATE source_cash_coverage_revisions")
    view = result.json()["readback"]
    assert (
        client.get(f"/api/cash-boundary-coverages/{view['coverage_id']}").json()[
            "source_acceptance"
        ]
        == view
    )
    for extra in ({"flow_ids": []}, {"source_ids": []}, {"amount": "1"}, {"scope": "portfolio"}):
        assert (
            client.post("/api/cash-boundary-coverages/preview", json={**body, **extra}).status_code
            == 422
        )


def test_broken_source_withdrawal_binds_new_current_conflict_without_positive_support(database):
    with database.session_factory() as session:
        raw = quiet_intent(session)
        first = certify(session, claims(session, raw, zero=True))["readback"]
        source_row = session.scalar(select(MyBrokerImport))
        source_row.normalized_json = "{}"
        session.commit()
        view = read_source_cash_coverage(session, first["coverage_id"])
        revoke = SourceCashIntent(
            operation="revoke",
            coverage_id=view["coverage_id"],
            expected_revision=view["revision"],
            reason_code="evidence_disputed",
        )
        plan = preview_source_cash_coverage(session, revoke)
        assert plan["can_apply"]
        source_row.normalized_json = "[]"
        session.commit()
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply_source_cash_coverage(
                session,
                revoke,
                confirmation_digest=plan["confirmation_digest"],
                request_id="stale-revoke",
            )
        assert certify(session, revoke, "broken-revoke")["readback"]["effective_state"] == "revoked"


@pytest.mark.parametrize(
    "payload",
    [
        {"account_id": 1, "opening_date": "2030-01-17", "closing_date": "2030-01-17"},
        {"operation": "revoke", "coverage_id": 1},
        {"account_id": True, "opening_date": "2030-01-16", "closing_date": "2030-01-17"},
        {
            "operation": "reaffirm",
            "account_id": 1,
            "opening_date": "2030-01-16",
            "closing_date": "2030-01-17",
        },
    ],
)
def test_intent_shape_rejects_undefined_or_expanded_authority(payload):
    with pytest.raises(ValidationError):
        SourceCashIntent.model_validate(payload)


@pytest.mark.parametrize("kind", ["gap", "overlap", "excluded", "absent", "opening_gap"])
def test_exact_historical_membership_covers_both_eod_boundaries_without_current_flags(
    database, kind
):
    with database.session_factory() as session:
        raw = quiet_intent(session)
        row = session.scalar(select(AccountPerformanceScopeMembership))
        if kind == "gap":
            row.effective_to = date(2030, 1, 15)
        elif kind == "opening_gap":
            row.effective_from = B
        elif kind == "excluded":
            row.include_in_returns = False
        elif kind == "absent":
            session.delete(row)
        else:
            session.add(
                AccountPerformanceScopeMembership(
                    account_id=raw.account_id,
                    effective_from=A,
                    effective_to=B,
                    include_in_returns=True,
                )
            )
        session.get(Account, raw.account_id).include_in_returns = True
        session.commit()
        plan = preview_source_cash_coverage(session, claims(session, raw, zero=True))
        assert "historical_membership_not_continuously_included" in plan["blockers"]
        assert not plan["can_apply"]


def test_mapping_remap_and_removed_binding_cannot_hide_previously_relevant_report(database):
    from hermes_finance.services.accounts import create_account

    with database.session_factory() as session:
        _, _, raw = prepared(session)
        first = certify(session, claims(session, raw))["readback"]
        other = create_account(session, name="Synthetic other", account_type="brokerage")
        row = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
        )
        row.hermes_account_id = other.id
        session.commit()
        changed = read_source_cash_coverage(session, first["coverage_id"])
        assert changed["coverage_state"] == "unknown"
        plan = preview_source_cash_coverage(session, claims(session, renew(raw, changed)))
        assert len(plan["evidence"]["dependencies"]["sources"]) == 1
        assert "accepted_mapping_changed" in plan["blockers"]
        source_row = session.scalar(select(MyBrokerImport))
        source_row.mappings_json = "[]"
        session.commit()
        plan = preview_source_cash_coverage(session, renew(raw, changed))
        assert len(plan["evidence"]["dependencies"]["sources"]) == 1
        assert "accepted_mapping_changed" in plan["blockers"]


def test_unrelated_account_range_and_current_flags_preserve_authority(database):
    from hermes_finance.services.accounts import create_account

    with database.session_factory() as session:
        _, flow, raw = prepared(session)
        first = certify(session, claims(session, raw))["readback"]
        document = xml(stamp="11", cash_day="2030-02-17")
        filename = FILENAME.replace("01.01.30-31.01.30", "01.02.30-28.02.30")
        apply(session, document, preview(session, document, filename), filename)
        session.get(Account, raw.account_id).include_in_returns = False
        session.commit()
        other = create_account(session, name="Synthetic unrelated", account_type="brokerage")
        session.add(
            CashBoundaryCoverage(
                account_id=other.id,
                covered_from=B,
                covered_to=B,
                coverage_state="complete",
                provenance_kind="owner_attestation",
            )
        )
        session.commit()
        assert read_source_cash_coverage(session, first["coverage_id"]) == first
        assert read_historical_owner_flow(session, flow["flow_id"]) == flow


def test_trade_support_report_outside_window_is_bound_and_retires_new_assertion(database):
    with database.session_factory() as session:
        document = fixture()
        result = apply(session, document, preview(session, document))
        account_id = result["mappings"][0]["hermes_id"]
        continuous_membership(session, account_id)
        raw = SourceCashIntent(account_id=account_id, opening_date=A, closing_date=B)
        first = certify(session, claims(session, raw, zero=True))["readback"]
        document = fixture(money=False)
        filename = FILENAME.replace("01.01.30-31.01.30", "01.02.30-28.02.30")
        later = apply(session, document, preview(session, document, filename), filename)
        retired = read_source_cash_coverage(session, first["coverage_id"])
        assert retired["acceptance_state"] == "retired"
        plan = preview_source_cash_coverage(session, renew(raw, retired))
        relevant = next(
            s
            for s in plan["evidence"]["dependencies"]["sources"]
            if s["import_id"] == later["import_id"]
        )
        assert (
            relevant["full_range"] == ["2030-02-01", "2030-02-28"]
            and relevant["clipped_range"] is None
        )


def test_overlap_unknown_and_legacy_cash_disclosed_before_acceptance(database):
    with database.session_factory() as session:
        raw = quiet_intent(session)
        session.add(
            CashBoundaryCoverage(
                account_id=raw.account_id,
                covered_from=A,
                covered_to=B,
                coverage_state="unknown",
                provenance_kind="owner_attestation",
            )
        )
        month = ReportingMonth(
            year=2030,
            month=1,
            period_start=date(2030, 1, 1),
            period_end=date(2030, 1, 31),
            snapshot_date=date(2030, 1, 31),
        )
        session.add(month)
        session.commit()
        session.add(
            InvestmentCashFlow(
                account_id=raw.account_id,
                reporting_month_id=month.id,
                event_date=B,
                flow_type="deposit",
                gross_amount_kopecks=1,
                tax_amount_kopecks=0,
                commission_amount_kopecks=0,
                net_amount_kopecks=1,
                source="manual",
            )
        )
        session.commit()
        plan = preview_source_cash_coverage(session, claims(session, raw, zero=True))
        assert "overlapping_cash_coverage" in plan["blockers"]
        assert "legacy_cash_or_transfer_overlap" in plan["blockers"]
        assert len(plan["evidence"]["dependencies"]["legacy_cash"]) == 1


def test_reaffirm_retired_is_explicit_identity_is_immutable_and_rollback_retirement_atomic(
    database,
):
    with database.session_factory() as session:
        raw = quiet_intent(session)
        first = certify(session, claims(session, raw, zero=True))["readback"]
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
        )
        mapping.source_as_of = B
        session.flush()
        session.rollback()
        assert read_source_cash_coverage(session, first["coverage_id"])["revision"] == 1
        mapping.source_as_of = B
        session.commit()
        mapping.source_as_of = None
        session.commit()
        retired = read_source_cash_coverage(session, first["coverage_id"])
        assert retired["acceptance_state"] == "retired"
        fresh = claims(session, raw, zero=True)
        assert (
            "reviewed_reaffirmation_required"
            in preview_source_cash_coverage(session, fresh)["blockers"]
        )
        renewed = certify(session, claims(session, renew(raw, retired), zero=True), "reaffirm")[
            "readback"
        ]
        assert renewed["coverage_state"] == "complete" and renewed["revision"] == 3
        bad = renew(raw, renewed).model_copy(update={"opening_date": date(2030, 1, 15)})
        assert (
            "coverage_identity_immutable" in preview_source_cash_coverage(session, bad)["blockers"]
        )
        row = session.get(CashBoundaryCoverage, first["coverage_id"])
        row.covered_from = A
        with pytest.raises(ValueError, match="immutable"):
            session.flush()
        session.rollback()


def test_legacy_complete_conflict_still_retires_v2_flow(database):
    with database.session_factory() as session:
        _, flow, raw = prepared(session)
        session.add(
            CashBoundaryCoverage(
                account_id=raw.account_id,
                covered_from=B,
                covered_to=B,
                coverage_state="complete",
                provenance_kind="owner_attestation",
            )
        )
        session.commit()
        assert read_historical_owner_flow(session, flow["flow_id"])["effective_state"] == "retired"


def test_no_account_source_authority_or_portfolio_binding_from_missing_history(database):
    with database.session_factory() as session:
        raw = quiet_intent(session)
        assert (
            assess_cash_boundary_coverage(
                session,
                scope="account",
                account_id=raw.account_id,
                start_date=B,
                end_date=B,
                rows_by_account={},
                ledger_binding=COMPATIBLE_FLOW_CONTRACT,
            ).status
            == "unknown"
        )
        with pytest.raises(ValueError, match="account scope"):
            assess_cash_boundary_coverage(
                session,
                scope="portfolio",
                account_id=None,
                start_date=B,
                end_date=B,
                rows_by_account={},
                ledger_binding=COMPATIBLE_FLOW_CONTRACT,
            )


def test_source_preview_stays_read_only_with_legacy_preparation_header(database):
    from hermes_finance.api.performance_evidence_guard import evidence_signature

    with database.session_factory() as session:
        intent = quiet_intent(session)
        legacy_token = evidence_signature(session)
    client = TestClient(create_app(database=database))
    response = client.post(
        "/api/cash-boundary-coverages/preview",
        json=intent.model_dump(mode="json"),
        headers={"X-Performance-Evidence": legacy_token},
    )
    assert response.status_code == 200, response.text


def coupon_xml(
    *, stamp="10", bank=False, nkd=False, coupons=("1000", "1000", "2000", "3000", "4000")
):
    from decimal import Decimal
    from xml.etree import ElementTree as ET

    from test_statement_import_mybroker_endpoints import money_batch_xml
    from test_statement_import_mybroker_money_candidates import CASH_IN

    root = ET.fromstring(money_batch_xml(coupons=coupons, distinct=True, stamp=stamp, nkd=nkd))
    if not bank:
        collection = root.find(".//{MyBroker}rn_Collection")
        for row in list(collection):
            comment = row.find("{MyBroker}oper_type/{MyBroker}comment")
            if comment is not None and comment.get("comment") == CASH_IN:
                collection.remove(row)
                cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
                cash.set("real_rest", str(Decimal(cash.get("real_rest")) - 50000))
    return ET.tostring(root, encoding="utf-8")


def coupon_setup(database, *, raw=None, overlap=False, reverse=False, accepted=True):
    from test_statement_import_mybroker_endpoints import _money_apply, _money_decide, _money_setup

    raw = raw or coupon_xml()
    other = coupon_xml(stamp="11") if overlap else None
    client, first, intent, bond, base = _money_setup(database, other if reverse else raw)
    originals = [(FILENAME, first)]
    with database.session_factory() as session:
        if overlap:
            second = raw if reverse else other
            apply(session, second, preview(session, second))
            originals.append((FILENAME, second))
        continuous_membership(session, intent.account_id)
        if accepted:
            reviewed = _money_decide(session, intent, originals, bond, funding=False)
            saved = _money_apply(session, reviewed, originals)
            assert len(saved["targets"]) == 5
            assert all(t["effective"] for t in saved["targets"])
        coverage = SourceCashIntent(
            account_id=intent.account_id,
            opening_date=date(2029, 12, 31),
            closing_date=date(2030, 1, 31),
        )
    return client, intent, bond, originals, coverage


@pytest.mark.parametrize("reverse", [False, True])
def test_coupon_v3_real_money_five_targets_overlap_no_write_no_owner_cash(database, reverse):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.persistence import (
        BrokerMoneyOccurrenceOwner,
        CashBalance,
        HistoricalOwnerFlow,
    )
    from hermes_finance.services.broker_money import latest_proofs, proof_blockers, read_money
    from hermes_finance.services.broker_statement_return import read_statement_return
    from hermes_finance.services.source_cash_coverage import SECTION_CONTRACT, inventory

    _, money_intent, _, _, raw = coupon_setup(database, overlap=True, reverse=reverse)
    with database.session_factory() as session:
        before = _all_month_tables(database)
        old = inventory(
            session, raw.account_id, raw.opening_date, raw.closing_date, contract=SECTION_CONTRACT
        )
        assert {"money_disposition_unresolved", "legacy_cash_or_transfer_overlap"} <= set(
            old["blockers"]
        )
        assert "coupon_authority" not in old
        for receipt, proof, target in latest_proofs(session).values():
            assert not proof_blockers(session, receipt, proof, target)
        accepted = certify(session, claims(session, raw, zero=True))["readback"]
        deps = accepted["evidence"]["dependencies"]
        assert accepted["evidence"]["contract_version"] == "h2-a2-source-cash-rub-v3"
        assert (
            len(deps["effective_coupon_icf_ids"]) == len(set(deps["effective_coupon_icf_ids"])) == 5
        )
        assert len(deps["legacy_cash"]) == 5  # retained evidence, exact partition only
        assert (
            sum(o["disposition"] == "accepted_non_owner_coupon" for o in deps["money_dispositions"])
            == 10
        )
        assert all(
            not t["blockers"] and len(t["owners"]) == 2 for t in deps["coupon_authority"]["targets"]
        )
        assert count(session, BrokerMoneyOccurrenceOwner) == 10
        assert count(session, InvestmentCashFlow) == 5
        assert count(session, HistoricalOwnerFlow) == count(session, ExternalFlow) == 0
        after = _all_month_tables(database)
        for table in before:
            if table not in {
                "cash_boundary_coverages",
                "source_cash_coverage_revisions",
                "source_cash_coverage_applies",
            }:
                assert before[table] == after[table]
        assert count(session, CashBalance) == 1
        for _ in range(10):
            section_coverage_assert(session, renew(raw, accepted), "complete")
            assert all(t["effective"] for t in read_money(session, "money-accepted")["targets"])
            s3 = read_statement_return(
                session, request_id=money_intent.base_request_id, account_id=raw.account_id
            )
            assert s3.rate_fraction is None
        assert _all_month_tables(database) == after


@pytest.mark.parametrize(
    "shape", ["candidates", "bank", "nkd", "membership", "other_icf", "external"]
)
def test_coupon_v3_only_proven_icf_partition_other_conflicts_stay_unknown(database, shape):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    raw_xml = coupon_xml(bank=shape == "bank", nkd=shape == "nkd")
    _, _, _, _, raw = coupon_setup(database, raw=raw_xml, accepted=shape != "candidates")
    with database.session_factory() as session:
        if shape == "membership":
            membership = session.scalar(
                select(AccountPerformanceScopeMembership).where(
                    AccountPerformanceScopeMembership.account_id == raw.account_id
                )
            )
            membership.include_in_returns = False
            session.commit()
        elif shape == "other_icf":
            existing = session.scalar(select(InvestmentCashFlow))
            session.add(
                InvestmentCashFlow(
                    reporting_month_id=existing.reporting_month_id,
                    account_id=raw.account_id,
                    instrument_id=existing.instrument_id,
                    flow_type="interest",
                    event_date=B,
                    gross_amount_kopecks=1,
                    tax_amount_kopecks=0,
                    commission_amount_kopecks=0,
                    net_amount_kopecks=1,
                    currency="RUB",
                    source="synthetic",
                )
            )
            session.commit()
        elif shape == "external":
            from hermes_finance.services.external_flows import create_external_flow

            create_external_flow(
                session,
                reporting_month_id=session.scalar(select(ReportingMonth.id)),
                account_id=raw.account_id,
                event_date=B,
                direction="contribution",
                kind="external_contribution",
                boundary_amount="1.00",
            )
        before = _all_month_tables(database)
        plan = preview_source_cash_coverage(session, claims(session, raw, zero=True))
        assert not plan["can_apply"]
        deps = plan["evidence"]["dependencies"]
        if shape in ("bank", "nkd"):
            assert len(deps["effective_coupon_icf_ids"]) == 5
            assert "legacy_cash_or_transfer_overlap" not in deps["blockers"]
            assert "money_disposition_unresolved" in deps["blockers"]
        if shape == "candidates":
            assert not deps["effective_coupon_icf_ids"]
            assert all(
                o["disposition"] != "accepted_non_owner_coupon" for o in deps["money_dispositions"]
            )
        assert _all_month_tables(database) == before


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("trigger", ["journal", "comment"])
def test_coupon_v3_money_receipt_retires_closed_late_listener_replay_reaffirm(
    database, closed, trigger
):
    import json
    from datetime import UTC, datetime
    from uuid import uuid4

    from test_statement_import_mybroker_endpoints import _money_apply, _money_decide

    from hermes_finance.persistence import BrokerMonthApply, MonthlyComment
    from hermes_finance.services.broker_money import read_money
    from hermes_finance.services.broker_money_lifecycle import next_journal_revision
    from hermes_finance.statement_import.mybroker import canonical

    _, money_intent, bond, originals, raw = coupon_setup(database)
    with database.session_factory() as session:
        reviewed = claims(session, raw, zero=True)
        old_plan = preview_source_cash_coverage(session, reviewed)
        accepted = certify(session, reviewed)["readback"]
        frozen = session.get(SourceCashCoverageRevision, accepted["revision_id"]).evidence_json
        month = session.get(ReportingMonth, money_intent.reporting_month_id)
        if closed:
            month.status = "closed"
            session.commit()
        section_coverage_assert(session, renew(raw, accepted), "complete")
        receipt = session.get(BrokerMonthApply, "money-accepted")
        proof = json.loads(receipt.projection_json)
        from hermes_finance.services.reporting_months import create_reporting_month

        other_month_id = create_reporting_month(
            session, year=2030, month=2, snapshot_date=date(2030, 2, 28)
        ).id

        def late(current, _context, _instances):
            if current is session and not current.info.get("coupon_late"):
                current.info["coupon_late"] = True
                current.add(
                    BrokerMonthApply(
                        request_id="late-coupon-retire",
                        request_fingerprint="a" * 64,
                        confirmation_digest="b" * 64,
                        account_id=receipt.account_id,
                        reporting_month_id=receipt.reporting_month_id,
                        import_id=receipt.import_id,
                        projection_json=canonical(
                            {
                                **proof,
                                "operation": "retire",
                                "journal_revision": next_journal_revision(current),
                            }
                        ),
                        accepted_at=datetime.now(UTC),
                    )
                )

        event.listen(type(session), "before_flush", late)
        try:
            # An unrelated journal change triggers the flush before late listener.
            token = uuid4().hex
            if trigger == "comment":
                session.add(
                    MonthlyComment(
                        reporting_month_id=other_month_id,
                        position=1,
                        text="Synthetic unrelated flush",
                    )
                )
            else:
                session.add(
                    BrokerMonthApply(
                        request_id=token,
                        request_fingerprint="c" * 64,
                        confirmation_digest="d" * 64,
                        account_id=receipt.account_id,
                        reporting_month_id=receipt.reporting_month_id,
                        import_id=receipt.import_id,
                        projection_json=canonical(
                            {
                                "contract_version": "broker_money_v1",
                                "base_request_id": "foreign-base",
                                "operation": "accept",
                                "sources": [],
                                "occurrences": [],
                                "targets": [],
                            }
                        ),
                        accepted_at=datetime.now(UTC),
                    )
                )
            session.commit()
        finally:
            event.remove(type(session), "before_flush", late)
        retired = section_coverage_assert(session, renew(raw, accepted), "unknown")
        assert retired["acceptance_state"] == "retired" and retired["revision"] == 2
        assert not any(t["effective"] for t in read_money(session, "money-accepted")["targets"])
        replay = apply_source_cash_coverage(
            session,
            reviewed,
            confirmation_digest=old_plan["confirmation_digest"],
            request_id="coverage-apply",
        )
        assert replay["replayed"] and replay["readback"]["effective_state"] == "retired"
        assert (
            session.get(SourceCashCoverageRevision, accepted["revision_id"]).evidence_json == frozen
        )
        if closed:
            assert (
                "closed_reporting_month_requires_reopen"
                in preview_source_cash_coverage(session, renew(raw, retired))["blockers"]
            )
            month.status = "draft"
            session.commit()
        fresh_money = _money_decide(
            session, money_intent, originals, bond, funding=False, operation="reaffirm"
        )
        _money_apply(session, fresh_money, originals, "money-reaffirmed")
        assert (
            read_source_cash_coverage(session, accepted["coverage_id"])["effective_state"]
            == "retired"
        )
        renewed = certify(
            session, claims(session, renew(raw, retired), zero=True), "coverage-reaffirmed"
        )["readback"]
        assert renewed["effective_state"] == "accepted" and renewed["revision"] == 3
        assert count(session, InvestmentCashFlow) == 5


@pytest.mark.parametrize(
    "change",
    [
        "source_plus",
        "source_minus",
        "source_account",
        "source_date",
        "source_currency",
        "source_malformed",
        "source_nonfinite",
        "source_overflow",
        "target_net",
        "target_currency",
        "target_date",
        "target_instrument",
        "target_month",
        "target_tax",
        "missing_owner",
        "owner_fingerprint",
        "owner_target",
        "missing_proof",
        "wrong_receipt_account",
        "wrong_receipt_month",
        "malformed_occurrence",
        "malformed_receipt",
    ],
)
def test_coupon_v3_corrupt_current_source_owner_target_proof_fails_closed_without_read_repair(
    database, change
):
    import json

    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.persistence import BrokerMoneyOccurrenceOwner, BrokerMonthApply
    from hermes_finance.services.source_cash_coverage import inventory
    from hermes_finance.statement_import.mybroker import canonical

    _, _, _, _, raw = coupon_setup(database)
    with database.session_factory() as session:
        accepted = certify(session, claims(session, raw, zero=True))["readback"]
        target_ids = accepted["evidence"]["dependencies"]["effective_coupon_icf_ids"]
        owner = session.scalar(
            select(BrokerMoneyOccurrenceOwner).where(
                BrokerMoneyOccurrenceOwner.investment_cash_flow_id == target_ids[0]
            )
        )
        source_id, ordinal, owner_id = owner.import_id, owner.ordinal, owner.id
        # Deliberate synthetic storage corruption bypasses the immutable writers.
        # The reader must still refuse authority, without repairing history.
        if change.startswith("source_"):
            source = session.get(MyBrokerImport, source_id)
            payload = json.loads(source.normalized_json)
            row = next(r for r in payload["money"] if r["ordinal"] == ordinal)
            field, value = {
                "source_plus": ("amount", "1000.01"),
                "source_minus": ("amount", "999.99"),
                "source_account": ("source_account", "foreign-alias"),
                "source_date": ("date", "2030-01-18"),
                "source_currency": ("currency", "USD"),
                "source_malformed": ("amount", "not-a-number"),
                "source_nonfinite": ("amount", "NaN"),
                "source_overflow": ("amount", "1e1000001"),
            }[change]
            row[field] = value
            session.execute(
                text("UPDATE mybroker_imports SET normalized_json=:payload WHERE id=:id"),
                {"payload": canonical(payload), "id": source_id},
            )
        elif change.startswith("target_"):
            field, value = {
                "target_net": ("net_amount_kopecks", 100001),
                "target_currency": ("currency", "USD"),
                "target_date": ("event_date", "2030-01-18"),
                "target_instrument": ("instrument_id", 1),
                "target_month": ("reporting_month_id", 999),
                "target_tax": ("tax_amount_kopecks", 0),
            }[change]
            if change in ("target_currency", "target_tax"):
                from sqlalchemy.exc import IntegrityError

                before = _all_month_tables(database)
                with pytest.raises(IntegrityError, match="ck_investment_cash_flows_amount_basis"):
                    session.execute(
                        text(f"UPDATE investment_cash_flows SET {field}=:value WHERE id=:id"),
                        {"value": value, "id": target_ids[0]},
                    )
                session.rollback()
                assert _all_month_tables(database) == before
                section_coverage_assert(session, renew(raw, accepted), "complete")
                return
            if change == "target_month":
                from hermes_finance.services.reporting_months import create_reporting_month

                value = create_reporting_month(
                    session, year=2030, month=2, snapshot_date=date(2030, 2, 28)
                ).id
            session.execute(
                text(f"UPDATE investment_cash_flows SET {field}=:value WHERE id=:id"),
                {"value": value, "id": target_ids[0]},
            )
        elif change == "missing_owner":
            session.execute(
                text("DELETE FROM broker_money_occurrence_owners WHERE id=:id"), {"id": owner_id}
            )
        elif change.startswith("owner_"):
            field, value = (
                ("row_fingerprint", "b" * 64)
                if change == "owner_fingerprint"
                else ("investment_cash_flow_id", target_ids[1])
            )
            session.execute(
                text(f"UPDATE broker_money_occurrence_owners SET {field}=:value WHERE id=:id"),
                {"value": value, "id": owner_id},
            )
        elif change in ("missing_proof", "malformed_occurrence", "malformed_receipt"):
            receipt = session.get(BrokerMonthApply, "money-accepted")
            payload = json.loads(receipt.projection_json)
            if change == "missing_proof":
                payload["targets"] = payload["targets"][1:]
            elif change == "malformed_occurrence":
                del payload["occurrences"][0]["ordinal"]
            session.execute(
                text(
                    "UPDATE broker_month_applies SET projection_json=:value WHERE request_id='money-accepted'"
                ),
                {"value": "invalid-json" if change == "malformed_receipt" else canonical(payload)},
            )
        else:
            field, value = (
                ("account_id", 2)
                if change == "wrong_receipt_account"
                else ("reporting_month_id", 999)
            )
            if field == "account_id":
                from hermes_finance.services.accounts import create_account

                value = create_account(session, name="Foreign", account_type="brokerage").id
            else:
                from hermes_finance.services.reporting_months import create_reporting_month

                value = create_reporting_month(
                    session, year=2030, month=2, snapshot_date=date(2030, 2, 28)
                ).id
            session.execute(
                text(
                    f"UPDATE broker_month_applies SET {field}=:value WHERE request_id='money-accepted'"
                ),
                {"value": value},
            )
        session.commit()
        session.expire_all()
        before = _all_month_tables(database)
        deps = inventory(session, raw.account_id, raw.opening_date, raw.closing_date)
        assert target_ids[0] not in deps["effective_coupon_icf_ids"]
        assert "legacy_cash_or_transfer_overlap" in deps["blockers"]
        view = section_coverage_assert(session, renew(raw, accepted), "unknown")
        assert view["effective_state"] in {"invalidated", "retired"}
        assert _all_month_tables(database) == before


def test_coupon_v3_account_aba_stales_preview_and_never_revives_retired_coverage(database):
    from test_statement_import_mybroker_endpoints import _money_apply, _money_decide

    from hermes_finance.persistence import Account
    from hermes_finance.services.broker_money import read_money

    _, money_intent, bond, originals, raw = coupon_setup(database)
    with database.session_factory() as session:
        intent = claims(session, raw, zero=True)
        plan = preview_source_cash_coverage(session, intent)
        accepted = certify(session, intent)["readback"]
        account = session.get(Account, raw.account_id)
        name = account.name
        account.name += " B"
        session.commit()
        account.name = name
        session.commit()
        retired = section_coverage_assert(session, renew(raw, accepted), "unknown")
        assert retired["acceptance_state"] == "retired" and retired["revision"] == 2
        assert all(not t["effective"] for t in read_money(session, "money-accepted")["targets"])
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply_source_cash_coverage(
                session,
                intent,
                confirmation_digest=plan["confirmation_digest"],
                request_id="old-unused-request",
            )
        fresh_money = _money_decide(
            session, money_intent, originals, bond, funding=False, operation="reaffirm"
        )
        _money_apply(session, fresh_money, originals, "aba-money-reaffirm")
        section_coverage_assert(session, renew(raw, accepted), "unknown")
        certify(session, claims(session, renew(raw, retired), zero=True), "aba-coverage-reaffirm")


@pytest.mark.parametrize("change", ["event_aba", "revision_aba", "retract"])
def test_coupon_v3_typed_pdf_addition_retires_coverage_and_mutations_are_monotonic(
    database, change
):
    from test_statement_import_apply import apply as income_apply
    from test_statement_import_apply import preview as income_preview
    from test_statement_import_apply import selection_from_row
    from test_statement_import_mybroker_endpoints import money_coupon_pdf

    from hermes_finance.persistence import AppliedStatementEvent, AppliedStatementEventRevision
    from hermes_finance.services.broker_money import read_money
    from hermes_finance.services.statement_import_apply import StatementApplyAction
    from hermes_finance.services.statement_import_retract import retract_applied_statement_event

    _, _, _, _, raw = coupon_setup(database)
    with database.session_factory() as session:
        accepted = certify(session, claims(session, raw, zero=True))["readback"]
        deps = accepted["evidence"]["dependencies"]
        target_id = deps["effective_coupon_icf_ids"][0]
        pdf = money_coupon_pdf()
        row = income_preview(session, pdf, raw.account_id).rows[0]
        result = income_apply(
            session,
            pdf,
            raw.account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=target_id,
                    expected_candidate_ids=tuple(deps["effective_coupon_icf_ids"]),
                ),
            ),
        )
        assert result.success, result
        assert all(t["effective"] for t in read_money(session, "money-accepted")["targets"])
        retired = section_coverage_assert(session, renew(raw, accepted), "unknown")
        assert retired["acceptance_state"] == "retired"
        renewed = certify(session, claims(session, renew(raw, retired), zero=True), "pdf-reviewed")[
            "readback"
        ]
        event_row = session.get(AppliedStatementEvent, result.items[0].applied_statement_event_id)
        if change == "retract":
            result = retract_applied_statement_event(session, event_row.id)
            assert not result.cash_flow_deleted
        else:
            obj = (
                event_row
                if change == "event_aba"
                else session.get(AppliedStatementEventRevision, result.items[0].revision_id)
            )
            field = "material_fingerprint" if change == "event_aba" else "net_amount_kopecks"
            old = getattr(obj, field)
            setattr(obj, field, "b" * 64 if change == "event_aba" else old + 1)
            session.commit()
            setattr(obj, field, old)
            session.commit()
        view = section_coverage_assert(session, renew(raw, renewed), "unknown")
        assert view["acceptance_state"] == "retired"
        targets = read_money(session, "money-accepted")["targets"]
        assert not targets[0]["effective"] and all(t["effective"] for t in targets[1:])
        assert count(session, InvestmentCashFlow) == 5


def test_coupon_v3_pdf_first_real_money_links_existing_target_tax_unknown(database):
    from test_statement_import_apply import apply as income_apply
    from test_statement_import_apply import preview as income_preview
    from test_statement_import_apply import selection_from_row
    from test_statement_import_mybroker_endpoints import (
        _money_apply,
        _money_decide,
        _money_setup,
        money_coupon_pdf,
    )

    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.services.broker_money import preview_money

    _, document, money_intent, bond, _ = _money_setup(
        database, coupon_xml(coupons=("1000", "2000", "3000", "4000", "5000"))
    )
    originals = [(FILENAME, document)]
    with database.session_factory() as session:
        continuous_membership(session, money_intent.account_id)
        pdf = money_coupon_pdf()
        row = income_preview(session, pdf, money_intent.account_id).rows[0]
        applied = income_apply(session, pdf, money_intent.account_id, (selection_from_row(row),))
        assert applied.success, applied
        target_id = applied.items[0].investment_cash_flow_id
        reviewed = _money_decide(session, money_intent, originals, bond, funding=False)
        decisions = reviewed.model_dump()["money_decisions"]
        decisions[0]["investment_cash_flow_id"] = target_id
        requested = MoneyIntent.model_validate(
            {**reviewed.model_dump(), "money_decisions": decisions}
        )
        plan = preview_money(session, requested, originals)
        decisions[0]["coupon_claims"]["review_context_digest"] = plan["decisions"][0][
            "review_context_digest"
        ]
        requested = MoneyIntent.model_validate(
            {**reviewed.model_dump(), "money_decisions": decisions}
        )
        saved = _money_apply(session, requested, originals)
        assert all(t["effective"] for t in saved["targets"])
        raw = SourceCashIntent(
            account_id=money_intent.account_id,
            opening_date=date(2029, 12, 31),
            closing_date=date(2030, 1, 31),
        )
        accepted = certify(session, claims(session, raw, zero=True))["readback"]
        section_coverage_assert(session, renew(raw, accepted), "complete")
        deps = accepted["evidence"]["dependencies"]
        assert target_id in deps["effective_coupon_icf_ids"]
        target = next(t for t in deps["coupon_authority"]["targets"] if t["target_id"] == target_id)
        assert target["current_target"]["components"]["tax_amount_kopecks"] is None
        assert len(target["current_target"]["statement_support"]["events"]) == 1
        assert count(session, InvestmentCashFlow) == 5


def test_coupon_v3_late_source_add_remove_aba_requires_both_reviews(database):
    from test_statement_import_mybroker_endpoints import _money_apply, _money_decide

    from hermes_finance.services.broker_money import read_money

    _, money_intent, bond, originals, raw = coupon_setup(database)
    with database.session_factory() as session:
        accepted = certify(session, claims(session, raw, zero=True))["readback"]
        # A covering original with missing coupon events cannot inherit authority.
        other = coupon_xml(stamp="11", coupons=("1000",))
        added = apply(session, other, preview(session, other))
        retired = section_coverage_assert(session, renew(raw, accepted), "unknown")
        assert retired["acceptance_state"] == "retired"
        assert all(not t["effective"] for t in read_money(session, "money-accepted")["targets"])
        session.delete(session.get(MyBrokerImport, added["import_id"]))
        session.commit()
        section_coverage_assert(session, renew(raw, retired), "unknown")
        assert all(not t["effective"] for t in read_money(session, "money-accepted")["targets"])
        fresh = _money_decide(
            session, money_intent, originals, bond, funding=False, operation="reaffirm"
        )
        _money_apply(session, fresh, originals, "source-aba-money")
        section_coverage_assert(session, renew(raw, retired), "unknown")
        certify(session, claims(session, renew(raw, retired), zero=True), "source-aba-coverage")
        assert count(session, InvestmentCashFlow) == 5


def test_coupon_v3_dependency_retirement_late_failure_rolls_back_all_tables(database):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.persistence import Account

    _, _, _, _, raw = coupon_setup(database)
    with database.session_factory() as session:
        accepted = certify(session, claims(session, raw, zero=True))["readback"]
        before = _all_month_tables(database)

        def fail(current, _context):
            if current is session:
                raise RuntimeError("synthetic after-retirement failure")

        event.listen(type(session), "after_flush_postexec", fail)
        try:
            session.get(Account, raw.account_id).name += " failed B"
            with pytest.raises(RuntimeError, match="after-retirement failure"):
                session.commit()
            session.rollback()
        finally:
            event.remove(type(session), "after_flush_postexec", fail)
        assert _all_month_tables(database) == before
        section_coverage_assert(session, renew(raw, accepted), "complete")
