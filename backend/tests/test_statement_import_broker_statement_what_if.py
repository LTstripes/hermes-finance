"""C1–C4: synthetic evidence only, composed real readers and immutable actual state."""

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_statement_import_broker_statement_return import (
    MID,
    T0,
    T1,
    basis,
    native_xml,
    prepared,
)
from test_statement_import_mybroker import FILENAME
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _all_month_tables,
    _broker_month_apply,
    _broker_month_preview,
)
from test_statement_import_mybroker_metadata import metadata_xml
from test_statement_import_mybroker_money_candidates import original

from hermes_finance.domain.broker_statement_return import calculate_statement_return
from hermes_finance.domain.broker_statement_what_if import (
    AssumptionRequirement,
    StatementWhatIfAssumptions,
    StatementWhatIfContext,
    WhatIfFlow,
    WhatIfObserved,
    evaluate_context,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import Account
from hermes_finance.services.reporting_months import create_reporting_month

PREFIX = "/api/broker-statement-what-if"


def choices(context, *, include=True):
    return {
        "version": "account_native_what_if_v1",
        "schedule_mode": "dated"
        if (context["fixed_schedule"] or (include and context["optional_candidate"]))
        else "explicit_empty",
        "selections": [
            {
                "requirement_id": r["requirement_id"],
                "source_references": r["source_references"],
                "choice": (
                    r["choices"][0]
                    if include or r["requirement_id"] != "candidate"
                    else "exclude_from_external_schedule"
                ),
            }
            for r in context["required_assumptions"]
        ],
    }


def paid_nkd_what_if(database, *, accepted=True, **kwargs):
    from test_statement_import_source_cash_coverage import certify, claims, paid_nkd_setup

    client, intent, originals, coverage = paid_nkd_setup(database, **kwargs)
    if accepted:
        with database.session_factory() as session:
            certify(session, claims(session, coverage))

    def call(operation="context", **fields):
        return request(
            client,
            originals[0][1],
            operation,
            request_id=intent.base_request_id,
            **fields,
        )

    return call, intent, coverage, originals


@pytest.mark.parametrize("inclusive", [False, True])
def test_paid_nkd_v4_context_evaluate_export_no_duplicate_cash(database, inclusive):
    from collections import Counter

    call, _, _, _ = paid_nkd_what_if(database, inclusive=inclusive)
    before = _all_month_tables(database)
    writes = []

    def spy(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            writes.append(statement)

    event.listen(database.engine, "before_cursor_execute", spy)
    try:
        response = call()
        assert response.status_code == 200, response.text
        context = response.json()
        assert context["hard_blockers"] == []
        actual = context["actual_result"]
        assert actual["reason_codes"] == [] and actual["rate_fraction"] is not None
        assert context["optional_candidate"] is None
        assert [f["signed_amount_kopecks"] for f in context["fixed_schedule"]] == ["5000000"]
        dispositions = context["diagnostic_inventory"]["h2"]["money_dispositions"]
        assert Counter(d["disposition"] for d in dispositions) == {
            "accepted_non_owner_coupon": 2,
            "effective_owner_flow": 1,
            "accepted_non_owner_trade_cash": 2,
            "accepted_non_owner_paid_nkd": 1,
        }
        money_basis = [r for r in context["required_assumptions"] if r["slot"] == "money_basis"]
        assert len(money_basis) == 3
        selected = choices(context)
        for missing in money_basis:
            partial = deepcopy(selected)
            partial["selections"] = [
                s for s in partial["selections"] if s["requirement_id"] != missing["requirement_id"]
            ]
            response = call("evaluate", context=context, assumptions=partial)
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["status"] == "needs_assumptions"
            assert result["scenario_rate_fraction"] is result["scenario_result_kopecks"] is None
        response = call("evaluate", context=context)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "hypothetical", result["reason_codes"]
        assert result["actual_result"] == actual
        assert abs(
            Decimal(result["scenario_rate_fraction"]) - Decimal(actual["rate_fraction"])
        ) < Decimal("1e-8")
        assert result["scenario_result_kopecks"] == str(
            int(actual["closing"]["total_value_kopecks"])
            - int(actual["opening"]["total_value_kopecks"])
            - 5000000
        )
        exported = call("export", context=context, result=result)
        assert exported.status_code == 200, exported.text
        assert exported.json() == result
        assert exported.headers["cache-control"] == "no-store"
        assert "attachment" in exported.headers["content-disposition"]
        assert writes == []
        assert _all_month_tables(database) == before
    finally:
        event.remove(database.engine, "before_cursor_execute", spy)


@pytest.mark.parametrize(
    "change",
    [
        "target",
        "missing_target",
        "absent_owner",
        "role",
        "owner_target",
        "fingerprint",
        "ordinal",
        "source",
        "duplicate",
        "pattern_gap",
    ],
)
def test_paid_nkd_v4_consumer_rejects_forged_inventory(database, monkeypatch, change):
    from dataclasses import asdict, replace

    from hermes_finance.services import broker_statement_what_if as service

    call, intent, coverage, _ = paid_nkd_what_if(database)
    with database.session_factory() as session:
        actual = service.read_statement_return(
            session, account_id=intent.account_id, request_id=intent.base_request_id
        )
        cash = service.source_cash_coverage.inventory(
            session, intent.account_id, coverage.opening_date, coverage.closing_date
        )
    context = call().json()
    ownership = deepcopy(context["diagnostic_inventory"]["ownership"])
    nkd = next(
        d for d in cash["money_dispositions"] if d["disposition"] == "accepted_non_owner_paid_nkd"
    )
    key = (nkd["import_id"], nkd["section"], nkd["ordinal"])
    owner = next(o for o in ownership if tuple(o["key"]) == key)
    if change == "target":
        nkd["trade_target_id"] = "synthetic-wrong-trade"
    elif change == "missing_target":
        nkd.pop("trade_target_id")
    elif change == "absent_owner":
        ownership.remove(owner)
    elif change == "role":
        owner["role"] = "account_funding"
    elif change == "owner_target":
        owner["target_id"] = "synthetic-wrong-trade"
    elif change == "fingerprint":
        owner["row_fingerprint"] = "0" * 64
    elif change in {"ordinal", "source"}:
        owner["key"][2 if change == "ordinal" else 0] += 1000
    elif change == "duplicate":
        ownership.append(deepcopy(owner))
    else:
        reader = service.read_money_candidates

        def with_gap(*args, **kwargs):
            result = reader(*args, **kwargs)
            return replace(
                result,
                observations=tuple(
                    replace(o, reasons=(*o.reasons, "source_pattern_unproven"))
                    if service.broker_money_ownership.key(asdict(o.occurrence)) == key
                    else o
                    for o in result.observations
                ),
            )

        monkeypatch.setattr(service, "read_money_candidates", with_gap)
    # Deliberately forge only the consumer boundary, after obtaining genuine
    # accepted material. Canonical authority itself rejects these corruptions.
    monkeypatch.setattr(service, "read_statement_return", lambda *a, **k: actual)
    monkeypatch.setattr(service.source_cash_coverage, "inventory", lambda *a, **k: cash)
    monkeypatch.setattr(service.broker_money_ownership, "owners", lambda *a, **k: ownership)
    response = call(expected_actual_fingerprint=actual.material_fingerprint)
    assert response.status_code == 200, response.text
    fresh = response.json()
    assert fresh["hard_blockers"]
    assert fresh["optional_candidate"] is None
    response = call(
        "evaluate", context=fresh, expected_actual_fingerprint=actual.material_fingerprint
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "blocked"
    assert result["scenario_rate_fraction"] is result["scenario_result_kopecks"] is None


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize(
    "change", ["revoke", "account_aba", "source_aba", "trade_revision", "fork"]
)
def test_paid_nkd_v4_changed_proof_stales_routes_no_aba_revival(database, closed, change):
    from datetime import UTC, datetime

    from test_statement_import_mybroker_endpoints import _money_apply, _trade_decide

    from hermes_finance.persistence import (
        BrokerMonthApply,
        CashBoundaryCoverage,
        ExecutedTradeRevision,
        ReportingMonth,
    )
    from hermes_finance.services.broker_money_lifecycle import next_journal_revision
    from hermes_finance.services.source_cash_coverage import read_source_cash_coverage
    from hermes_finance.statement_import.mybroker import canonical

    call, intent, _, originals = paid_nkd_what_if(database)
    context = call().json()
    assert context["hard_blockers"] == []
    result = call("evaluate", context=context).json()
    assert result["status"] == "hypothetical"
    with database.session_factory() as session:
        receipt = session.get(BrokerMonthApply, "paid-nkd")
        proof = json.loads(receipt.projection_json)
        coverage_id = session.scalar(select(CashBoundaryCoverage.id))
        if closed:
            session.get(ReportingMonth, intent.reporting_month_id).status = "closed"
            session.commit()
        if change == "account_aba":
            account = session.get(Account, intent.account_id)
            name = account.name
            account.name += " changed"
            session.commit()
            account.name = name
        elif change == "source_aba":
            from hermes_finance.persistence import MyBrokerImport

            source = session.get(MyBrokerImport, receipt.import_id)
            old = source.normalized_json
            data = json.loads(old)
            data["money"][0]["amount"] = "123.45"
            source.normalized_json = canonical(data)
            session.commit()
            source.normalized_json = old
        elif change == "trade_revision":
            previous = session.scalar(
                select(ExecutedTradeRevision).order_by(ExecutedTradeRevision.revision.desc())
            )
            fields = {
                c.name: getattr(previous, c.name)
                for c in previous.__table__.columns
                if c.name != "id"
            }
            fields.update(
                revision=previous.revision + 1,
                acceptance_state="retracted",
                accepted_at=datetime.now(UTC),
            )
            session.add(ExecutedTradeRevision(**fields))
        else:
            fields = {c.name: getattr(receipt, c.name) for c in receipt.__table__.columns}
            if change == "revoke":
                proof.update(operation="retire", journal_revision=next_journal_revision(session))
            fields.update(
                request_id="synthetic-changed-proof",
                projection_json=canonical(proof),
                accepted_at=datetime.now(UTC),
            )
            session.add(BrokerMonthApply(**fields))
        session.commit()
        assert read_source_cash_coverage(session, coverage_id)["effective_state"] == "retired"
    for operation in ("evaluate", "export"):
        response = call(
            operation, context=context, **({"result": result} if operation == "export" else {})
        )
        assert response.status_code == 409, response.text
        assert response.headers["cache-control"] == "no-store"
        assert "content-disposition" not in response.headers
    fresh = call().json()
    assert fresh["actual_result"]["rate_fraction"] is None
    assert fresh["hard_blockers"]
    assert fresh["optional_candidate"] is None
    if change == "revoke" and not closed:
        # Genuine reviewed Money reaffirmation restores the exact occurrence,
        # but cannot revive H2 acceptance or any previously bound scenario.
        with database.session_factory() as session:
            _money_apply(
                session,
                _trade_decide(session, intent, originals, operation="reaffirm"),
                originals,
                "synthetic-reaffirm",
            )
            assert read_source_cash_coverage(session, coverage_id)["effective_state"] == "retired"
        assert call("export", context=context, result=result).status_code == 409


@pytest.mark.parametrize("extra", [False, True])
def test_paid_nkd_v4_does_not_waive_legacy_v3_or_extra_money(database, monkeypatch, extra):
    from hermes_finance.services import source_cash_coverage

    # Opaque extra Money prevents A2 acceptance in the genuine fixture itself.
    call, _, _, _ = paid_nkd_what_if(database, accepted=not extra, extra=extra)
    if not extra:
        monkeypatch.setattr(source_cash_coverage, "CONTRACT", source_cash_coverage.COUPON_CONTRACT)
    response = call()
    assert response.status_code == 200, response.text
    context = response.json()
    assert context["hard_blockers"]
    result = call("evaluate", context=context).json()
    assert result["status"] == "blocked"
    assert result["scenario_rate_fraction"] is result["scenario_result_kopecks"] is None


def request(
    client,
    raw,
    operation="context",
    *,
    context=None,
    assumptions=None,
    result=None,
    filename=FILENAME,
    **changes,
):
    actual = client.get(
        "/api/broker-statement-returns",
        params={"account_id": 1, "request_id": changes.get("request_id", "synthetic-batch")},
    ).json()
    fields = {
        "account_id": "1",
        "request_id": "synthetic-batch",
        "expected_actual_fingerprint": actual["material_fingerprint"],
    }
    if context:
        fields["expected_context_fingerprint"] = context["context_fingerprint"]
        fields["assumptions"] = json.dumps(
            assumptions if assumptions is not None else choices(context)
        )
    if result:
        fields["expected_result_fingerprint"] = result["result_fingerprint"]
    fields.update(changes)
    return client.post(
        PREFIX + "/" + operation, data=fields, files={"file": (filename, raw, "application/xml")}
    )


def incoming_source(
    database,
    *,
    count=1,
    narrative="из АО Synthetic bank",
    amount="1000.00",
    safe=False,
    unsafe=False,
    cash_opening="0",
    operation="Перевод",
    bond=False,
):
    root = ET.fromstring(native_xml())
    if bond:
        from hermes_finance.persistence import Instrument

        root.find(".//{MyBroker}Details[@ISIN1]").set("active_type", "Облигации")
        with database.session_factory() as session:
            session.get(Instrument, 1).instrument_type = "bond"
            session.commit()
    table = deepcopy(
        ET.fromstring(original()).find("{MyBroker}Trades2/{MyBroker}Report/{MyBroker}Tablix1")
    )
    table.find(".//{MyBroker}settlement_date").set("settlement_date", "2030-09-15T00:00:00")
    collection = table.find(".//{MyBroker}rn_Collection")
    incoming = next(
        r
        for r in collection
        if r.find(".//{MyBroker}comment").get("comment") == "из АО Synthetic bank"
    )
    for row in list(collection):
        collection.remove(row)
    for i in range(count):
        row = deepcopy(incoming)
        row.set("last_update", "2030-09-15T10:00:00")
        row.find(".//{MyBroker}comment").set("comment", narrative)
        row.find(".//{MyBroker}oper_type").set("oper_type", operation)
        row.find(".//{MyBroker}p_code[@volume]").set("volume", amount)
        collection.append(row)
    root.find("{MyBroker}Trades2/{MyBroker}Report").append(table)
    root.find(".//{MyBroker}Details[@ISIN1]").set("real_volume", "10211")
    cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
    cash.set("income_rest", cash_opening)
    cash.set("real_rest", str(Decimal(cash_opening) + Decimal(amount) * count))
    if unsafe:
        ET.SubElement(
            root.find("{MyBroker}Trades3/{MyBroker}Report"), "{MyBroker}Tablix1", volume="5"
        )
    raw = ET.tostring(root, encoding="utf-8")
    if safe:
        raw = metadata_xml(raw)
    filename = "Брокерский 1234567 (01.09.30-30.09.30).xml"
    with database.session_factory() as session:
        month = create_reporting_month(session, year=2030, month=9, snapshot_date=date(2030, 9, 30))
        month_id = month.id
    client = TestClient(create_app(database=database))
    scope = {"account_id": 1, "reporting_month_id": month_id}
    plan = _broker_month_preview(client, scope, raw, filename)
    applied = _broker_month_apply(client, scope, plan, raw, filename=filename)
    assert applied.status_code == 200, applied.text
    return client, raw, filename


def test_real_reader_context_evaluate_export_reference_and_isolation(database):
    client, raw, filename = incoming_source(database)
    before = _all_month_tables(database)
    actual_before = client.get(
        "/api/broker-statement-returns?account_id=1&request_id=synthetic-batch"
    ).json()
    invariant_routes = [
        "/api/months",
        "/api/cash-boundary-coverages?account_id=1",
        "/api/performance/readiness?start_date=2030-08-31&end_date=2030-09-30&scope=account&account_id=1",
        "/api/performance/xirr?start_date=2030-08-31&end_date=2030-09-30&scope=account&account_id=1",
        "/api/performance/twrr?start_date=2030-08-31&end_date=2030-09-30&scope=account&account_id=1",
        "/api/months/1/close-readiness",
    ]
    invariant_before = []
    for path in invariant_routes:
        response = client.get(path)
        assert response.status_code == 200, response.text
        invariant_before.append(response.json())
    writes = []

    def spy(_conn, _cursor, statement, *_args):
        if (
            statement.lstrip()
            .upper()
            .startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"))
        ):
            writes.append(statement)

    event.listen(database.engine, "before_cursor_execute", spy)
    try:
        response = request(client, raw, filename=filename)
        assert response.status_code == 200, response.text
        context = response.json()
        assert not context["hard_blockers"], context["hard_blockers"]
        assert context["actual_result"] == actual_before
        assert context["observed"]["capital_delta_kopecks"] == "121100"
        assert context["diagnostic_inventory"]["money"]["adapter"] == "mybroker-money-candidates-v1"
        assert context["diagnostic_inventory"]["h2"]["membership"] == []
        absent = request(
            client,
            raw,
            "evaluate",
            context=context,
            assumptions={"version": "account_native_what_if_v1"},
            filename=filename,
        ).json()
        assert absent["status"] == "needs_assumptions"
        assert absent["scenario_rate_fraction"] is absent["scenario_result_kopecks"] is None
        response = request(client, raw, "evaluate", context=context, filename=filename)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "hypothetical", result["reason_codes"]
        assert result["scenario_result_kopecks"] == "21100"
        assert abs(Decimal(result["scenario_rate_fraction"]) - Decimal("0.0201")) <= Decimal("1e-8")
        assert result["actual_result"] == actual_before
        exported = request(client, raw, "export", context=context, result=result, filename=filename)
        assert exported.status_code == 200, exported.text
        assert exported.json() == result
        assert exported.headers["cache-control"] == "no-store"
        assert "attachment" in exported.headers["content-disposition"]
        excluded = request(
            client,
            raw,
            "evaluate",
            context=context,
            assumptions=choices(context, include=False),
            filename=filename,
        ).json()
        assert excluded["status"] == "hypothetical", excluded["reason_codes"]
        assert excluded["scenario_result_kopecks"] == "121100"
        assert abs(Decimal(excluded["scenario_rate_fraction"]) - Decimal("0.1211")) <= Decimal(
            "1e-8"
        )
        assert writes == []
        assert _all_month_tables(database) == before
        assert [client.get(path).json() for path in invariant_routes] == invariant_before
        assert (
            client.get(
                "/api/broker-statement-returns?account_id=1&request_id=synthetic-batch"
            ).json()
            == actual_before
        )
    finally:
        event.remove(database.engine, "before_cursor_execute", spy)


def numeric_context(v0, v1, flows):
    actual = calculate_statement_return(basis(v0, v1, flows, cash_coverage_state="unknown"))
    return StatementWhatIfContext(
        account_id=1,
        request_id="synthetic",
        t0=T0,
        t1=T1,
        observed=WhatIfObserved(
            opening=actual.opening, closing=actual.closing, capital_delta_kopecks=str(v1 - v0)
        ),
        actual_result=actual,
        diagnostic_inventory={},
        fixed_schedule=tuple(
            WhatIfFlow(
                source_reference=c.event_id,
                event_date=c.event_date,
                signed_amount_kopecks=str(c.signed_amount_kopecks),
                provenance="accepted_h2",
            )
            for c in actual.crossings
        ),
        optional_candidate=None,
        required_assumptions=(
            AssumptionRequirement(
                requirement_id="schedule",
                subject="Synthetic schedule",
                slot="schedule",
                source_references=(),
                choices=("use_displayed_schedule",),
            ),
        ),
        hard_blockers=(),
        limitations=actual.warnings,
        context_fingerprint="a" * 64,
    )


@pytest.mark.parametrize(
    "v0,v1,flows,expected",
    [
        (1000000, 1121100, ((MID, 100000),), "0.0201"),
        (1000000, 1500000, ((MID, 500000),), "0"),
        (1000000, 500000, ((MID, -500000),), "0"),
        (1000000, 1028000, (), "0.028"),
        (1000000, 800000, (), "-0.2"),
        (1000000, 1100000, ((T1, 100000),), "0"),
        (9007199254740993, 9007199254740993, (), "0"),
    ],
)
def test_c1_independent_arithmetic(v0, v1, flows, expected):
    context = numeric_context(v0, v1, flows)
    assumptions = StatementWhatIfAssumptions.model_validate_json(
        json.dumps(choices(context.model_dump(mode="json")))
    )
    result = evaluate_context(context, assumptions)
    assert result.status == "hypothetical", result.reason_codes
    assert result.scenario_result_kopecks == str(v1 - v0 - sum(amount for _, amount in flows))
    with localcontext() as ctx:
        ctx.prec = 60
        rate = Decimal(result.scenario_rate_fraction)
        assert abs(rate - Decimal(expected)) <= Decimal("1e-8")
        recomputed = Decimal(v0) / 100 * (1 + rate)
        for day, amount in flows:
            recomputed += Decimal(amount) / 100 * (1 + rate) ** (Decimal((T1 - day).days) / 30)
        assert abs(recomputed - Decimal(v1) / 100) < Decimal("0.01")
    assert not result.annualized and result.actual_result.rate_fraction is None


def test_c1_schedule_boundary_root_guards_and_strict_choices():
    for flows, v0, v1, reason, iterations in [
        (((T0, 100000),), 1000000, 1100000, "what_if_numeric_basis_invalid", 256),
        ((), 0, 0, "not_computable_xirr_no_valid_root", 256),
        (
            ((MID, -2000000), (date(2026, 9, 16), 2000000)),
            1000000,
            500000,
            "not_computable_xirr_root_ambiguity",
            256,
        ),
        (((MID, 100000),), 1000000, 1121100, "not_computable_xirr_convergence_failed", 0),
    ]:
        context = numeric_context(v0, v1, flows)
        assumptions = StatementWhatIfAssumptions.model_validate_json(
            json.dumps(choices(context.model_dump(mode="json")))
        )
        result = evaluate_context(context, assumptions, max_iterations=iterations)
        assert result.status == "blocked"
        assert reason in result.reason_codes
        assert result.scenario_rate_fraction is result.scenario_result_kopecks is None


@pytest.mark.parametrize("mutation", ["missing", "extra", "references", "duplicate", "empty"])
def test_exact_assumption_membership(database, mutation):
    client, raw = prepared(database)
    context = request(client, raw).json()
    assumptions = choices(context)
    if mutation == "missing":
        assumptions["selections"].pop()
    elif mutation == "extra":
        assumptions["selections"].append(
            {
                "requirement_id": "invented",
                "source_references": [],
                "choice": "native_totals_continuously",
            }
        )
    elif mutation == "references":
        assumptions["selections"][0]["source_references"] = []
    elif mutation == "duplicate":
        assumptions["selections"].append(assumptions["selections"][0])
    else:
        assumptions["schedule_mode"] = "dated"
    result = request(client, raw, "evaluate", context=context, assumptions=assumptions).json()
    assert result["status"] == ("needs_assumptions" if mutation == "missing" else "blocked")
    assert result["scenario_rate_fraction"] is result["scenario_result_kopecks"] is None


def test_original_mismatch_and_structural_violations(database):
    client, raw = prepared(database)
    context = request(client, raw).json()
    changed = raw.replace(b"10280", b"10281")
    response = request(
        client,
        changed,
        expected_actual_fingerprint=context["actual_result"]["material_fingerprint"],
    )
    assert response.status_code == 409 and "attachment" not in response.headers
    assert request(client, raw, endpoint="100").status_code == 422
    assert request(client, raw, account_id="2").status_code == 404
    assumptions = choices(context)
    assumptions["opening_kopecks"] = "100"
    assert (
        request(client, raw, "evaluate", context=context, assumptions=assumptions).status_code
        == 422
    )
    assert request(client, raw, "export", context=context).status_code == 422


@pytest.mark.parametrize(
    "count,narrative,blocker",
    [
        (2, "из АО Synthetic bank", "what_if_candidate_capacity_exceeded"),
        (1, "Synthetic unsupported outgoing", "what_if_money_unsupported"),
    ],
)
def test_complete_inventory_capacity_and_unsupported(database, count, narrative, blocker):
    client, raw, filename = incoming_source(database, count=count, narrative=narrative)
    context = request(client, raw, filename=filename).json()
    assert blocker in context["hard_blockers"]
    assert len(context["diagnostic_inventory"]["money"]["observations"]) == count


def test_context_absence_ownership_change_stales_evaluation_and_export(database):
    client, raw, filename = incoming_source(database)
    context = request(client, raw, filename=filename).json()
    result = request(client, raw, "evaluate", context=context, filename=filename).json()
    with database.session_factory() as session:
        session.get(Account, 1).account_type = "iis"
        session.commit()
    stale = request(
        client,
        raw,
        "export",
        context=context,
        result=result,
        filename=filename,
        expected_actual_fingerprint=context["actual_result"]["material_fingerprint"],
    )
    assert stale.status_code == 409
    assert "content-disposition" not in stale.headers
    fresh = request(client, raw, filename=filename).json()
    assert "brokerage_account_required" in fresh["hard_blockers"]


def test_safe_metadata_requires_each_named_residual_without_actual_acceptance(database):
    client, raw, filename = incoming_source(database, safe=True)
    context = request(client, raw, filename=filename).json()
    assert not context["hard_blockers"], context["hard_blockers"]
    residual = [r for r in context["required_assumptions"] if r["slot"] == "residual"]
    assert len(residual) == 2
    result = request(client, raw, "evaluate", context=context, filename=filename).json()
    assert result["status"] == "hypothetical", result["reason_codes"]
    assert result["actual_result"]["rate_fraction"] is None
    assert all(s["period_scope"] == "unknown" for s in result["actual_result"]["section_authority"])


def accept_funding(database, raw, filename):
    from test_statement_import_mybroker_endpoints import _money_apply, _money_decide

    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.persistence import ReportingMonth

    with database.session_factory() as session:
        intent = MoneyIntent(
            contract_version="broker_money_v1",
            base_request_id="synthetic-batch",
            reporting_month_id=session.scalar(select(ReportingMonth.id)),
            account_id=1,
        )
        intent = _money_decide(session, intent, [(filename, raw)], bond_id=1)
        _money_apply(session, intent, [(filename, raw)])


def test_h2_and_money_same_ownership_is_one_fixed_crossing(database):
    client, raw, filename = incoming_source(database)
    accept_funding(database, raw, filename)
    before = _all_month_tables(database)
    context = request(client, raw, filename=filename).json()
    assert not context["hard_blockers"], context["hard_blockers"]
    assert context["optional_candidate"] is None
    assert len(context["fixed_schedule"]) == 1
    assert len(context["diagnostic_inventory"]["ownership"]) == 2
    assert (
        context["diagnostic_inventory"]["h2"]["money_dispositions"][0]["disposition"]
        == "effective_owner_flow"
    )
    result = request(client, raw, "evaluate", context=context, filename=filename).json()
    assert result["status"] == "hypothetical", result["reason_codes"]
    assert result["scenario_result_kopecks"] == "21100"
    assert len(result["assumed_schedule"]) == 1
    assert _all_month_tables(database) == before


@pytest.mark.parametrize("change", ["fingerprint", "ineffective", "other_target"])
def test_permanent_owned_occurrence_cannot_become_optional(database, change):
    from hermes_finance.persistence import (
        BrokerMoneyOccurrenceOwner,
        HistoricalOwnerFlow,
    )

    client, raw, filename = incoming_source(database)
    accept_funding(database, raw, filename)
    with database.session_factory() as session:
        owner = session.scalar(select(BrokerMoneyOccurrenceOwner))
        if change == "fingerprint":
            # Deliberate synthetic storage corruption: sanctioned writers refuse
            # permanent ownership edits. The read path must still fail closed.
            session.execute(
                BrokerMoneyOccurrenceOwner.__table__.update()
                .where(BrokerMoneyOccurrenceOwner.id == owner.id)
                .values(row_fingerprint="f" * 64)
            )
        elif change == "ineffective":
            # The real lifecycle retires current proofs when account facts change.
            session.get(Account, 1).name = "Synthetic changed dependency"
        else:
            other = HistoricalOwnerFlow(
                id="synthetic-other-target",
                account_id=1,
                event_date=date(2030, 8, 1),
                currency="RUB",
                signed_source_amount="1000",
                direction="contribution",
                boundary_amount_kopecks=100000,
            )
            session.add(other)
            session.flush()
            session.execute(
                BrokerMoneyOccurrenceOwner.__table__.update()
                .where(BrokerMoneyOccurrenceOwner.id == owner.id)
                .values(historical_owner_flow_id=other.id)
            )
        session.commit()
    context = request(client, raw, filename=filename).json()
    assert context["hard_blockers"]
    assert context["optional_candidate"] is None
    result = request(client, raw, "evaluate", context=context, filename=filename).json()
    assert result["status"] == "blocked"
    assert result["scenario_rate_fraction"] is result["scenario_result_kopecks"] is None


@pytest.mark.parametrize("preserve_actual_fingerprint", [False, True])
def test_ownership_absence_stales_actual_context_and_export(
    database, monkeypatch, preserve_actual_fingerprint
):
    from hermes_finance.persistence import HistoricalOwnerFlow, HistoricalOwnerFlowOccurrence
    from hermes_finance.services import broker_statement_what_if as service

    client, raw, filename = incoming_source(database)
    context = request(client, raw, filename=filename).json()
    result = request(client, raw, "evaluate", context=context, filename=filename).json()
    occurrence = context["diagnostic_inventory"]["money"]["observations"][0]["occurrence"]
    with database.session_factory() as session:
        flow = HistoricalOwnerFlow(
            id="synthetic-ineffective-outside-period",
            account_id=1,
            event_date=date(2030, 8, 1),
            currency="RUB",
            signed_source_amount="1000",
            direction="contribution",
            boundary_amount_kopecks=100000,
        )
        session.add(flow)
        session.flush()
        session.add(HistoricalOwnerFlowOccurrence(flow_id=flow.id, **occurrence))
        session.commit()
    old_actual = context["actual_result"]["material_fingerprint"]
    binding = {}
    if preserve_actual_fingerprint:
        # Explicit composition probe: retain independent context protection even
        # if an actual reader's fingerprint omits this dependency. The real S3
        # path now binds this ownership material under #850 (the other case).
        reader = service.read_statement_return

        def frozen_fingerprint(*args, **kwargs):
            return reader(*args, **kwargs).model_copy(update={"material_fingerprint": old_actual})

        monkeypatch.setattr(service, "read_statement_return", frozen_fingerprint)
        binding = {"expected_actual_fingerprint": old_actual}
    fresh = request(client, raw, filename=filename, **binding).json()
    assert (
        fresh["actual_result"]["material_fingerprint"] == old_actual
    ) is preserve_actual_fingerprint
    assert fresh["context_fingerprint"] != context["context_fingerprint"]
    assert fresh["optional_candidate"] is None
    assert "what_if_ownership_ineffective_or_incompatible" in fresh["hard_blockers"]
    for operation in ("evaluate", "export"):
        stale = request(
            client,
            raw,
            operation,
            context=context,
            filename=filename,
            result=result if operation == "export" else None,
            **binding,
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "what_if_context_stale"
        assert stale.headers["cache-control"] == "no-store"
        assert "content-disposition" not in stale.headers
        assert "scenario_rate_fraction" not in stale.text
        if not preserve_actual_fingerprint:
            old_view = request(
                client,
                raw,
                operation,
                context=context,
                filename=filename,
                result=result if operation == "export" else None,
                expected_actual_fingerprint=old_actual,
            )
            assert old_view.status_code == 409
            assert old_view.json()["error"]["code"] == "what_if_actual_stale"
            assert old_view.headers["cache-control"] == "no-store"
            assert "content-disposition" not in old_view.headers
            assert "scenario_rate_fraction" not in old_view.text


@pytest.mark.parametrize("change", ["source", "mapping", "month", "cash", "nonfinite", "subkopeck"])
def test_bad_current_provenance_never_relabels_cached_amounts_observed(database, change):
    from hermes_finance.persistence import MyBrokerImport, ReportingMonth

    client, raw = prepared(database)
    old = request(client, raw).json()
    with database.session_factory() as session:
        source = session.scalar(select(MyBrokerImport))
        if change == "month":
            session.scalar(select(ReportingMonth)).snapshot_date = date(2030, 1, 30)
        elif change == "mapping":
            mappings = json.loads(source.mappings_json)
            mappings[0]["hermes_id"] = 999
            source.mappings_json = json.dumps(mappings)
        else:
            document = json.loads(source.normalized_json)
            if change == "cash":
                document["rub_money"] = []
            elif change == "nonfinite":
                document["positions"][0]["ending_value"] = "NaN"
            elif change == "subkopeck":
                document["positions"][0]["ending_value"] = "0.001"
            else:
                document["filename_account"] = "synthetic-wrong-account"
            source.normalized_json = json.dumps(document)
        session.commit()
    stale = request(
        client,
        raw,
        "evaluate",
        context=old,
        expected_actual_fingerprint=old["actual_result"]["material_fingerprint"],
    )
    assert stale.status_code == 409
    fresh_response = request(client, raw)
    if change in {"source", "cash", "nonfinite", "subkopeck"}:
        assert fresh_response.status_code == 409
        assert "scenario_rate_fraction" not in fresh_response.text
        return
    assert fresh_response.status_code == 200, fresh_response.text
    fresh = fresh_response.json()
    assert fresh["hard_blockers"]
    assert fresh["observed"]["opening"] is fresh["observed"]["closing"] is None
    result = request(client, raw, "evaluate", context=fresh).json()
    assert result["status"] == "blocked"


@pytest.mark.parametrize(
    "reason",
    [
        "future_new_reason",
        "settlement_principal_unresolved",
        "unparsed_source_rows",
        "legacy_cash_or_transfer_overlap",
        "coupon_target_scope_conflict",
    ],
)
def test_unmapped_actual_reason_is_hard_and_not_an_assumption(database, monkeypatch, reason):
    from hermes_finance.services import broker_statement_what_if as service

    client, raw = prepared(database)
    reader = service.read_statement_return

    def future(*args, **kwargs):
        actual = reader(*args, **kwargs)
        return actual.model_copy(update={"reason_codes": (*actual.reason_codes, reason)})

    monkeypatch.setattr(service, "read_statement_return", future)
    context = request(client, raw).json()
    assert reason in context["hard_blockers"]
    result = request(client, raw, "evaluate", context=context).json()
    assert result["status"] == "blocked"
    assert result["scenario_rate_fraction"] is result["scenario_result_kopecks"] is None
    exported = request(client, raw, "export", context=context, result=result)
    assert exported.status_code == 200 and exported.json() == result


def test_fixed_capacity_never_truncates_inventory(database, monkeypatch):
    from hermes_finance.services import broker_statement_what_if as service

    client, raw = prepared(database)
    reader = service.read_statement_return

    def many(*args, **kwargs):
        actual = reader(*args, **kwargs)
        flows = basis(flows=((MID, 1),)).crossings
        return actual.model_copy(
            update={
                "crossings": tuple(
                    flows[0].model_copy(
                        update={"event_id": f"synthetic-{i}", "event_date": date(2030, 1, 15)}
                    )
                    for i in range(129)
                )
            }
        )

    monkeypatch.setattr(service, "read_statement_return", many)
    context = request(client, raw).json()
    assert "what_if_crossing_capacity_exceeded" in context["hard_blockers"]
    assert len(context["fixed_schedule"]) == 129


def test_unsafe_nonempty_exposure_is_not_dismissible(database):
    client, raw, filename = incoming_source(database, unsafe=True)
    # The existing synthetic opaque wrapper is not the exact approved tree.
    context = request(client, raw, filename=filename).json()
    assert "what_if_unmodelled_exposure" in context["hard_blockers"]
    result = request(client, raw, "evaluate", context=context, filename=filename).json()
    assert result["status"] == "blocked"


@pytest.mark.parametrize("kind", ["coupon", "nkd", "outgoing"])
def test_recognized_money_basis_never_becomes_investor_cash(database, kind):
    from test_statement_import_mybroker_money_candidates import COUPON

    client, raw, filename = incoming_source(
        database,
        narrative=COUPON
        if kind == "coupon"
        else "Synthetic unlinked NKD"
        if kind == "nkd"
        else "Synthetic outgoing",
        amount="1000" if kind == "coupon" else "-100",
        cash_opening="1000",
        operation="НКД по сделке" if kind == "nkd" else "Перевод",
    )
    context = request(client, raw, filename=filename).json()
    if kind == "outgoing":
        assert context["hard_blockers"]
        return
    assert not context["hard_blockers"], context["hard_blockers"]
    assert context["optional_candidate"] is None
    assert len([r for r in context["required_assumptions"] if r["slot"] == "money_basis"]) == 1
    result = request(client, raw, "evaluate", context=context, filename=filename).json()
    assert result["status"] == "hypothetical", result["reason_codes"]
    assert result["assumed_schedule"] == []
    assert result["scenario_result_kopecks"] == context["observed"]["capital_delta_kopecks"]
    assert result["actual_result"]["rate_fraction"] is None


def test_new_competing_source_blocks_what_if_without_deduplicating_rows(database):
    from test_statement_import_mybroker import apply, preview

    client, raw = prepared(database)
    root = ET.fromstring(raw)
    root.find(".//{MyBroker}Details[@ISIN1]").set("active_name", "Synthetic overlapping source")
    competing = ET.tostring(root)
    with database.session_factory() as session:
        apply(session, competing, preview(session, competing))
    context = request(client, raw).json()
    assert "statement_overlapping_source" in context["hard_blockers"]
    result = request(client, raw, "evaluate", context=context).json()
    assert result["status"] == "blocked"


def test_section_head_change_without_coverage_stales_bound_export(database):
    from test_statement_import_mybroker_metadata import _section_accept, section_setup

    client, intent, raw = section_setup(database, raw=metadata_xml(native_xml()))
    context = request(client, raw, request_id="section-base").json()
    assert not context["hard_blockers"], context["hard_blockers"]
    result = request(client, raw, "evaluate", context=context, request_id="section-base").json()
    assert result["status"] == "hypothetical", result["reason_codes"]
    _section_accept(client, intent, raw)
    for operation in ("evaluate", "export"):
        response = request(
            client,
            raw,
            operation,
            context=context,
            request_id="section-base",
            result=result if operation == "export" else None,
        )
        assert response.status_code == 409
        assert "content-disposition" not in response.headers


def test_malformed_accepted_source_stays_blocked_and_no_store_on_all_routes(database):
    from hermes_finance.persistence import MyBrokerImport

    client, raw = prepared(database)
    with database.session_factory() as session:
        session.scalar(select(MyBrokerImport)).normalized_json = "not JSON"
        session.commit()
    before = _all_month_tables(database)
    response = request(client, raw)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    context = response.json()
    assert "what_if_source_inventory_invalid" in context["hard_blockers"]
    assert context["observed"]["opening"] is context["observed"]["closing"] is None
    response = request(client, raw, "evaluate", context=context)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["status"] == "blocked"
    assert result["scenario_rate_fraction"] is result["scenario_result_kopecks"] is None
    exported = request(client, raw, "export", context=context, result=result)
    assert exported.status_code == 200, exported.text
    assert exported.headers["cache-control"] == "no-store"
    assert exported.json() == result
    assert _all_month_tables(database) == before


def test_current_coupon_authority_change_without_coverage_stales_context_and_export(database):
    from test_statement_import_mybroker_money_candidates import COUPON

    from hermes_finance.persistence import CashBoundaryCoverage, InvestmentCashFlow

    client, raw, filename = incoming_source(database, narrative=COUPON, bond=True)
    accept_funding(database, raw, filename)
    context = request(client, raw, filename=filename).json()
    assert not context["hard_blockers"], context["hard_blockers"]
    assert (
        context["diagnostic_inventory"]["h2"]["money_dispositions"][0]["disposition"]
        == "accepted_non_owner_coupon"
    )
    result = request(client, raw, "evaluate", context=context, filename=filename).json()
    assert result["status"] == "hypothetical", result["reason_codes"]
    assert result["assumed_schedule"] == []
    with database.session_factory() as session:
        assert session.scalar(select(CashBoundaryCoverage.id)) is None
        payout = session.scalar(select(InvestmentCashFlow))
        # Deliberate synthetic corruption: supported writers require a reviewed
        # source revision. Fresh reads must detect altered coupon target material
        # even without a coverage row or a lifecycle retirement being appended.
        session.execute(
            InvestmentCashFlow.__table__.update()
            .where(InvestmentCashFlow.id == payout.id)
            .values(net_amount_kopecks=payout.net_amount_kopecks + 1)
        )
        session.commit()
    for operation in ("evaluate", "export"):
        response = request(
            client,
            raw,
            operation,
            context=context,
            filename=filename,
            result=result if operation == "export" else None,
        )
        assert response.status_code == 409, response.text
        assert "content-disposition" not in response.headers
        assert response.headers["cache-control"] == "no-store"
        assert "scenario_rate_fraction" not in response.text


@pytest.mark.parametrize("operation", ["context", "evaluate", "export"])
def test_malformed_multipart_and_missing_upload_are_typed_no_store(database, operation):
    client, raw = prepared(database)
    response = client.post(
        PREFIX + "/" + operation,
        content=b"malformed synthetic form",
        headers={"Content-Type": "multipart/form-data"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "what_if_request_invalid"
    assert response.headers["cache-control"] == "no-store"
    assert "content-disposition" not in response.headers
    missing = client.post(PREFIX + "/" + operation, data={"account_id": "1"})
    assert missing.status_code == 422
    assert missing.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("narrative", ["Synthetic outgoing", "из АО Synthetic bank"])
def test_real_effective_h2_withdrawal_needs_no_incoming_narrative_classifier(database, narrative):
    from test_statement_import_historical_owner_flows import accept, attest

    from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent
    from hermes_finance.persistence import MyBrokerImport

    client, raw, filename = incoming_source(
        database, narrative=narrative, amount="-1000", cash_opening="1000"
    )
    with database.session_factory() as session:
        source = session.scalar(select(MyBrokerImport))
        intent = OwnerFlowIntent(
            evidence_version="h2-a1-owner-rub-v2",
            account_id=1,
            seed={"import_id": source.id, "ordinal": 0},
        )
        flow = accept(session, attest(session, intent))["readback"]
        assert flow["effective_state"] == "accepted"
    before = _all_month_tables(database)
    context = request(client, raw, filename=filename).json()
    assert not context["hard_blockers"], context["hard_blockers"]
    assert context["optional_candidate"] is None
    assert context["fixed_schedule"][0]["signed_amount_kopecks"] == "-100000"
    assert (
        context["diagnostic_inventory"]["h2"]["money_dispositions"][0]["disposition"]
        == "effective_owner_flow"
    )
    result = request(client, raw, "evaluate", context=context, filename=filename).json()
    assert result["status"] == "hypothetical", result["reason_codes"]
    assert len(result["assumed_schedule"]) == 1
    assert result["scenario_result_kopecks"] == "21100"
    assert result["actual_result"]["rate_fraction"] is None
    assert (
        request(client, raw, "export", context=context, result=result, filename=filename).json()
        == result
    )
    assert _all_month_tables(database) == before


@pytest.mark.parametrize("warning", ["period_inferred_from_content", "filename_period_mismatch"])
@pytest.mark.parametrize("channel", ["metadata", "actual"])
def test_period_warnings_are_scoped_what_if_diagnostics(database, monkeypatch, warning, channel):
    from hermes_finance.services import broker_statement_what_if as service

    client, raw = prepared(database)
    if channel == "metadata":
        reader = service.parse_section_metadata

        def warned(*args, **kwargs):
            metadata = reader(*args, **kwargs)
            metadata["source_warnings"].append(warning)
            return metadata

        monkeypatch.setattr(service, "parse_section_metadata", warned)
    else:
        reader = service.read_statement_return

        def warned(*args, **kwargs):
            actual = reader(*args, **kwargs)
            return actual.model_copy(update={"reason_codes": (*actual.reason_codes, warning)})

        monkeypatch.setattr(service, "read_statement_return", warned)
    before = _all_month_tables(database)
    response = request(client, raw)
    assert response.status_code == 200, response.text
    context = response.json()
    inferred = warning == "period_inferred_from_content"
    assert ("source_period_inferred" in context["hard_blockers"]) == inferred
    assert (context["observed"]["opening"] is None) == inferred
    diagnostics = (
        context["diagnostic_inventory"]["metadata"]["source_warnings"]
        if channel == "metadata"
        else context["actual_result"]["reason_codes"]
    )
    assert warning in diagnostics
    result = request(client, raw, "evaluate", context=context).json()
    assert result["status"] == ("blocked" if inferred else "hypothetical"), result["reason_codes"]
    if inferred:
        assert result["scenario_rate_fraction"] is result["scenario_result_kopecks"] is None
    assert result["actual_result"] == context["actual_result"]
    assert _all_month_tables(database) == before
