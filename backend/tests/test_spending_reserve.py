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
    assert near["target"]["amount"] == "228000.00"
    assert near["difference"]["amount"] == "-48000.00"
    late = calc(plan(start="2028-06-01", end="2028-11-30"), [rule()])
    assert late["target"]["amount"] == "252000.00"
    assert late["calendar"][-1]["total"]["amount"] == "62000.00"


def test_uncertain_rule_and_absent_price_preserve_unknown():
    for candidate in (rule(needs_review=True, mandatory=None), rule(amount_kopecks=None)):
        view = calc(plan(), [candidate])
        assert view["target"] is None and view["monthly"] is None
    view = calc(plan(), [rule(next_due=None)])
    assert view["target"] is None and view["monthly"]["amount"] == "40000.00"
    optional = rule(mandatory=False, mandatory_override=False, needs_review=True)
    assert calc(plan(), [optional])["monthly"]["amount"] == "38000.00"
    assert calc(plan(), [rule(repeat=False)])["monthly"]["amount"] == "38000.00"


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
    monkeypatch.setattr(spending_insights, "operations", lambda s, b, limit: {"items": items})
    p = plan(categories=[dict(id=1)], months=["2026-10", "2026-11"])
    rules = [rule(month=m, source="alfa", operation_id=1) for m in p.months]
    assert reserve.historical_amounts(FakeSession(), p, rules)[1] == 150000
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
