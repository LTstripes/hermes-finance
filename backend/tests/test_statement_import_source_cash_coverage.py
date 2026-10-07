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
