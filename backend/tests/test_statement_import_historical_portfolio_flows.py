"""Private-free H2-B1 boundary, dependency, atomicity and receipt evidence."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select, text
from test_statement_import_historical_owner_flows import (
    DAY,
    count,
    source,
    xml,
)
from test_statement_import_historical_owner_flows import (
    accept as account_accept,
)
from test_statement_import_historical_owner_flows import (
    attest as account_attest,
)
from test_statement_import_mybroker import ACCOUNT, FILENAME, apply, preview
from test_statement_import_mybroker import database as database

from hermes_finance.domain.historical_portfolio_flows import (
    OUTSIDE_CLAIMS,
    ROSTER_CLAIMS,
    PortfolioFlowIntent,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    CashBalance,
    CashBoundaryCoverage,
    ExternalFlow,
    ExternalTransferLink,
    ExternalTransferReconciliationEvidence,
    HistoricalOwnerFlow,
    HistoricalOwnerFlowOccurrence,
    HistoricalPortfolioFlowApply,
    HistoricalPortfolioFlowRevision,
    InvestmentCashFlow,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.broker_identity_mappings import confirm_mapping, revoke_mapping
from hermes_finance.services.historical_owner_flows import (
    apply_historical_owner_flow,
    preview_historical_owner_flow,
    read_historical_owner_flow,
)
from hermes_finance.services.historical_portfolio_flows import (
    apply_historical_portfolio_flow,
    preview_historical_portfolio_flow,
    read_historical_portfolio_flow,
)
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError


def other_account(session, *, included=False, account_type="brokerage", status="hidden"):
    account = Account(name="Synthetic", account_type=account_type, status=status)
    session.add(account)
    session.flush()
    session.add(
        AccountPerformanceScopeMembership(
            account_id=account.id,
            effective_from=date(2029, 1, 1),
            include_in_returns=included,
        )
    )
    session.commit()
    return account


def start(session, **kwargs):
    intent = source(session, **kwargs)
    session.add(
        AccountPerformanceScopeMembership(
            account_id=intent.account_id,
            effective_from=DAY,
            effective_to=DAY,
            include_in_returns=True,
        )
    )
    session.commit()
    readback = account_accept(session, account_attest(session, intent))["readback"]
    return PortfolioFlowIntent(
        flow_id=readback["flow_id"],
        expected_flow_revision=readback["revision"],
        expected_portfolio_revision=0,
    )


def attest(session, intent, *, dispositions=None):
    plan = preview_historical_portfolio_flow(session, intent)
    catalogue = plan["evidence"]["dependencies"]["catalogue"]
    roster = {
        "provenance_kind": "owner_attested_dated_roster",
        "reference": "synthetic-roster",
        "event_date": DAY.isoformat(),
        "catalogue_account_ids": [int(a["id"]) for a in catalogue],
        "entries": [
            {
                "account_id": int(a["id"]),
                "disposition": (dispositions or {}).get(int(a["id"]), "tracked"),
                "reference": "synthetic-disposition",
                "historical_disposition_confirmed": True,
            }
            for a in catalogue
        ],
        "review_context_digest": "a" * 64,
        **dict.fromkeys(ROSTER_CLAIMS, True),
    }
    staged = PortfolioFlowIntent.model_validate(
        {**intent.model_dump(mode="json"), "roster": roster}
    )
    bound = preview_historical_portfolio_flow(session, staged)
    roster["review_context_digest"] = bound["review_context_digest"]
    outside = {
        "provenance_kind": "owner_attested_source_row",
        "reference": "synthetic-outside",
        "flow_id": intent.flow_id,
        "flow_revision_id": bound["evidence"]["dependencies"]["target_flow_revision_id"],
        "source_set_fingerprint": bound["source_set_fingerprint"],
        "review_context_digest": bound["review_context_digest"],
        **dict.fromkeys(OUTSIDE_CLAIMS, True),
    }
    return PortfolioFlowIntent.model_validate(
        {
            **intent.model_dump(mode="json"),
            "roster": roster,
            "outside": outside,
        }
    )


def accept(session, intent, request_id="synthetic-portfolio"):
    plan = preview_historical_portfolio_flow(session, intent)
    assert plan["can_apply"], plan["blockers"]
    return apply_historical_portfolio_flow(
        session,
        intent,
        confirmation_digest=plan["confirmation_digest"],
        request_id=request_id,
    )


def amend(intent, **changes):
    return PortfolioFlowIntent.model_validate({**intent.model_dump(mode="json"), **changes})


@pytest.mark.parametrize("amount,direction", [("12.34", "contribution"), ("-12.34", "withdrawal")])
def test_external_exact_core_complete_roster_no_materialization(database, amount, direction):
    with database.session_factory() as session:
        other = other_account(session, included=False, account_type="deposit", status="closed")
        intent = attest(session, start(session, amount=amount))
        before = read_historical_owner_flow(session, intent.flow_id)
        result = accept(session, intent)
        readback = read_historical_portfolio_flow(session, intent.flow_id)
        assert result["readback"] == readback
        assert readback["portfolio_scope"] == {
            "status": "authoritative",
            "classification": "external_" + direction,
        }
        assert readback["core"] == before["core"]
        assert readback["boundary_amount_kopecks"] == 1234
        assert readback["evidence"]["tracked_account_ids"] == sorted(
            [other.id, before["core"]["account_id"]]
        )
        assert readback["evidence"]["included_account_ids"] == [before["core"]["account_id"]]
        assert readback["cash_coverage"] == "unknown"
        assert read_historical_owner_flow(session, intent.flow_id) == before
        assert (
            count(session, HistoricalOwnerFlow)
            == count(session, HistoricalOwnerFlowOccurrence)
            == 1
        )
        for model in (
            ReportingMonth,
            ExternalFlow,
            InvestmentCashFlow,
            CashBalance,
            PositionSnapshot,
            CashBoundaryCoverage,
        ):
            assert count(session, model) == 0


def test_inspection_missing_default_unconfirmed_claims_and_no_acceptance(database):
    with database.session_factory() as session:
        intent = start(session)
        plan = preview_historical_portfolio_flow(session, intent)
        assert not plan["can_apply"]
        assert "dated_roster_claims_missing" in plan["blockers"]
        assert "outside_universe_claims_missing" in plan["blockers"]
        assert plan["evidence"]["dependencies"]["catalogue"]
        assert plan["evidence"]["dependencies"]["sources"]
        assert (
            read_historical_portfolio_flow(session, intent.flow_id)["boundary_amount_kopecks"]
            is None
        )


@pytest.mark.parametrize("claim", ROSTER_CLAIMS + OUTSIDE_CLAIMS)
def test_every_claim_affirmative_no_account_claim_reuse(database, claim):
    with database.session_factory() as session:
        intent = attest(session, start(session))
        data = intent.model_dump(mode="json")
        data["roster" if claim in ROSTER_CLAIMS else "outside"][claim] = False
        plan = preview_historical_portfolio_flow(session, PortfolioFlowIntent.model_validate(data))
        assert claim + "_unconfirmed" in plan["blockers"]
        assert not plan["can_apply"]


@pytest.mark.parametrize(
    "mutation",
    [
        "subset",
        "missing_entry",
        "wrong_date",
        "wrong_digest",
        "wrong_flow_revision",
        "wrong_occurrences",
        "unconfirmed_disposition",
    ],
)
def test_exact_roster_row_revision_and_digest_binding(database, mutation):
    with database.session_factory() as session:
        other_account(session, included=False, status="frozen")
        intent = attest(session, start(session))
        data = intent.model_dump(mode="json")
        if mutation == "subset":
            data["roster"]["catalogue_account_ids"].pop()
        elif mutation == "missing_entry":
            data["roster"]["entries"].pop()
        elif mutation == "wrong_date":
            data["roster"]["event_date"] = "2030-01-18"
        elif mutation == "wrong_digest":
            data["outside"]["review_context_digest"] = "b" * 64
        elif mutation == "wrong_flow_revision":
            data["outside"]["flow_revision_id"] += 1
        elif mutation == "wrong_occurrences":
            data["outside"]["source_set_fingerprint"] = "b" * 64
        else:
            data["roster"]["entries"][0]["historical_disposition_confirmed"] = False
        assert not preview_historical_portfolio_flow(
            session, PortfolioFlowIntent.model_validate(data)
        )["can_apply"]
        assert count(session, HistoricalPortfolioFlowRevision) == 0


@pytest.mark.parametrize(
    "case", ["missing", "gap", "equal_overlap", "conflicting_overlap", "unsupported_included"]
)
def test_other_account_membership_not_current_flags_is_required(database, case):
    with database.session_factory() as session:
        other = other_account(
            session, included=case == "unsupported_included", account_type="savings"
        )
        membership = session.scalar(
            select(AccountPerformanceScopeMembership).where(
                AccountPerformanceScopeMembership.account_id == other.id
            )
        )
        if case == "missing":
            session.delete(membership)
        elif case == "gap":
            membership.effective_to = date(2030, 1, 16)
        elif "overlap" in case:
            session.add(
                AccountPerformanceScopeMembership(
                    account_id=other.id,
                    effective_from=DAY,
                    include_in_returns=case == "conflicting_overlap",
                )
            )
        session.commit()
        intent = attest(session, start(session))
        plan = preview_historical_portfolio_flow(session, intent)
        assert not plan["can_apply"]
        assert (
            "included_account_type_unsupported"
            if case == "unsupported_included"
            else "dated_membership_missing_or_ambiguous"
        ) in plan["blockers"]


def test_explicit_not_relevant_disposition_and_contradiction(database):
    with database.session_factory() as session:
        future = Account(name="Synthetic future", account_type="iis")
        session.add(future)
        session.commit()
        intent = attest(session, start(session), dispositions={future.id: "not_yet_opened"})
        assert preview_historical_portfolio_flow(session, intent)["can_apply"]
        accept(session, intent)
        session.add(
            AccountPerformanceScopeMembership(
                account_id=future.id, effective_from=DAY, include_in_returns=True
            )
        )
        session.commit()
        retired = read_historical_portfolio_flow(session, intent.flow_id)
        assert retired["effective_state"] == "retired"
        assert "historical_disposition_contradicted" in retired["blockers"]


def test_explicit_exclusion_not_in_scope_preserves_account_authority(database):
    with database.session_factory() as session:
        intent = start(session)
        membership = session.scalar(select(AccountPerformanceScopeMembership))
        membership.include_in_returns = False
        session.commit()
        # Existing H2-A1 lifecycle requires its own reviewed reaffirmation.
        account = read_historical_owner_flow(session, intent.flow_id)
        original = account["evidence"]["intent"]
        from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent

        original.update(
            operation="reaffirm",
            flow_id=intent.flow_id,
            expected_revision=account["revision"],
            claims=None,
        )
        account_accept(
            session,
            account_attest(session, OwnerFlowIntent.model_validate(original)),
            "account-renew",
        )
        intent = amend(intent, expected_flow_revision=3)
        bound = attest(session, intent)
        assert (
            "source_account_not_in_scope"
            in preview_historical_portfolio_flow(session, bound)["blockers"]
        )
        readback = read_historical_portfolio_flow(session, intent.flow_id)
        assert readback["portfolio_scope"]["status"] == "not_in_scope"
        assert readback["account_scope"]["status"] == "authoritative"
        assert readback["boundary_amount_kopecks"] is None


def add_other_source(session, other, *, opaque=False, cash_day="2030-01-17", amount="-12.34"):
    alias = "7654321-000"
    for identity in (alias, "7654321"):
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="account",
            provider_identity=identity,
            hermes_target_id=other.id,
        )
    raw = xml(opaque=opaque, cash_day=cash_day, amount=amount).replace(
        ACCOUNT.encode(), alias.encode()
    )
    filename = FILENAME.replace("1234567", "7654321")
    return apply(session, raw, preview(session, raw, filename), filename)


@pytest.mark.parametrize("opaque", [False, True])
def test_other_account_unknown_money_or_opaque_section_cannot_be_attested_away(database, opaque):
    with database.session_factory() as session:
        other = other_account(session, included=False)
        intent = start(session)
        add_other_source(session, other, opaque=opaque)
        plan = preview_historical_portfolio_flow(session, attest(session, intent))
        assert not plan["can_apply"]
        assert "unresolved_dated_money_semantics" in plan["blockers"]
        if opaque:
            assert any("unsupported" in b for b in plan["blockers"])
        assert plan["evidence"]["core"]["boundary_amount_kopecks"] == 1234


def legacy(session, account_id, *, day=DAY, link=None, amount=1234, direction="withdrawal"):
    month = session.scalar(select(ReportingMonth))
    if month is None:
        month = ReportingMonth(
            year=2030,
            month=1,
            period_start=date(2030, 1, 1),
            period_end=date(2030, 1, 31),
            snapshot_date=date(2030, 1, 31),
        )
        session.add(month)
        session.flush()
    row = ExternalFlow(
        reporting_month_id=month.id,
        account_id=account_id,
        event_date=day,
        boundary_amount_kopecks=amount,
        direction=direction,
        kind="external_" + direction,
        transfer_link_id=link.id if link else None,
        source="synthetic",
    )
    session.add(row)
    session.commit()
    return row


@pytest.mark.parametrize(
    "case",
    [
        "one_leg",
        "resolved",
        "asynchronous",
        "transit",
        "unresolved_outside_range",
        "unequal",
        "destination_exceeds",
    ],
)
def test_legacy_transfer_refusal_full_counterpart_no_reconciliation_or_residual(database, case):
    with database.session_factory() as session:
        other = other_account(session, included=case != "one_leg")
        intent = start(session)
        link = ExternalTransferLink(
            transfer_key="synthetic",
            status="resolved"
            if case not in ("one_leg", "unresolved_outside_range")
            else "unresolved",
        )
        session.add(link)
        session.commit()
        origin = date(2029, 12, 1) if case in ("transit", "unresolved_outside_range") else DAY
        legacy(session, other.id, day=origin, link=link)
        if case not in ("one_leg", "unresolved_outside_range"):
            arrival = date(2030, 3, 1) if case in ("asynchronous", "transit") else DAY
            legacy(
                session,
                other.id,
                day=arrival,
                link=link,
                amount=1233
                if case == "unequal"
                else 1235
                if case == "destination_exceeds"
                else 1234,
                direction="contribution",
            )
        session.add(
            ExternalTransferReconciliationEvidence(
                transfer_link_id=link.id,
                kind="internal_fee",
                amount_kopecks=1,
                currency="RUB",
                source="synthetic",
                evidence_reference="synthetic-cost",
            )
        )
        session.commit()
        plan = preview_historical_portfolio_flow(session, attest(session, intent))
        assert "legacy_transfer_or_flow_identity_unresolved" in plan["blockers"]
        assert len(plan["evidence"]["dependencies"]["legacy_flows"]) == (
            1 if case in ("one_leg", "unresolved_outside_range") else 2
        )
        assert len(plan["evidence"]["dependencies"]["reconciliation"]) == 1
        assert (
            read_historical_portfolio_flow(session, intent.flow_id)["boundary_amount_kopecks"]
            is None
        )


def test_other_membership_a_b_a_retirement_reaffirm_and_fresh_receipt_replay(database):
    with database.session_factory() as session:
        other = other_account(session, included=False)
        intent = attest(session, start(session))
        plan = preview_historical_portfolio_flow(session, intent)
        first = accept(session, intent)
        before = read_historical_owner_flow(session, intent.flow_id)
        membership = session.scalar(
            select(AccountPerformanceScopeMembership).where(
                AccountPerformanceScopeMembership.account_id == other.id
            )
        )
        membership.include_in_returns = True
        session.commit()
        membership.include_in_returns = False
        session.commit()
        retired = read_historical_portfolio_flow(session, intent.flow_id)
        assert retired["effective_state"] == "retired" and retired["revision"] == 2
        assert read_historical_owner_flow(session, intent.flow_id) == before
        replay = apply_historical_portfolio_flow(
            session,
            intent,
            confirmation_digest=plan["confirmation_digest"],
            request_id="synthetic-portfolio",
        )
        assert replay["committed_revision_id"] == first["committed_revision_id"]
        assert replay["replayed"] and replay["readback"]["boundary_amount_kopecks"] is None
        renewed = amend(
            intent, operation="reaffirm", expected_portfolio_revision=2, roster=None, outside=None
        )
        result = accept(session, attest(session, renewed), "synthetic-renew")
        assert result["readback"]["effective_state"] == "accepted"
        assert result["readback"]["revision"] == 3


@pytest.mark.parametrize(
    "case", ["new_account", "mapping", "source", "account_revoke", "coverage", "legacy"]
)
def test_sanctioned_dependency_writers_retire_transactionally(database, case):
    with database.session_factory() as session:
        other = other_account(session)
        intent = attest(session, start(session))
        accept(session, intent)
        if case == "new_account":
            other_account(session)
        elif case == "mapping":
            mapping = session.scalar(
                select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
            )
            revoke_mapping(session, mapping.id)
        elif case == "source":
            source(session, stamp="11")
        elif case == "account_revoke":
            account = read_historical_owner_flow(session, intent.flow_id)
            from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent

            revoke = OwnerFlowIntent(
                operation="revoke",
                flow_id=intent.flow_id,
                expected_revision=account["revision"],
                reason_code="evidence_disputed",
            )
            p = preview_historical_owner_flow(session, revoke)
            apply_historical_owner_flow(
                session,
                revoke,
                confirmation_digest=p["confirmation_digest"],
                request_id="account-revoke",
            )
        elif case == "coverage":
            session.add(
                CashBoundaryCoverage(
                    account_id=other.id,
                    covered_from=DAY,
                    covered_to=date(2030, 1, 18),
                    coverage_state="unknown",
                    provenance_kind="synthetic",
                )
            )
            session.commit()
        else:
            legacy(session, other.id)
        readback = read_historical_portfolio_flow(session, intent.flow_id)
        assert (
            readback["effective_state"] == "retired" and readback["boundary_amount_kopecks"] is None
        )


def test_get_detects_bypass_without_mutation_and_revoke_with_broken_support(database):
    with database.session_factory() as session:
        other = other_account(session)
        intent = attest(session, start(session))
        accept(session, intent)
        session.execute(
            text(
                "UPDATE account_performance_scope_memberships SET include_in_returns=1 WHERE account_id=:id"
            ),
            {"id": other.id},
        )
        session.commit()
        readback = read_historical_portfolio_flow(session, intent.flow_id)
        assert readback["effective_state"] == "invalidated"
        assert readback["revision"] == 1 and readback["boundary_amount_kopecks"] is None
        revoke = PortfolioFlowIntent(
            operation="revoke",
            flow_id=intent.flow_id,
            expected_flow_revision=1,
            expected_portfolio_revision=1,
            reason_code="evidence_disputed",
        )
        revoked = accept(session, revoke, "portfolio-revoke")["readback"]
        assert revoked["effective_state"] == "revoked"
        assert revoked["account_scope"]["status"] == "authoritative"


def test_noop_receipt_conflict_stale_apply_and_rollback(database):
    with database.session_factory() as session:
        intent = attest(session, start(session))
        plan = preview_historical_portfolio_flow(session, intent)
        first = accept(session, intent)
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply_historical_portfolio_flow(
                session, intent, confirmation_digest=plan["confirmation_digest"], request_id="stale"
            )
        identical = amend(intent, expected_portfolio_revision=1)
        noop = accept(session, identical, "noop")
        assert (
            noop["result_action"] == "noop"
            and noop["committed_revision_id"] == first["committed_revision_id"]
        )
        with pytest.raises(MyBrokerError, match="idempotency_conflict"):
            apply_historical_portfolio_flow(
                session,
                identical,
                confirmation_digest=plan["confirmation_digest"],
                request_id="synthetic-portfolio",
            )
        revoke = PortfolioFlowIntent(
            operation="revoke",
            flow_id=intent.flow_id,
            expected_flow_revision=1,
            expected_portfolio_revision=1,
            reason_code="evidence_disputed",
        )
        plan = preview_historical_portfolio_flow(session, revoke)

        def fail(_session, _ctx):
            if any(isinstance(r, HistoricalPortfolioFlowApply) for r in _session.new):
                raise RuntimeError("synthetic injected receipt failure")

        event.listen(session, "after_flush", fail)
        try:
            with pytest.raises(RuntimeError, match="injected"):
                apply_historical_portfolio_flow(
                    session,
                    revoke,
                    confirmation_digest=plan["confirmation_digest"],
                    request_id="failure",
                )
        finally:
            event.remove(session, "after_flush", fail)
        assert count(session, HistoricalPortfolioFlowRevision) == 1
        assert count(session, HistoricalPortfolioFlowApply) == 2
        assert (
            read_historical_portfolio_flow(session, intent.flow_id)["effective_state"] == "accepted"
        )


def test_concurrent_same_receipt_serialized_one_revision(database):
    with database.session_factory() as session:
        intent = attest(session, start(session))
        plan = preview_historical_portfolio_flow(session, intent)

    def execute():
        with database.session_factory() as session:
            return apply_historical_portfolio_flow(
                session,
                intent,
                confirmation_digest=plan["confirmation_digest"],
                request_id="concurrent",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute(), range(2)))
    assert sorted(r["replayed"] for r in results) == [False, True]
    assert len({r["committed_revision_id"] for r in results}) == 1
    with database.session_factory() as session:
        assert (
            count(session, HistoricalPortfolioFlowRevision)
            == count(session, HistoricalPortfolioFlowApply)
            == 1
        )


def test_closed_overlap_independent_authority_close_does_not_restore(database):
    with database.session_factory() as session:
        intent = attest(session, start(session))
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
        accept(session, intent)
        assert month.status == "closed" and count(session, ExternalFlow) == 0
        revoke = PortfolioFlowIntent(
            operation="revoke",
            flow_id=intent.flow_id,
            expected_flow_revision=1,
            expected_portfolio_revision=1,
            reason_code="attestation_withdrawn",
        )
        accept(session, revoke, "revoke")
        month.status = "draft"
        session.commit()
        month.status = "closed"
        session.commit()
        assert (
            read_historical_portfolio_flow(session, intent.flow_id)["effective_state"] == "revoked"
        )


def test_http_preview_apply_get_strict_financial_payload_and_default_claims(database):
    with database.session_factory() as session:
        intent = attest(session, start(session))
    app = create_app(database=database)
    client = TestClient(app)
    data = intent.model_dump(mode="json")
    inspected = client.post("/api/historical-portfolio-flows/preview", json=data)
    assert inspected.status_code == 200 and inspected.json()["can_apply"]
    result = client.post(
        "/api/historical-portfolio-flows/apply",
        json={
            **data,
            "request_id": "api",
            "confirmation_digest": inspected.json()["confirmation_digest"],
        },
    )
    assert result.status_code == 200, result.text
    assert (
        client.get("/api/historical-portfolio-flows/" + intent.flow_id).json()
        == result.json()["readback"]
    )
    assert (
        client.post(
            "/api/historical-portfolio-flows/preview",
            json={**data, "boundary_amount_kopecks": 1234},
        ).status_code
        == 422
    )
    assert client.get("/api/historical-portfolio-flows/missing").status_code == 404
    data["outside"]["not_routed_as_tracked_account_transfer"] = "true"
    with pytest.raises(ValidationError):
        PortfolioFlowIntent.model_validate(data)


def test_migration_append_only_empty_and_nonempty_loss_guard(tmp_path):
    import sqlite3

    from _migration_helpers import run_alembic

    path = tmp_path / "synthetic-portfolio-migration.db"
    assert run_alembic(path, "upgrade", "0052_source_cash_coverage").returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    tables = ("historical_portfolio_flow_revisions", "historical_portfolio_flow_applies")
    with sqlite3.connect(path) as connection:
        for table in (*tables, "reporting_months", "external_flows"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    assert run_alembic(path, "downgrade", "0052_source_cash_coverage").returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO accounts(id,name,account_type) VALUES(1,'Synthetic','brokerage')"
        )
        connection.execute(
            "INSERT INTO historical_owner_flows VALUES('synthetic',1,'2030-01-17','RUB','12.34','contribution',1234)"
        )
        connection.execute(
            "INSERT INTO historical_portfolio_flow_revisions VALUES(1,'synthetic',1,NULL,'accept','accepted','{}',?,NULL,'2030-02-01')",
            ("a" * 64,),
        )
        connection.execute(
            "INSERT INTO historical_portfolio_flow_applies VALUES(1,'synthetic',?,?,'synthetic',1,'accepted','2030-02-01')",
            ("b" * 64, "c" * 64),
        )
        for table in tables:
            for statement in (f"UPDATE {table} SET id=id", f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                    connection.execute(statement)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute(
                "INSERT INTO historical_portfolio_flow_revisions VALUES(2,'synthetic',1,NULL,'accept','accepted','{}',?,NULL,'2030-02-01')",
                ("a" * 64,),
            )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    result = run_alembic(path, "downgrade", "0052_source_cash_coverage")
    assert (
        result.returncode != 0 and "cannot discard historical portfolio acceptance" in result.stderr
    )


@pytest.fixture
def migrated_database(tmp_path):
    from _migration_helpers import run_alembic
    from test_statement_import_mybroker import ISIN

    from hermes_finance.database import create_database
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.instruments import create_instrument

    path = tmp_path / "synthetic-migrated-portfolio.db"
    migrated = run_alembic(path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    db = create_database(path)
    with db.session_factory() as session:
        account = create_account(session, name="Synthetic", account_type="brokerage")
        instrument = create_instrument(
            session, name="Synthetic", instrument_type="stock", isin=ISIN
        )
        for alias in ("1234567", ACCOUNT):
            confirm_mapping(
                session,
                provider=PROVIDER,
                subject_kind="account",
                provider_identity=alias,
                hermes_target_id=account.id,
            )
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="instrument",
            provider_identity=ISIN,
            hermes_target_id=instrument.id,
            observed_isin=ISIN,
        )
    yield db
    db.engine.dispose()


def test_migrated_sql_aba_never_revives_noop_writes_not_changes(migrated_database):
    from hermes_finance.persistence import HistoricalPortfolioDependencyChange

    with migrated_database.session_factory() as session:
        other = other_account(session)
        intent = attest(session, start(session))
        accept(session, intent)
        changes = count(session, HistoricalPortfolioDependencyChange)
        session.execute(
            text(
                "UPDATE account_performance_scope_memberships SET include_in_returns=include_in_returns"
            )
        )
        session.commit()
        assert count(session, HistoricalPortfolioDependencyChange) == changes
        assert (
            read_historical_portfolio_flow(session, intent.flow_id)["effective_state"] == "accepted"
        )
        for include in (1, 0):
            session.execute(
                text(
                    "UPDATE account_performance_scope_memberships SET include_in_returns=:include WHERE account_id=:id"
                ),
                {"include": include, "id": other.id},
            )
            session.commit()
        before = count(session, HistoricalPortfolioFlowRevision)
        invalid = read_historical_portfolio_flow(session, intent.flow_id)
        assert invalid["effective_state"] == "invalidated"
        assert invalid["boundary_amount_kopecks"] is None
        assert count(session, HistoricalPortfolioFlowRevision) == before == 1
        renewed = amend(
            intent, operation="reaffirm", expected_portfolio_revision=1, roster=None, outside=None
        )
        result = accept(session, attest(session, renewed), "sql-renew")
        assert result["readback"]["effective_state"] == "accepted"
        event_row = session.scalar(select(HistoricalPortfolioDependencyChange))
        assert set(event_row.__table__.columns.keys()) == {
            "id",
            "table_name",
            "row_id",
            "account_id",
            "flow_id",
            "mapping_kind",
            "covered_from",
            "covered_to",
        }
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError, match="append-only"):
            session.execute(text("DELETE FROM historical_portfolio_dependency_changes"))
        session.rollback()


def test_migrated_sanctioned_writer_atomic_retirement_and_backup_roundtrip(migrated_database):
    from hermes_finance.services.backups import create_backup, restore_backup

    db = migrated_database
    with db.session_factory() as session:
        other = other_account(session)
        intent = attest(session, start(session))
        accept(session, intent)
        membership = session.scalar(
            select(AccountPerformanceScopeMembership).where(
                AccountPerformanceScopeMembership.account_id == other.id
            )
        )
        membership.include_in_returns = True
        session.flush()
        session.rollback()
        assert (
            read_historical_portfolio_flow(session, intent.flow_id)["effective_state"] == "accepted"
        )
        membership = session.get(AccountPerformanceScopeMembership, membership.id)
        membership.include_in_returns = True
        session.commit()
        retired = read_historical_portfolio_flow(session, intent.flow_id)
        assert retired["revision"] == 2 and retired["effective_state"] == "retired"
    backup = create_backup(db)
    with db.session_factory() as session:
        renewed = amend(
            intent, operation="reaffirm", expected_portfolio_revision=2, roster=None, outside=None
        )
        accept(session, attest(session, renewed), "before-restore")
    restore_backup(db, backup.id)
    with db.session_factory() as session:
        assert read_historical_portfolio_flow(session, intent.flow_id) == retired
        assert count(session, HistoricalPortfolioFlowApply) == 1


def test_clean_distinct_same_day_flows_not_paired_or_netted(database):
    from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent

    with database.session_factory() as session:
        intent = start(session, extra_amounts=("-22.46",))
        first = read_historical_owner_flow(session, intent.flow_id)
        seed = first["evidence"]["intent"]["seed"]
        second_intent = OwnerFlowIntent(
            account_id=first["core"]["account_id"], seed={**seed, "ordinal": 1}
        )
        second = account_accept(
            session, account_attest(session, second_intent), "second-account-event"
        )["readback"]
        result = accept(session, attest(session, intent))["readback"]
        assert result["boundary_amount_kopecks"] == 1234
        second_portfolio = PortfolioFlowIntent(
            flow_id=second["flow_id"], expected_flow_revision=1, expected_portfolio_revision=0
        )
        second_result = accept(
            session, attest(session, second_portfolio), "second-portfolio-event"
        )["readback"]
        assert second_result["boundary_amount_kopecks"] == 2246
        assert (
            count(session, HistoricalOwnerFlow)
            == count(session, HistoricalOwnerFlowOccurrence)
            == count(session, HistoricalPortfolioFlowRevision)
            == 2
        )
        assert result["flow_id"] != second_result["flow_id"]


def test_unrelated_source_interval_current_flags_no_retirement(migrated_database):
    db = migrated_database
    with db.session_factory() as session:
        intent = attest(session, start(session))
        accept(session, intent)
        account_id = read_historical_owner_flow(session, intent.flow_id)["core"]["account_id"]
        raw = xml(stamp="11", cash_day="2030-02-17", opaque=True)
        filename = FILENAME.replace("01.01.30-31.01.30", "01.02.30-28.02.30")
        apply(session, raw, preview(session, raw, filename), filename)
        account = session.get(Account, account_id)
        account.include_in_returns = False
        account.status = "closed"
        session.commit()
        assert (
            read_historical_portfolio_flow(session, intent.flow_id)["effective_state"] == "accepted"
        )


def test_source_membership_gap_and_equal_overlaps_cannot_supply_not_in_scope(database):
    with database.session_factory() as session:
        intent = start(session)
        membership = session.scalar(select(AccountPerformanceScopeMembership))
        membership.effective_from = date(2030, 1, 18)
        membership.effective_to = None
        session.commit()
        assert (
            read_historical_portfolio_flow(session, intent.flow_id)["portfolio_scope"]["status"]
            == "unknown"
        )
        membership.effective_from = date(2030, 1, 1)
        membership.include_in_returns = False
        session.add(
            AccountPerformanceScopeMembership(
                account_id=membership.account_id, effective_from=DAY, include_in_returns=False
            )
        )
        session.commit()
        assert (
            read_historical_portfolio_flow(session, intent.flow_id)["portfolio_scope"]["status"]
            == "unknown"
        )


@pytest.mark.parametrize("case", ["malformed_date", "erased_opaque_blocker"])
def test_fresh_review_cannot_scope_away_malformed_or_opaque_source_inventory(database, case):
    with database.session_factory() as session:
        other = other_account(session)
        intent = start(session)
        imported = add_other_source(
            session, other, opaque=case == "erased_opaque_blocker", cash_day="2030-01-15"
        )
        row = session.get(MyBrokerImport, imported["import_id"])
        document = json.loads(row.normalized_json)
        if case == "malformed_date":
            document["money"][0]["date"] = "unknown"
        else:
            document["syntax_blockers"] = []
        session.execute(
            text("UPDATE mybroker_imports SET normalized_json=:document WHERE id=:id"),
            {"document": json.dumps(document), "id": row.id},
        )
        session.commit()
        plan = preview_historical_portfolio_flow(session, attest(session, intent))
        assert not plan["can_apply"]
        assert (
            "source_envelope_invalid" if case == "malformed_date" else "4_Transfers_unsupported"
        ) in plan["blockers"]


def test_unregistered_roster_account_and_unsupported_currency_claim(database):
    with database.session_factory() as session:
        intent = start(session)
        bound = attest(session, intent)
        data = bound.model_dump(mode="json")
        data["roster"]["included_accounts_rub_confirmed"] = False
        assert (
            "included_accounts_rub_confirmed_unconfirmed"
            in preview_historical_portfolio_flow(session, PortfolioFlowIntent.model_validate(data))[
                "blockers"
            ]
        )
        data["roster"]["entries"].append(
            {
                "account_id": 9999,
                "disposition": "tracked",
                "reference": "synthetic",
                "historical_disposition_confirmed": True,
            }
        )
        assert (
            "complete_catalogue_binding_required"
            in preview_historical_portfolio_flow(session, PortfolioFlowIntent.model_validate(data))[
                "blockers"
            ]
        )


@pytest.mark.parametrize("coverage_first", [False, True])
def test_source_cash_and_portfolio_authorities_coexist(migrated_database, coverage_first):
    from test_statement_import_source_cash_coverage import certify, claims, prepared

    from hermes_finance.services.source_cash_coverage import read_source_cash_coverage

    with migrated_database.session_factory() as session:
        _, flow, raw = prepared(session)
        intent = PortfolioFlowIntent(
            flow_id=flow["flow_id"],
            expected_flow_revision=flow["revision"],
            expected_portfolio_revision=0,
        )
        if coverage_first:
            coverage = certify(session, claims(session, raw))["readback"]
        portfolio = accept(session, attest(session, intent))["readback"]
        if not coverage_first:
            coverage = certify(session, claims(session, raw))["readback"]
        assert read_historical_portfolio_flow(session, flow["flow_id"]) == portfolio
        assert portfolio["effective_state"] == "accepted"
        assert portfolio["cash_coverage"] == "unknown"
        assert (
            read_source_cash_coverage(session, coverage["coverage_id"])["coverage_state"]
            == "complete"
        )
        assert read_historical_owner_flow(session, flow["flow_id"])["effective_state"] == "accepted"
        from hermes_finance.domain.source_cash_coverage import SourceCashIntent

        revoke = SourceCashIntent(
            operation="revoke",
            coverage_id=coverage["coverage_id"],
            expected_revision=coverage["revision"],
            reason_code="attestation_withdrawn",
        )
        withdrawn = certify(session, revoke, request="coverage-withdrawal")["readback"]
        assert withdrawn["coverage_state"] == "unknown"
        assert read_historical_portfolio_flow(session, flow["flow_id"]) == portfolio
        assert count(session, HistoricalPortfolioFlowRevision) == 1
        assert count(session, ReportingMonth) == count(session, InvestmentCashFlow) == 0


def test_source_cash_does_not_override_missing_roster_or_transfer(migrated_database):
    from test_statement_import_source_cash_coverage import certify, claims, prepared

    with migrated_database.session_factory() as session:
        _, flow, raw = prepared(session)
        certify(session, claims(session, raw))
        intent = PortfolioFlowIntent(
            flow_id=flow["flow_id"],
            expected_flow_revision=flow["revision"],
            expected_portfolio_revision=0,
        )
        missing = preview_historical_portfolio_flow(session, intent)
        assert not missing["can_apply"]
        assert "dated_roster_claims_missing" in missing["blockers"]
        accept(session, attest(session, intent))
        legacy(session, raw.account_id)
        view = read_historical_portfolio_flow(session, flow["flow_id"])
        assert view["effective_state"] != "accepted"
        assert "legacy_transfer_or_flow_identity_unresolved" in view["blockers"]


def test_source_cash_projection_sql_legacy_transition_is_fail_closed(migrated_database):
    from test_statement_import_source_cash_coverage import certify, claims, prepared

    with migrated_database.session_factory() as session:
        _, flow, raw = prepared(session)
        coverage = certify(session, claims(session, raw))["readback"]
        intent = PortfolioFlowIntent(
            flow_id=flow["flow_id"],
            expected_flow_revision=flow["revision"],
            expected_portfolio_revision=0,
        )
        accept(session, attest(session, intent))
        session.execute(
            text(
                "UPDATE cash_boundary_coverages SET provenance_kind='owner_attestation' WHERE id=:id"
            ),
            {"id": coverage["coverage_id"]},
        )
        session.commit()
        view = read_historical_portfolio_flow(session, flow["flow_id"])
        assert "legacy_complete_coverage_not_source_reconciled" in view["blockers"]
        assert view["effective_state"] != "accepted"
        session.execute(
            text(
                "UPDATE cash_boundary_coverages SET provenance_kind='owner_attested_source_cash_history' WHERE id=:id"
            ),
            {"id": coverage["coverage_id"]},
        )
        session.commit()
        assert (
            read_historical_portfolio_flow(session, flow["flow_id"])["effective_state"]
            != "accepted"
        )
