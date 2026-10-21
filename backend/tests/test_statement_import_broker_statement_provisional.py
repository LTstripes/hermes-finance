"""Synthetic source-intake provisional estimate; no Owner data or financial writes."""

import json
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_statement_import_mybroker import ACCOUNT, node, repo_fixture
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import _all_month_tables, broker_month_xml
from test_statement_import_mybroker_money_candidates import CASH_IN, COUPON
from test_statement_import_source_intake import intent

from hermes_finance.domain.broker_statement_provisional import (
    ProvisionalAssumptions,
    ProvisionalCash,
    ProvisionalChoice,
    ProvisionalContext,
    ProvisionalFlow,
    ProvisionalJournal,
    ProvisionalObserved,
    ProvisionalRequirement,
    evaluate_context,
)
from hermes_finance.main import create_app
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.statement_import.mybroker import NS

PREFIX = "/api/broker-statement-provisional"
BASE = "/api/broker-months/intakes"
FILENAME_APRIL = "Брокерский 1234567 (01.04.30-30.04.30).xml"
CASH_IN_AMOUNT = "1000.00"


def april_scope(database):
    with database.session_factory() as session:
        month = create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
        return {"reporting_month_id": month.id, "account_id": 1}


def _upload(client, path, xml, field, value):
    return client.post(
        path,
        files={"file": (FILENAME_APRIL, xml, "application/xml")},
        data={field: json.dumps(value)},
    )


def save(client, xml, scope, request_id="save-1"):
    response = _upload(client, BASE, xml, "intent", {**scope, "request_id": request_id})
    assert response.status_code == 200, response.text
    ack = response.json()
    response = client.get(f"{BASE}/{ack['intake_id']}")
    assert response.status_code == 200, response.text
    return response.json()


def review(client, view, xml, requested, request_id="decision-1", *, link=False):
    response = _upload(client, f"{BASE}/{view['id']}/review-preview", xml, "intent", requested)
    assert response.status_code == 200, response.text
    plan = response.json()
    return _upload(
        client,
        f"{BASE}/{view['id']}/{'finance-link' if link else 'decisions'}",
        xml,
        "confirmation",
        {
            **requested,
            "request_id": request_id,
            "confirmation_digest": plan["confirmation_digest"],
        },
    )


def _replace_dates(value: bytes) -> bytes:
    text = value.decode("utf-8")
    for old, new in (
        ("15.01.2030", "15.04.2030"),
        ("17.01.2030", "17.04.2030"),
        ("2030-01-17T", "2030-04-15T"),
    ):
        text = text.replace(old, new)
    return text.encode("utf-8")


def _add_money(root, operation, narrative, amount, *, day="2030-04-15"):
    report = root.find("m:Trades2/m:Report", NS)
    groups = report.find("m:Tablix1/m:settlement_date_Collection", NS)
    if groups is None:
        groups = node(node(report, "Tablix1"), "settlement_date_Collection")
    group = groups.find(f"m:settlement_date[@settlement_date='{day}T00:00:00']", NS)
    if group is None:
        group = node(groups, "settlement_date", settlement_date=f"{day}T00:00:00")
    collection = group.find("m:rn_Collection", NS)
    if collection is None:
        collection = node(group, "rn_Collection")
    rn = node(collection, "rn", last_update=f"{day}T10:00:00")
    comment = node(node(rn, "oper_type", oper_type=operation), "comment", comment=narrative)
    node(comment, "Textbox11", acc_code=ACCOUNT)
    level = node(
        node(
            node(node(comment, "money_volume_begin1_Collection"), "money_volume_begin1"),
            "p_code_Collection",
        ),
        "p_code",
    )
    node(level, "p_code", volume=amount, p_code="RUB")
    return rn


def provisional_xml(
    *,
    beginning="9000.00",
    beginning_quantity="10",
    closing="10211.00",
    rub=("1000.00", "1000.00"),
    cash_in=CASH_IN_AMOUNT,
    coupon=None,
    nkd=None,
    extra_money=(),
    rub_rows=1,
    bad_closing=False,
    missing_closing=False,
    unclassified=False,
    opaque=False,
    opaque_section=False,
    pending=False,
    repo=False,
    candidate_currency="RUB",
    candidate_count=1,
):
    if repo:
        root = ET.fromstring(_replace_dates(repo_fixture()))
    else:
        root = ET.fromstring(_replace_dates(broker_month_xml(unsupported=opaque, bond=False)))
    ns = NS
    security = root.find(".//m:Details[@ISIN1]", ns)
    security.set("income_rest", beginning_quantity)
    security.set("income_volume", beginning)
    if not missing_closing:
        security.set("real_volume", "0.001" if bad_closing else closing)
    else:
        security.attrib.pop("real_volume", None)
    collection = root.find(
        "m:Positions/m:Report/m:Tablix1/m:active_type_Collection/"
        "m:active_type/m:Details_Collection",
        ns,
    )
    for row in list(collection):
        if row.get("ISIN1") is None:
            collection.remove(row)
    for index in range(rub_rows):
        values = rub if index == 0 else rub
        node(
            collection,
            "Details",
            acc_code=ACCOUNT,
            active_type="Валюта",
            active_name="RUB",
            income_rest=values[0],
            real_rest=values[1],
        )
    if unclassified:
        node(collection, "Details", acc_code=ACCOUNT)
    # Remove the fixture settlement narrative; the scenario adds explicit Money
    # observations so candidate/payout classification is intentional.
    for group in root.findall(
        "m:Trades2/m:Report/m:Tablix1/m:settlement_date_Collection/m:settlement_date",
        ns,
    ):
        collection = group.find("m:rn_Collection", ns)
        if collection is not None:
            for rn in list(collection):
                collection.remove(rn)
    for index in range(candidate_count):
        rn = _add_money(root, "Перевод", CASH_IN, cash_in)
        if candidate_currency != "RUB":
            rn.find(".//m:p_code[@volume]", ns).set("p_code", candidate_currency)
    if coupon is not None:
        _add_money(root, "Перевод", COUPON, coupon)
    if nkd is not None:
        _add_money(root, "НКД по сделке", "Synthetic NKD text without a native trade id", nkd)
    for operation, narrative, amount in extra_money:
        _add_money(root, operation, narrative, amount)
    if pending:
        # The fixture's trade is settled; add a separate pending observation with
        # the same approved shape, not an economic cash event.
        from copy import deepcopy

        trades = root.find("m:Trades/m:Report", ns)
        table = trades.find("m:Tablix3", ns)
        if table is None:
            table = node(trades, "Tablix3")
        pending_collection = table.find("m:Details2_Collection", ns)
        if pending_collection is None:
            pending_collection = node(table, "Details2_Collection")
        row = deepcopy(root.find(".//m:Details[@trade_no]", ns))
        for old, new in (
            ("trade_no", "trade_no1"),
            ("db_time", "db_time2"),
            ("qty", "qty2"),
            ("Price", "Price2"),
            ("summ_trade", "summ_trade2"),
            ("curr_calc", "curr_calc2"),
            ("acc_code", "acc_code2"),
            ("isin_reg", "isin_reg1"),
            ("save_settlement_date", "save_settlement_date3"),
            ("save_depo_settlement_date", "save_depo_settlement_date3"),
            ("settlement_time", "settlement_time2"),
            ("bank_tax", "bank_tax2"),
        ):
            row.set(new, row.get(old, ""))
            row.attrib.pop(old, None)
        row.set("trade_no1", "2000000002")
        row.set("db_time2", "15.04.2030 9:00:00")
        row.set("qty2", "1")
        row.set("Price2", "100.00")
        row.set("summ_trade2", "100.00")
        row.set("curr_calc2", "RUB")
        row.set("acc_code2", ACCOUNT)
        row.set("isin_reg1", "RU000A000000")
        row.set("save_settlement_date3", "17.04.2030")
        row.set("save_depo_settlement_date3", "17.04.2030")
        row.set("settlement_time2", "17.04.2030 10:00:00")
        row.set("bank_tax2", "0")
        row.tag = "{MyBroker}Details2"
        pending_collection.append(row)
    if opaque_section:
        report = root.find("m:Trades3/m:Report", ns)
        assert report is not None
        node(report, "Tablix1")
    return ET.tostring(root, encoding="utf-8")


def context_for(client, xml, view, *, filename=FILENAME_APRIL):
    response = client.post(
        f"{PREFIX}/context",
        files={"file": (filename, xml, "application/xml")},
        data={
            "intake_id": str(view["id"]),
            "expected_manifest_digest": view["manifest_digest"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def choices(context, *, include=True, schedule_mode=None):
    selections = []
    for requirement in context["required_assumptions"]:
        if requirement["slot"] == "candidate":
            choice = "include_as_account_inflow" if include else "exclude_from_external_schedule"
        else:
            choice = requirement["choices"][0]
        selections.append(
            {
                "requirement_id": requirement["requirement_id"],
                "source_references": requirement["source_references"],
                "choice": choice,
            }
        )
    if schedule_mode is None:
        schedule_mode = "dated" if include and context["candidates"] else "explicit_empty"
    return {
        "version": "source_intake_provisional_v2",
        "schedule_mode": schedule_mode,
        "selections": selections,
    }


def evaluate(client, context, assumptions, xml, *, filename=FILENAME_APRIL):
    return client.post(
        f"{PREFIX}/evaluate",
        files={"file": (filename, xml, "application/xml")},
        data={
            "intake_id": str(context["intake_id"]),
            "expected_manifest_digest": context["journal"]["manifest_digest"],
            "expected_context_fingerprint": context["context_fingerprint"],
            "assumptions": json.dumps(assumptions),
        },
    )


def test_domain_reference_math_and_no_annualized_override():
    j = ProvisionalJournal(
        intake_id=1,
        head_seq=2,
        manifest_digest="a" * 64,
        document_sha256="b" * 64,
        parser="mybroker-s1-v2",
        binding="hermes_account",
        finance_link_present=False,
        exceptions=(),
    )
    observed = ProvisionalObserved(
        positions_value_opening_kopecks="900000",
        cash_opening_kopecks="100000",
        total_opening_kopecks="1000000",
        positions_value_closing_kopecks="1021100",
        cash_closing_kopecks="100000",
        total_closing_kopecks="1121100",
        reported_value_change_kopecks="121100",
        positions=(),
        cash=ProvisionalCash(
            source_reference="cash",
            beginning_amount="1000",
            ending_amount="1000",
            beginning_kopecks="100000",
            ending_kopecks="100000",
        ),
    )
    candidate = ProvisionalFlow(
        source_reference="money:1:money:0:" + "c" * 64,
        event_date=date(2030, 4, 15),
        signed_amount_kopecks="100000",
        source_amount="1000",
    )
    requirements = (
        ProvisionalRequirement(
            requirement_id="native_basis",
            subject="native",
            slot="native_basis",
            source_references=("source",),
            choices=("native_totals_continuously",),
        ),
        ProvisionalRequirement(
            requirement_id="candidate:0:" + "c" * 12,
            subject="candidate",
            slot="candidate",
            source_references=(candidate.source_reference,),
            choices=(
                "include_as_account_inflow",
                "exclude_from_external_schedule",
            ),
        ),
        ProvisionalRequirement(
            requirement_id="schedule",
            subject="schedule",
            slot="schedule",
            source_references=(candidate.source_reference,),
            choices=("use_displayed_schedule",),
        ),
        ProvisionalRequirement(
            requirement_id="remaining_crossings",
            subject="remaining",
            slot="remaining_crossings",
            source_references=("source", candidate.source_reference),
            choices=("no_other_account_crossings",),
        ),
    )
    context = ProvisionalContext(
        intake_id=1,
        account_id=1,
        native_source_account=None,
        t0=date(2030, 3, 31),
        t1=date(2030, 4, 30),
        journal=j,
        observed=observed,
        candidates=(candidate,),
        known_payouts=(),
        required_assumptions=requirements,
        hard_blockers=(),
        limitations=("not actual",),
        context_fingerprint="d" * 64,
    )

    def assumption(include=True):
        selections = []
        for requirement in requirements:
            choice = requirement.choices[0]
            if requirement.slot == "candidate" and not include:
                choice = "exclude_from_external_schedule"
            selections.append(
                ProvisionalChoice(
                    requirement_id=requirement.requirement_id,
                    source_references=requirement.source_references,
                    choice=choice,
                )
            )
        return ProvisionalAssumptions(
            schedule_mode="dated" if include else "explicit_empty",
            selections=tuple(selections),
        )

    included = evaluate_context(context, assumption(True))
    assert (included.status, included.scenario_result_kopecks) == ("provisional", "21100")
    assert Decimal(included.scenario_rate_fraction).is_finite()
    assert abs(Decimal(included.scenario_rate_fraction) - Decimal("0.0201")) <= Decimal("1e-8")
    assert included.alternatives[0].scenario_result_kopecks == "121100"
    assert abs(
        Decimal(included.alternatives[0].scenario_rate_fraction) - Decimal("0.1211")
    ) <= Decimal("1e-8")
    assert included.annualized is False
    # Independent reference: 10,000 × 1.0201 + 1,000 × 1.01 = 11,211.
    assert Decimal("10000") * Decimal("1.0201") + Decimal("1000") * Decimal("1.01") == (
        Decimal("11211")
    )

    excluded = evaluate_context(context, assumption(False))
    assert (excluded.status, excluded.scenario_result_kopecks) == ("provisional", "121100")
    assert abs(Decimal(excluded.scenario_rate_fraction) - Decimal("0.1211")) <= Decimal("1e-8")

    missing = evaluate_context(context, ProvisionalAssumptions(schedule_mode=None, selections=()))
    assert (missing.status, missing.scenario_result_kopecks, missing.scenario_rate_fraction) == (
        "needs_assumptions",
        None,
        None,
    )
    assert missing.reported_value_change_kopecks == "121100"


def test_domain_loss_funding_and_withdrawal_are_period_only():
    def context(v0, v1, flow=None):
        j = ProvisionalJournal(
            intake_id=1,
            head_seq=2,
            manifest_digest="a" * 64,
            document_sha256="b" * 64,
            parser="mybroker-s1-v2",
            binding="hermes_account",
            finance_link_present=False,
            exceptions=(),
        )
        observed = ProvisionalObserved(
            positions_value_opening_kopecks=v0,
            cash_opening_kopecks="0",
            total_opening_kopecks=v0,
            positions_value_closing_kopecks=v1,
            cash_closing_kopecks="0",
            total_closing_kopecks=v1,
            reported_value_change_kopecks=str(int(v1) - int(v0)),
            positions=(),
            cash=None,
        )
        requirements = [
            ProvisionalRequirement(
                requirement_id="native_basis",
                subject="native",
                slot="native_basis",
                source_references=("source",),
                choices=("native_totals_continuously",),
            )
        ]
        candidates = ()
        if flow is not None:
            candidates = (flow,)
            requirements.append(
                ProvisionalRequirement(
                    requirement_id="candidate:0:" + "c" * 12,
                    subject="candidate",
                    slot="candidate",
                    source_references=(flow.source_reference,),
                    choices=(
                        "include_as_account_inflow",
                        "exclude_from_external_schedule",
                    ),
                )
            )
        requirements.extend(
            [
                ProvisionalRequirement(
                    requirement_id="schedule",
                    subject="schedule",
                    slot="schedule",
                    source_references=tuple(f.source_reference for f in candidates),
                    choices=("use_displayed_schedule",),
                ),
                ProvisionalRequirement(
                    requirement_id="remaining_crossings",
                    subject="remaining",
                    slot="remaining_crossings",
                    source_references=("source",) + tuple(f.source_reference for f in candidates),
                    choices=("no_other_account_crossings",),
                ),
            ]
        )
        return ProvisionalContext(
            intake_id=1,
            account_id=1,
            native_source_account=None,
            t0=date(2030, 3, 31),
            t1=date(2030, 4, 30),
            journal=j,
            observed=observed,
            candidates=candidates,
            known_payouts=(),
            required_assumptions=tuple(requirements),
            hard_blockers=(),
            limitations=("not actual",),
            context_fingerprint="d" * 64,
        )

    def assumptions(context, include=True):
        selections = []
        for requirement in context.required_assumptions:
            choice = requirement.choices[0]
            if requirement.slot == "candidate" and not include:
                choice = "exclude_from_external_schedule"
            selections.append(
                ProvisionalChoice(
                    requirement_id=requirement.requirement_id,
                    source_references=requirement.source_references,
                    choice=choice,
                )
            )
        return ProvisionalAssumptions(
            schedule_mode="dated" if context.candidates else "explicit_empty",
            selections=tuple(selections),
        )

    loss = evaluate_context(context("100000", "80000"), assumptions(context("100000", "80000")))
    assert (loss.status, loss.scenario_result_kopecks) == ("provisional", "-20000")
    assert abs(Decimal(loss.scenario_rate_fraction) - Decimal("-0.2")) <= Decimal("1e-8")

    funding_flow = ProvisionalFlow(
        source_reference="money:1:money:0:" + "e" * 64,
        event_date=date(2030, 4, 15),
        signed_amount_kopecks="50000",
        source_amount="500",
    )
    funding = evaluate_context(
        context("100000", "150000", funding_flow),
        assumptions(context("100000", "150000", funding_flow)),
    )
    assert (funding.status, funding.scenario_result_kopecks) == ("provisional", "0")
    assert abs(Decimal(funding.scenario_rate_fraction)) <= Decimal("1e-8")

    withdrawal_flow = ProvisionalFlow(
        source_reference="money:1:money:0:" + "f" * 64,
        event_date=date(2030, 4, 15),
        signed_amount_kopecks="-50000",
        source_amount="-500",
    )
    # The source reader currently recognizes only incoming candidates; the signed
    # kernel is nevertheless checked so a future supported withdrawal cannot
    # silently use the wrong investor direction.
    withdrawal = evaluate_context(
        context("100000", "50000", withdrawal_flow),
        assumptions(context("100000", "50000", withdrawal_flow)),
    )
    assert (withdrawal.status, withdrawal.scenario_result_kopecks) == ("provisional", "0")
    assert abs(Decimal(withdrawal.scenario_rate_fraction)) <= Decimal("1e-8")


def test_context_and_scenario_from_synthetic_source_intake(database):
    scope = april_scope(database)
    xml = provisional_xml(coupon="500.00", nkd="-25.00")
    app = create_app(database=database)
    client = TestClient(app)
    view = save(client, xml, scope)
    context = context_for(client, xml, view)

    assert context["kind"] == "broker_source_provisional_context_v1"
    assert context["authority"] == "provisional"
    assert context["annualized"] is False
    assert context["t0"] == "2030-03-31" and context["t1"] == "2030-04-30"
    assert context["observed"]["total_opening_kopecks"] == "1000000"
    assert context["observed"]["total_closing_kopecks"] == "1121100"
    assert context["observed"]["reported_value_change_kopecks"] == "121100"
    assert context["observed"]["positions"][0]["beginning_value"] == "9000"
    assert context["observed"]["cash"]["beginning_amount"] == "1000"
    assert len(context["candidates"]) == 1
    assert context["candidates"][0]["signed_amount_kopecks"] == "100000"
    assert len(context["known_payouts"]) == 2
    slots = [r["slot"] for r in context["required_assumptions"]]
    assert slots[:2] == ["native_basis", "candidate"]
    assert {"schedule", "remaining_crossings", "trades_money_basis"} <= set(slots)
    assert "repo_basis" not in slots
    assert "unparsed_basis" not in slots
    assert context["hard_blockers"] == []

    result = evaluate(client, context, choices(context, include=True), xml)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "provisional"
    assert body["scenario_result_kopecks"] == "21100"
    assert body["reported_value_change_kopecks"] == "121100"
    assert body["annualized"] is False
    assert body["currency"] == "RUB"
    assert body["alternatives"][0]["scenario_result_kopecks"] == "121100"
    assert any("не аннулизирован" in line for line in body["limitations"])
    assert any("НКД" in line for line in body["limitations"])

    excluded = evaluate(client, context, choices(context, include=False), xml)
    assert excluded.status_code == 200, excluded.text
    assert excluded.json()["scenario_result_kopecks"] == "121100"
    assert Decimal(excluded.json()["scenario_rate_fraction"]) != Decimal(
        body["scenario_rate_fraction"]
    )


def test_missing_assumptions_never_default_and_export_is_bound(database):
    scope = april_scope(database)
    xml = provisional_xml()
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope, request_id="save-export")
    context = context_for(client, xml, view)

    missing = evaluate(
        client,
        context,
        {**choices(context), "schedule_mode": None, "selections": []},
        xml,
    )
    assert missing.status_code == 200, missing.text
    body = missing.json()
    assert body["status"] == "needs_assumptions"
    assert body["scenario_result_kopecks"] is None
    assert body["scenario_rate_fraction"] is None
    assert body["reported_value_change_kopecks"] == "121100"

    fresh = evaluate(client, context, choices(context), xml).json()
    export = client.post(
        f"{PREFIX}/export",
        files={"file": (FILENAME_APRIL, xml, "application/xml")},
        data={
            "intake_id": str(view["id"]),
            "expected_manifest_digest": view["manifest_digest"],
            "expected_context_fingerprint": context["context_fingerprint"],
            "assumptions": json.dumps(choices(context)),
            "expected_result_fingerprint": fresh["result_fingerprint"],
        },
    )
    assert export.status_code == 200, export.text
    exported = export.json()
    assert exported["kind"] == "broker_source_provisional_result_v1"
    assert exported["result_fingerprint"] == fresh["result_fingerprint"]
    assert exported["context"]["context_fingerprint"] == context["context_fingerprint"]
    assert export.headers["cache-control"] == "no-store"


def test_endpoint_gaps_block_percentage_but_keep_defined_observed_values(database):
    scope = april_scope(database)
    for index, xml in enumerate(
        (
            provisional_xml(missing_closing=True),
            provisional_xml(bad_closing=True),
            provisional_xml(unclassified=True),
        )
    ):
        client = TestClient(create_app(database=database))
        view = save(client, xml, scope, request_id=f"save-gap-{index}")
        context = context_for(client, xml, view)
        assert (
            "provisional_endpoint_value_unavailable" in context["hard_blockers"]
            or "provisional_endpoint_value_invalid" in context["hard_blockers"]
            or "position_row_unclassified" in context["hard_blockers"]
        )
        assert context["observed"]["reported_value_change_kopecks"] is None
        assert context["observed"]["total_opening_kopecks"] is None
        assert context["observed"]["total_closing_kopecks"] is None
        result = evaluate(client, context, choices(context), xml)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "blocked"
        assert result.json()["scenario_result_kopecks"] is None
        assert result.json()["scenario_rate_fraction"] is None


def test_repo_opaque_and_pending_are_named_assumptions(database):
    scope = april_scope(database)
    xml = provisional_xml(repo=True, opaque_section=True, pending=True)
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope, request_id="save-repo")
    context = context_for(client, xml, view)
    assert context["journal"]["exceptions"]
    assert "repo_basis" in {r["slot"] for r in context["required_assumptions"]}
    assert "unparsed_basis" in {r["slot"] for r in context["required_assumptions"]}
    assert any("REPO" in line for line in context["limitations"])
    assert any("opaque" in line for line in context["limitations"])
    result = evaluate(client, context, choices(context), xml)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "provisional"
    assert "native_totals_include_REPO_as_reported" in [
        s["choice"] for s in result.json()["assumptions"]["selections"]
    ]


def test_stale_manifest_original_and_context_are_refused(database):
    scope = april_scope(database)
    xml = provisional_xml()
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope, request_id="save-stale")
    context = context_for(client, xml, view)
    stale = client.post(
        f"{PREFIX}/context",
        files={"file": (FILENAME_APRIL, xml, "application/xml")},
        data={"intake_id": str(view["id"]), "expected_manifest_digest": "0" * 64},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "provisional_manifest_stale"
    changed = provisional_xml(closing="10212.00")
    mismatch = client.post(
        f"{PREFIX}/context",
        files={"file": (FILENAME_APRIL, changed, "application/xml")},
        data={"intake_id": str(view["id"]), "expected_manifest_digest": view["manifest_digest"]},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "provisional_original_mismatch"
    # A journal decision changes the current head and exceptions, so an old
    # context fingerprint cannot be used to calculate a number.
    review(client, view, xml, intent(view, overrides=[]), "decision-stale")
    current = client.get(f"/api/broker-months/intakes/{view['id']}").json()
    assert current["head_seq"] != view["head_seq"]
    result = evaluate(client, context, choices(context), xml)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "provisional_context_stale"


def test_capacity_invalid_candidate_and_zero_writes(database):
    scope = april_scope(database)
    xml = provisional_xml(candidate_count=17)
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope, request_id="save-capacity")
    before = _all_month_tables(database)
    context = context_for(client, xml, view)
    assert "provisional_candidate_capacity_exceeded" in context["hard_blockers"]
    assert len(context["candidates"]) == 17
    result = evaluate(client, context, choices(context), xml)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "blocked"
    assert _all_month_tables(database) == before


def test_zero_quantity_with_value_and_alias_remap_block_totals(database):
    scope = april_scope(database)
    xml = provisional_xml(beginning_quantity="0")
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope, request_id="save-quantity")
    context = context_for(client, xml, view)
    assert "provisional_quantity_value_conflict" in context["hard_blockers"]
    assert context["observed"]["reported_value_change_kopecks"] is None
    assert evaluate(client, context, choices(context), xml).json()["status"] == "blocked"

    from hermes_finance.persistence import BrokerIdentityMapping
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.broker_identity_mappings import (
        confirm_mapping,
        revoke_mapping,
    )
    from hermes_finance.statement_import.mybroker import PROVIDER

    alias_xml = provisional_xml()
    alias_view = save(client, alias_xml, scope, request_id="save-alias")
    with database.session_factory() as session:
        other = create_account(session, name="Synthetic other account", account_type="brokerage")
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(
                BrokerIdentityMapping.provider == PROVIDER,
                BrokerIdentityMapping.subject_kind == "account",
                BrokerIdentityMapping.provider_identity == ACCOUNT,
                BrokerIdentityMapping.status == "effective",
            )
        )
        mapping_id = mapping.id
    with database.session_factory() as session:
        revoke_mapping(session, mapping_id)
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="account",
            provider_identity=ACCOUNT,
            hermes_target_id=other.id,
        )
    context = context_for(client, alias_xml, alias_view)
    assert "provisional_multiple_source_accounts" in context["hard_blockers"]
    assert context["observed"]["reported_value_change_kopecks"] is None
    assert evaluate(client, context, choices(context), alias_xml).json()["status"] == "blocked"


def test_non_rub_and_ambiguous_cash_are_blocked(database):
    scope = april_scope(database)
    xml = provisional_xml(candidate_currency="USD", rub_rows=2)
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope, request_id="save-usd")
    context = context_for(client, xml, view)
    assert "provisional_candidate_currency_unsupported" in context["hard_blockers"]
    assert "provisional_rub_cash_ambiguous" in context["hard_blockers"]
    assert context["observed"]["reported_value_change_kopecks"] is None
    assert evaluate(client, context, choices(context), xml).json()["status"] == "blocked"


def test_api_fields_and_missing_intake(database):
    scope = april_scope(database)
    xml = provisional_xml()
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope, request_id="save-fields")
    context = context_for(client, xml, view)
    extra = client.post(
        f"{PREFIX}/context",
        files={"file": (FILENAME_APRIL, xml, "application/xml")},
        data={
            "intake_id": str(view["id"]),
            "expected_manifest_digest": view["manifest_digest"],
            "account_id": "1",
        },
    )
    assert extra.status_code == 422
    missing = client.post(
        f"{PREFIX}/context",
        files={"file": (FILENAME_APRIL, xml, "application/xml")},
        data={"intake_id": "999999", "expected_manifest_digest": view["manifest_digest"]},
    )
    assert missing.status_code == 404
    query = client.post(
        f"{PREFIX}/context?account_id=1",
        files={"file": (FILENAME_APRIL, xml, "application/xml")},
        data={"intake_id": str(view["id"]), "expected_manifest_digest": view["manifest_digest"]},
    )
    assert query.status_code == 422
    wrong_refs = choices(context)
    wrong_refs["selections"][0]["source_references"] = ["wrong"]
    bad = evaluate(client, context, wrong_refs, xml)
    assert bad.status_code == 200, bad.text
    assert bad.json()["status"] == "blocked"
    assert "provisional_assumption_membership_invalid" in bad.json()["reason_codes"]


def _free_database(tmp_path):
    from hermes_finance.database import create_database
    from hermes_finance.persistence import Base

    database = create_database(tmp_path / "unbound-provisional.db")
    Base.metadata.create_all(database.engine)
    return database


def _finite_tables(database):
    from hermes_finance.persistence import (
        Account,
        BrokerIdentityMapping,
        BrokerMonthApply,
        CashBalance,
        Instrument,
        MyBrokerImport,
        PositionSnapshot,
        ReportingMonth,
    )

    models = (
        Account,
        Instrument,
        ReportingMonth,
        BrokerIdentityMapping,
        MyBrokerImport,
        BrokerMonthApply,
        PositionSnapshot,
        CashBalance,
    )
    with database.session_factory() as session:
        return {
            model.__name__: session.scalar(select(func.count()).select_from(model))
            for model in models
        }


def test_unbound_single_native_scope_yields_hypothetical_return_without_metadata(tmp_path):
    database = _free_database(tmp_path)
    xml = provisional_xml()
    client = TestClient(create_app(database=database))
    view = save(
        client,
        xml,
        {"account_id": None, "reporting_month_id": None},
        request_id="save-unbound",
    )
    assert view["state"]["account_id"] is None
    assert view["state"]["reporting_month_id"] is None
    assert all(count == 0 for count in _finite_tables(database).values())

    context = context_for(client, xml, view)
    assert context["scope"] == "native_source"
    assert context["account_id"] is None
    assert context["native_source_account"] == ACCOUNT
    assert context["financial_authority"] == "none"
    assert context["journal"]["binding"] == "unbound"
    assert context["hard_blockers"] == []
    assert context["observed"]["total_opening_kopecks"] == "1000000"
    assert context["observed"]["total_closing_kopecks"] == "1121100"
    assert context["observed"]["reported_value_change_kopecks"] == "121100"
    assert any("source-native" in line for line in context["limitations"])

    result = evaluate(client, context, choices(context), xml)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "provisional"
    assert body["scope"] == "native_source"
    assert body["account_id"] is None
    assert body["native_source_account"] == ACCOUNT
    assert body["scenario_result_kopecks"] == "21100"
    assert abs(Decimal(body["scenario_rate_fraction"]) - Decimal("0.0201")) <= Decimal("1e-8")
    exported = client.post(
        f"{PREFIX}/export",
        files={"file": (FILENAME_APRIL, xml, "application/xml")},
        data={
            "intake_id": str(view["id"]),
            "expected_manifest_digest": view["manifest_digest"],
            "expected_context_fingerprint": context["context_fingerprint"],
            "assumptions": json.dumps(choices(context)),
            "expected_result_fingerprint": body["result_fingerprint"],
        },
    )
    assert exported.status_code == 200, exported.text
    assert exported.json()["account_id"] is None
    assert all(count == 0 for count in _finite_tables(database).values())

    # ABA: a journal command changes the head, so the old context cannot be reused.
    proposal = view["proposals"][0]["isin"]
    assert (
        review(
            client,
            view,
            xml,
            intent(view, overrides=[{"isin": proposal, "currency": "USD"}]),
            "unbound-decision",
        ).status_code
        == 200
    )
    stale = evaluate(client, context, choices(context), xml)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "provisional_context_stale"
    database.engine.dispose()


def test_unbound_trade_core_account_mismatch_blocks_and_same_account_control_passes(tmp_path):
    database = _free_database(tmp_path)
    client = TestClient(create_app(database=database))

    control = provisional_xml()
    control_view = save(
        client,
        control,
        {"account_id": None, "reporting_month_id": None},
        request_id="save-core-control",
    )
    control_context = context_for(client, control, control_view)
    assert control_context["hard_blockers"] == []
    control_result = evaluate(client, control_context, choices(control_context), control)
    assert control_result.json()["scenario_result_kopecks"] == "21100"

    mixed = provisional_xml()
    root = ET.fromstring(mixed)
    trade = root.find(".//m:Details[@trade_no]", NS)
    trade.set("acc_code", "second-synthetic-account")
    mixed = ET.tostring(root, encoding="utf-8")
    view = save(
        client,
        mixed,
        {"account_id": None, "reporting_month_id": None},
        request_id="save-core-mixed",
    )
    context = context_for(client, mixed, view)
    assert "provisional_source_scope_ambiguous" in context["hard_blockers"]
    assert context["observed"]["total_opening_kopecks"] is None
    assert context["observed"]["reported_value_change_kopecks"] is None
    assert evaluate(client, context, choices(context), mixed).json()["status"] == "blocked"
    database.engine.dispose()


def test_bound_trade_core_account_mismatch_blocks(database):
    scope = april_scope(database)
    xml = provisional_xml()
    root = ET.fromstring(xml)
    trade = root.find(".//m:Details[@trade_no]", NS)
    trade.set("acc_code", "second-synthetic-account")
    xml = ET.tostring(root, encoding="utf-8")
    client = TestClient(create_app(database=database))
    view = save(client, xml, scope, request_id="save-bound-core")
    context = context_for(client, xml, view)
    assert {
        "provisional_source_account_unproven",
        "provisional_multiple_source_accounts",
    } & set(context["hard_blockers"])
    assert context["observed"]["reported_value_change_kopecks"] is None
    assert evaluate(client, context, choices(context), xml).json()["status"] == "blocked"


def test_pending_trade_core_account_mismatch_blocks_and_same_account_control_passes(tmp_path):
    database = _free_database(tmp_path)
    client = TestClient(create_app(database=database))

    control = provisional_xml(pending=True)
    control_view = save(
        client,
        control,
        {"account_id": None, "reporting_month_id": None},
        request_id="save-pending-control",
    )
    control_context = context_for(client, control, control_view)
    assert control_context["hard_blockers"] == []
    assert any("Pending-сделки (1)" in line for line in control_context["limitations"])
    assert (
        evaluate(client, control_context, choices(control_context), control).json()[
            "scenario_result_kopecks"
        ]
        == "21100"
    )

    mixed = provisional_xml(pending=True)
    root = ET.fromstring(mixed)
    pending = root.find(".//m:Details2", NS)
    pending.set("acc_code2", "second-synthetic-account")
    mixed = ET.tostring(root, encoding="utf-8")
    view = save(
        client,
        mixed,
        {"account_id": None, "reporting_month_id": None},
        request_id="save-pending-mixed",
    )
    context = context_for(client, mixed, view)
    assert "provisional_source_scope_ambiguous" in context["hard_blockers"]
    assert context["observed"]["total_opening_kopecks"] is None
    assert context["observed"]["reported_value_change_kopecks"] is None
    assert evaluate(client, context, choices(context), mixed).json()["status"] == "blocked"
    database.engine.dispose()


def test_unbound_ambiguous_second_alias_missing_side_and_repo_are_fail_closed(tmp_path):
    database = _free_database(tmp_path)
    client = TestClient(create_app(database=database))

    ambiguous = provisional_xml()
    root = ET.fromstring(ambiguous)
    cash_rows = root.findall(".//m:rn", NS)
    assert cash_rows
    cash_rows[0].find("m:oper_type/m:comment/m:Textbox11", NS).set(
        "acc_code", "second-synthetic-account"
    )
    ambiguous = ET.tostring(root, encoding="utf-8")
    view = save(
        client,
        ambiguous,
        {"account_id": None, "reporting_month_id": None},
        request_id="save-ambiguous",
    )
    context = context_for(client, ambiguous, view)
    assert "provisional_source_scope_ambiguous" in context["hard_blockers"]
    assert context["observed"]["reported_value_change_kopecks"] is None
    assert evaluate(client, context, choices(context), ambiguous).json()["status"] == "blocked"

    missing = provisional_xml(missing_closing=True)
    missing_view = save(
        client,
        missing,
        {"account_id": None, "reporting_month_id": None},
        request_id="save-missing-side",
    )
    missing_context = context_for(client, missing, missing_view)
    assert "provisional_endpoint_value_unavailable" in missing_context["hard_blockers"]
    assert missing_context["observed"]["reported_value_change_kopecks"] is None
    assert (
        evaluate(client, missing_context, choices(missing_context), missing).json()["status"]
        == "blocked"
    )

    repo = provisional_xml(repo=True, opaque_section=True, pending=True)
    repo_view = save(
        client,
        repo,
        {"account_id": None, "reporting_month_id": None},
        request_id="save-unbound-repo",
    )
    repo_context = context_for(client, repo, repo_view)
    slots = {requirement["slot"] for requirement in repo_context["required_assumptions"]}
    assert repo_context["scope"] == "native_source"
    assert {"repo_basis", "unparsed_basis"} <= slots
    unset = evaluate(
        client,
        repo_context,
        {**choices(repo_context), "schedule_mode": None, "selections": []},
        repo,
    )
    assert unset.json()["status"] == "needs_assumptions"
    assert unset.json()["scenario_rate_fraction"] is None
    chosen = evaluate(client, repo_context, choices(repo_context), repo)
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["status"] == "provisional"
    assert "native_totals_include_REPO_as_reported" in [
        selection["choice"] for selection in chosen.json()["assumptions"]["selections"]
    ]
    database.engine.dispose()


def test_old_shape_intake_with_nominal_reattaches_without_promoting_frozen_facts(
    database, monkeypatch
):
    from hermes_finance.services.broker_statement_provisional import _matching_source
    from hermes_finance.statement_import import mybroker

    root = ET.fromstring(provisional_xml())
    root.find(".//m:Details[@ISIN1]", NS).set("nominal", "500")
    root.find(".//m:Details[@trade_no]", NS).set("nominal", "1000")
    xml = ET.tostring(root)
    client = TestClient(create_app(database=database))
    scope = april_scope(database)
    # Simulate a pre-extension parser at Save, with the same exact original bytes.
    with monkeypatch.context() as old:
        old.setattr(mybroker, "_face_value_fields", lambda *args, **kwargs: {})
        view = save(client, xml, scope)
    assert all(
        "face_value" not in row for key in ("positions", "trades") for row in view["document"][key]
    )
    before = _all_month_tables(database)
    context = context_for(client, xml, view)
    assert context["hard_blockers"] == []
    matched = _matching_source(view["document"], xml, FILENAME_APRIL)
    assert all("face_value" not in row for key in ("positions", "trades") for row in matched[key])
    assert _all_month_tables(database) == before
