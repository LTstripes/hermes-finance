from datetime import date

from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, CashBalance, ReportingMonth, SpendingCategory
from hermes_finance.services import spending_reserve as reserve


def plan(**kwargs):
    values = dict(
        start="2027-12-01",
        end="2028-05-31",
        sources=[],
        categories=[dict(id=1, estimate="38000")],
        months=[],
    )
    return reserve.Plan.model_validate({**values, **kwargs})


def rule(**patch):
    values = dict(
        id=3,
        title="Проездной",
        month="2026-10",
        source="alfa",
        category_id=1,
        operation_id=1,
        was_recurring=True,
        occurrences=[],
        mandatory=True,
        mandatory_override=None,
        repeat=True,
        period_months=12,
        next_due=date(2028, 11, 2),
        amount_kopecks=2400000,
        needs_review=False,
    )
    return {**values, **patch}


def calc(p, rules):
    return reserve.calculate(p, rules, {1: "Базовые расходы"}, None, 18000000, [])


def test_paid_pass_and_renewal_within_horizon():
    near = calc(plan(), [rule()])
    assert near["monthly"]["amount"] == "40000.00"
    assert near["coverage_months"] == "4.5"
    assert near["rules"][0]["monthly"]["amount"] == "2000.00"
    assert near["target"]["amount"] == "228000.00"
    assert near["difference"]["amount"] == "-48000.00"
    late = calc(plan(start="2028-06-01", end="2028-11-30"), [rule()])
    assert late["target"]["amount"] == "252000.00"
    assert late["calendar"][-1]["total"]["amount"] == "62000.00"


def test_uncertain_rule_and_absent_price_preserve_unknown():
    detached = calc(plan(), [rule(needs_review=True, mandatory=None)])
    assert detached["target"] is None and detached["monthly"] is None
    view = calc(plan(), [rule(next_due=None)])
    assert view["target"] is None and view["monthly"]["amount"] == "40000.00"
    optional = rule(mandatory=False, mandatory_override=False, needs_review=True)
    assert calc(plan(), [optional])["monthly"]["amount"] == "38000.00"
    assert calc(plan(), [rule(repeat=False)])["monthly"]["amount"] == "38000.00"


def test_unknown_inputs_only_affect_periods_with_possible_payments():
    horizon = plan(start="2028-01-01", end="2028-06-30")
    for candidate in (
        rule(next_due=date(2028, 11, 1), amount_kopecks=None),
        rule(next_due=date(2028, 11, 1), period_months=None),
        rule(next_due=date(2027, 11, 1), amount_kopecks=None),
    ):
        view = calc(horizon, [candidate])
        assert view["monthly"] is None and view["coverage_months"] is None
        assert view["target"]["amount"] == "228000.00"
        assert view["difference"]["amount"] == "-48000.00"
        assert all(m["total"]["amount"] == "38000.00" for m in view["calendar"])

    view = calc(horizon, [rule(next_due=date(2028, 4, 1), amount_kopecks=None)])
    assert view["target"] is None and view["difference"] is None
    assert [m["total"]["amount"] if m["total"] else None for m in view["calendar"]] == [
        "38000.00",
        "38000.00",
        "38000.00",
        None,
        "38000.00",
        "38000.00",
    ]
    assert view["calendar"][3]["payments"][0]["amount"] is None

    view = calc(horizon, [rule(next_due=date(2028, 4, 1), period_months=None)])
    assert view["target"] is None and view["monthly"] is None
    assert view["calendar"][3]["total"]["amount"] == "62000.00"
    assert view["calendar"][4]["total"] is None
    assert view["calendar"][4]["payments"] == []

    view = calc(horizon, [rule(next_due=None, period_months=None, amount_kopecks=0)])
    assert view["target"]["amount"] == "228000.00"
    assert view["monthly"]["amount"] == "38000.00"
    assert view["rules"][0]["monthly"]["amount"] == "0.00"


def test_partial_month_and_original_month_end_anchor():
    dates = list(reserve.next_dates(date(2028, 1, 31), 1, date(2028, 2, 1), date(2028, 3, 31)))
    assert dates == [date(2028, 2, 29), date(2028, 3, 31)]
    view = calc(
        plan(start="2028-02-28", end="2028-03-01", categories=[dict(id=1, estimate="3100")]), []
    )
    assert view["target"]["amount"] == "313.79"
    assert calc(plan(categories=[]), [])["target"] is None
    assert calc(plan(categories=[dict(id=1, estimate="0")]), [])["coverage_months"] is None


def test_historical_variable_amount_excludes_rule_and_uses_matching_sources(monkeypatch):
    from hermes_finance.services import spending_diary, spending_insights

    class FakeSession:
        def scalars(self, query):
            return ["test-synthetic-account"]

    def month_data(session, month):
        return dict(month=month, coverage={"full": True}, has_manual=True, unresolved=False)

    monkeypatch.setattr(spending_diary, "read_month_base", month_data)
    items = [
        dict(id=1, source="alfa", category_id=1, amount={"amount": "24000"}),
        dict(id=2, source="alfa", category_id=1, amount={"amount": "1500"}),
    ]
    for row in items:
        row.update(description="Тест", date=date(2026, 10, 2), category_name="Тестовая категория")
    monkeypatch.setattr(spending_insights, "operations", lambda s, b, limit: {"items": items})
    p = plan(categories=[dict(id=1)], months=["2026-10", "2026-11"])
    rules = [rule(month=m, source="alfa", operation_id=1) for m in p.months]
    assert reserve.historical_amounts(FakeSession(), p, rules)[1] == 150000
    canceled = [{**r, "repeat": False, "was_recurring": True} for r in rules]
    assert reserve.historical_amounts(FakeSession(), p, canceled)[1] == 150000
    notes_only = [{**r, "repeat": False, "was_recurring": False} for r in rules]
    assert reserve.historical_amounts(FakeSession(), p, notes_only)[1] == 2550000

    class DifferentAccounts:
        def __init__(self):
            self.accounts = iter([["account-a"], ["account-b"]])

        def scalars(self, query):
            return next(self.accounts)

    assert reserve.historical_amounts(DifferentAccounts(), p, rules) is None
    monkeypatch.setattr(
        spending_diary,
        "read_month_base",
        lambda s, m: {**month_data(s, m), "has_manual": m.endswith("11")},
    )
    assert reserve.historical_amounts(FakeSession(), p, rules) is None
    monkeypatch.setattr(
        spending_diary,
        "read_month_base",
        lambda s, m: {**month_data(s, m), "coverage": {"full": False}},
    )
    assert reserve.historical_amounts(FakeSession(), p, rules) is None


def test_historical_rule_payment_must_be_confirmed_and_can_be_kept_separate(monkeypatch):
    from hermes_finance.services import spending_diary, spending_insights

    class Session:
        def scalars(self, query):
            return ["test-account"]

    item = dict(
        id=55,
        source="alfa",
        category_id=1,
        category_name="Жильё",
        description="Аренда",
        date=date(2026, 11, 1),
        amount={"amount": "30000.00"},
    )
    items = [
        item,
        {
            **item,
            "category_id": 2,
            "id": 56,
            "description": "Продукты",
            "amount": {"amount": "8000.00"},
        },
    ]
    monkeypatch.setattr(
        spending_diary,
        "read_month_base",
        lambda s, m: dict(coverage={"full": True}, has_manual=True, unresolved=False),
    )
    monkeypatch.setattr(spending_insights, "operations", lambda s, b, limit: {"items": items})
    budget = plan(categories=[dict(id=1), dict(id=2)], months=["2026-11"])
    rent = rule(title="Аренда", period_months=1, next_due=date(2026, 11, 1), amount_kopecks=3000000)
    checks = []
    assert reserve.historical_amounts(Session(), budget, [rent], candidates=checks) == {2: 800000}
    assert len(checks) == 1 and (
        checks[0]["month"],
        checks[0]["source"],
        checks[0]["operation_id"],
    ) == ("2026-11", "alfa", 55)
    assert checks[0]["amount"]["amount"] == "30000.00"
    occurrence = dict(month="2026-11", source="alfa", operation_id=55, needs_review=False)
    amounts = reserve.historical_amounts(
        Session(), budget, [{**rent, "occurrences": [{**occurrence, "decision": "payment"}]}]
    )
    assert amounts == {1: 0, 2: 800000}
    projected = reserve.calculate(
        budget, [rent], {1: "Жильё", 2: "Продукты"}, amounts, 18000000, []
    )
    assert projected["monthly"]["amount"] == "38000.00"
    separate = {**rent, "occurrences": [{**occurrence, "decision": "separate"}]}
    checks = []
    assert reserve.historical_amounts(Session(), budget, [separate], candidates=checks) == {
        1: 3000000,
        2: 800000,
    }
    assert checks == []
    ambiguous = {
        **rent,
        "occurrences": [{**occurrence, "decision": "payment", "needs_review": True}],
    }
    assert reserve.historical_amounts(Session(), budget, [ambiguous]) is None
    # A dated purchase with the same source, category and price but another description is independent.
    item["description"] = "Другая услуга"
    assert reserve.historical_amounts(Session(), budget, [rent]) == {1: 3000000, 2: 800000}


def test_choosing_only_estimates_discards_hidden_history_months():
    p = plan(start="2027-01-01", end="2027-06-30", months=["2027-11"])
    assert p.months == []


def test_next_month_rent_reconciles_through_payment_card_and_reserve_api(tmp_path):
    from test_spending_diary import bank_row, csv_file

    from hermes_finance.services import spending_diary

    db = create_database(tmp_path / "rent.db")
    Base.metadata.create_all(db.engine)
    try:
        with db.session_factory() as session:
            for month, last in (("10", 31), ("11", 30)):
                day = f"01.{month}.2025"
                content = csv_file(
                    bank_row(
                        operationDate=day,
                        transactionDate=day,
                        merchant="Тестовая аренда",
                        category="Жильё",
                        amount="30000",
                    )
                )
                args = dict(
                    month=f"2025-{month}",
                    source="alfa_csv",
                    filename=f"Statement {day} - {last}.{month}.2025.csv",
                    content=content,
                )
                preview = spending_diary.preview_upload(session, **args)
                spending_diary.apply_upload(session, **args, preview_token=preview["preview_token"])
            session.commit()
        with TestClient(create_app(db)) as client:

            def operations(month):
                response = client.get("/api/spending/operations", params={"month": month})
                assert response.is_success, response.text
                return response.json()

            october = operations("2025-10")["items"][0]
            november = operations("2025-11")["items"][0]
            anchor = f"/api/spending/payment-rules/alfa/{october['id']}?month=2025-10"
            saved = client.put(
                anchor,
                json=dict(
                    token=client.get(anchor).json()["token"],
                    note="",
                    mandatory_override=True,
                    repeat=True,
                    period_months=1,
                    next_due="2025-11-01",
                    amount="30000",
                ),
            )
            assert saved.is_success, saved.text
            rule_id = saved.json()["rule"]["id"]
            budget = plan(
                start="2026-01-01",
                end="2026-06-30",
                categories=[dict(id=november["category_id"])],
                months=["2025-11"],
            )
            path = "/api/spending/reserve"
            view = client.put(
                path, json={"expected_revision": 0, "plan": budget.model_dump(mode="json")}
            )
            assert view.is_success, view.text
            assert view.json()["monthly"] is None
            [candidate] = view.json()["payment_candidates"]
            assert (candidate["operation_id"], candidate["rule_id"]) == (november["id"], rule_id)
            target = f"/api/spending/payment-rules/alfa/{november['id']}"
            params = {"month": "2025-11"}
            for decision, expected in [("separate", "60000.00"), ("payment", "30000.00")]:
                card = client.get(target, params=params).json()
                schedule = next(s for s in card["schedules"] if s["id"] == rule_id)
                receipt = client.put(
                    target + "/occurrence",
                    params=params,
                    json=dict(
                        token=card["token"],
                        rule_id=rule_id,
                        version=schedule["version"],
                        decision=decision,
                    ),
                )
                assert receipt.is_success, receipt.text
                view = client.get(path).json()
                assert view["monthly"]["amount"] == expected and view["payment_candidates"] == []
                assert operations("2025-11")["filtered_total"]["amount"] == "30000.00"
            assert view["target"]["amount"] == "180000.00"
    finally:
        db.engine.dispose()


def test_api_persists_portions_checks_revision_and_caps(tmp_path):
    db = create_database(tmp_path / "reserve.db")
    Base.metadata.create_all(db.engine)
    with db.session_factory() as session:
        report = ReportingMonth(
            year=2020,
            month=11,
            period_start=date(2020, 11, 1),
            period_end=date(2020, 11, 30),
            snapshot_date=date(2020, 11, 30),
            source="manual",
            status="closed",
        )
        session.add(report)
        session.flush()
        session.add(
            CashBalance(
                reporting_month_id=report.id, name="Синтетический кошелёк", amount_kopecks=18000000
            )
        )
        session.add(
            SpendingCategory(name="Продукты", name_key="продукты", expense_type="mandatory")
        )
        session.commit()
    try:
        with TestClient(create_app(db)) as client:
            path = "/api/spending/reserve"
            initial = client.get(path).json()
            assert initial["revision"] == 0 and initial["reserve"] is None
            k = initial["sources"][0]["key"]
            body = dict(
                expected_revision=0,
                plan=plan(sources=[dict(key=k, portion="100000")]).model_dump(mode="json"),
            )
            response = client.put(path, json=body)
            assert response.status_code == 200, response.text
            data = response.json()
            assert (
                data["reserve"]["amount"] == "100000.00" and data["snapshot_date"] == "2020-11-30"
            )
            assert client.get(path).json() == data
            assert client.put(path, json=body).json()["revision"] == 1
            body["plan"]["sources"][0]["portion"] = "190000"
            assert client.put(path, json=body).status_code == 409
            body["expected_revision"] = 1
            too_much = client.put(path, json=body).json()
            assert too_much["reserve"] is None and too_much["difference"] is None
            body["plan"]["sources"] *= 2
            assert client.put(path, json=body).status_code == 422
    finally:
        db.engine.dispose()
