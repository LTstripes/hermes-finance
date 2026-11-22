"""Synthetic Alfa savings CSVs exercised through the same HTTP routes as the editor."""

import csv
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from hermes_finance.alfa_csv import COLUMNS
from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import AlfaSavingsLink, Base, DepositSnapshot, ReportingMonth
from hermes_finance.services.accounts import create_account
from hermes_finance.services.deposits import create_deposit_snapshot, update_deposit_snapshot
from hermes_finance.services.reporting_months import create_reporting_month

SOURCE_A = "1" * 16 + "4000"
SOURCE_B = "2" * 16 + "4000"
INTEREST = (
    "Выплата процентов на ежедневный остаток по счету за 05.2030 по итоговой ставке 12,35% годовых"
)


def movement(number=SOURCE_A, amount="6000", **fields):
    return dict(
        {
            "operationDate": "30.04.2030",
            "transactionDate": "01.05.2030",
            "accountNumber": number,
            "amount": amount,
            "type": "Пополнение",
            "currency": "RUR",
            "status": "Выполнен",
            "category": "Между своими счетами",
        },
        **fields,
    )


def statement(*rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


@pytest.fixture
def env(tmp_path):
    db = create_database(tmp_path / "synthetic.db")
    Base.metadata.create_all(db.engine)
    with db.session_factory() as session:
        before = create_reporting_month(
            session, year=2030, month=4, snapshot_date=date(2030, 4, 30)
        )
        month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 31))
        accounts = [
            create_account(session, name=f"Синтетический {n}", account_type="savings")
            for n in range(3)
        ]
        ids = [a.id for a in accounts]
        before_id, month_id = before.id, month.id
        for account in accounts:
            for m, bal in ((before_id, "100000.00"), (month_id, "101000.01")):
                create_deposit_snapshot(
                    session,
                    reporting_month_id=m,
                    account_id=account.id,
                    name=account.name,
                    deposit_type="savings",
                    balance=bal,
                    annual_rate="9",
                    actual_interest_received="7.89",
                )
    try:
        with TestClient(create_app(db)) as client:
            yield client, db, month_id, before_id, ids
    finally:
        db.engine.dispose()


def preview(client, payload):
    reply = client.post("/api/deposits/alfa/preview", json=payload)
    assert reply.status_code == 200, reply.text
    assert reply.headers["cache-control"] == "no-store"
    return reply.json()["rows"]


def apply(client, payload, row):
    return client.post(
        "/api/deposits/alfa/apply",
        json={**payload, "source_key": row["source_key"], "token": row["token"]},
    )


def test_multi_account_bound_preview_exact_posting_date_and_idempotent_apply(env):
    client, db, month, _, accounts = env
    text = statement(
        movement(),
        movement(amount="2000", type="Списание"),
        movement(amount="1000.40", category="Накопления", merchant=INTEREST),
        movement(amount="700", operationDate="31.05.2030", transactionDate="01.06.2030"),
        movement(SOURCE_B, "6000", type="Списание"),
    )
    data = {"month_id": month, "csv": text}
    a, b = preview(client, data)
    assert a["label"] == b["label"] and a["source_key"] != b["source_key"]
    assert SOURCE_A not in str(a) and SOURCE_B not in str(b)
    assert a["count"] == 3 and a["first_date"] == a["last_date"] == "2030-05-01"
    assert [r["token"] for r in (a, b)] == [None, None]
    data["bindings"] = {a["source_key"]: accounts[0], b["source_key"]: accounts[1]}
    assert all(r["token"] is None for r in preview(client, data))
    data["full_month"] = True
    a, b = preview(client, data)
    assert a["proposed"] == {
        "balance": "105000.40",
        "actual_interest_received": "1000.40",
        "annual_rate": "12.35",
    }
    assert a["difference"] == "4000.39"
    assert b["proposed"] == {
        "balance": "94000.00",
        "actual_interest_received": None,
        "annual_rate": None,
    }
    assert a["token"] and b["token"] and not a["mapped"]
    assert preview(client, data) == [a, b]
    with db.session_factory() as s:
        assert s.scalar(select(func.count()).select_from(AlfaSavingsLink)) == 0
    saved = apply(client, data, a)
    assert saved.status_code == 200, saved.text
    assert saved.json()["balance"]["amount"] == "105000.40"
    assert saved.json()["expected_monthly_interest"]["amount"] == "1080.63"
    assert apply(client, data, a).status_code == 409
    assert apply(client, data, b).json()["actual_interest_received"]["amount"] == "7.89"
    again = preview(client, {**data, "bindings": {}})
    assert all(r["mapped"] and r["token"] is None for r in again)
    assert [
        r["balance"]["amount"]
        for r in client.get("/api/deposits", params={"month_id": month}).json()
    ] == ["105000.40", "94000.00", "101000.01"]


@pytest.mark.parametrize("change", ["closed", "manual", "opening", "file", "scope", "full_month"])
def test_changed_dependencies_never_apply_a_stale_preview(env, change):
    client, db, month, before, accounts = env
    data = {"month_id": month, "csv": statement(movement()), "full_month": True}
    key = preview(client, data)[0]["source_key"]
    data["bindings"] = {key: accounts[0]}
    row = preview(client, data)[0]
    with db.session_factory() as session:
        if change == "closed":
            session.get(ReportingMonth, month).status = "closed"
            session.commit()
        if change in {"manual", "opening"}:
            target = month if change == "manual" else before
            snap = session.scalars(
                select(DepositSnapshot).where(
                    DepositSnapshot.reporting_month_id == target,
                    DepositSnapshot.account_id == accounts[0],
                )
            ).one()
            update_deposit_snapshot(session, snap.id, balance="123.45")
    if change == "file":
        data["csv"] = statement(movement(amount="6001"))
    if change == "scope":
        data["bindings"][key] = accounts[1]
    if change == "full_month":
        data["full_month"] = False
    reply = apply(client, data, row)
    assert reply.status_code == 409
    with db.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AlfaSavingsLink)) == 0
        unchanged = session.scalars(
            select(DepositSnapshot).where(
                DepositSnapshot.reporting_month_id == month,
                DepositSnapshot.account_id == accounts[0],
            )
        ).one()
        assert unchanged.balance_kopecks == (12345 if change == "manual" else 10100001)


@pytest.mark.parametrize(
    "fields",
    [
        {"currency": "USD"},
        {"transactionDate": ""},
        {"status": "В обработке"},
        {"accountNumber": "****4000"},
        {"transactionDate": "01.06.2030"},
    ],
)
def test_ineligible_statements_do_not_offer_a_write(env, fields):
    client, _, month, _, accounts = env
    data = {"month_id": month, "csv": statement(movement(**fields)), "full_month": True}
    key = preview(client, data)[0]["source_key"]
    row = preview(client, {**data, "bindings": {key: accounts[0]}})[0]
    assert row["messages"] and row["token"] is None
    assert all(value is None for value in row["proposed"].values())


def test_ambiguous_target_and_unrecognized_interest(env):
    client, _, month, _, accounts = env
    data = {
        "month_id": month,
        "csv": statement(
            movement(category="Накопления", merchant="Неизвестное начисление"), movement(SOURCE_B)
        ),
        "full_month": True,
    }
    a, b = preview(client, data)
    both = {r["source_key"]: accounts[0] for r in (a, b)}
    assert all(r["token"] is None for r in preview(client, {**data, "bindings": both}))
    target = {**data, "bindings": {a["source_key"]: accounts[0]}}
    row = preview(client, target)[0]
    assert row["proposed"] == {
        "balance": "106000.00",
        "actual_interest_received": None,
        "annual_rate": None,
    }
    assert apply(client, target, row).status_code == 200
    assert preview(client, {**data, "bindings": {b["source_key"]: accounts[0]}})[1]["token"] is None


def test_missing_snapshot_or_missing_opening_balance(env):
    client, db, month, before, accounts = env
    with db.session_factory() as session:
        for account, target in ((accounts[0], month), (accounts[1], before)):
            snap = session.scalars(
                select(DepositSnapshot).where(
                    DepositSnapshot.reporting_month_id == target,
                    DepositSnapshot.account_id == account,
                )
            ).one()
            session.delete(snap)
        session.commit()
    data = {
        "month_id": month,
        "csv": statement(
            movement(
                amount="125.12", category="Накопления", merchant=INTEREST.split(" по итоговой")[0]
            ),
            movement(SOURCE_B, "123.01", category="Накопления", merchant=INTEREST),
        ),
        "full_month": True,
    }
    a, b = preview(client, data)
    data["bindings"] = {a["source_key"]: accounts[0], b["source_key"]: accounts[1]}
    a, b = preview(client, data)
    assert a["snapshot_id"] is None
    assert a["proposed"]["annual_rate"] == "9.00"
    assert any("перенесена" in m for m in a["messages"])
    created = apply(client, data, a).json()
    assert (
        created["balance"]["amount"] == "100125.12"
        and created["annual_rate"] == a["proposed"]["annual_rate"]
    )
    assert b["proposed"]["balance"] is None
    body = apply(client, data, b).json()
    assert (
        body["balance"]["amount"] == "101000.01"
        and body["actual_interest_received"]["amount"] == "123.01"
    )


def test_confirmed_link_cannot_be_reassigned_or_apply_twice(env):
    client, _, month, _, accounts = env
    data = {
        "month_id": month,
        "csv": statement(movement(category="Накопления", merchant=INTEREST)),
        "full_month": True,
    }
    row = preview(client, data)[0]
    data["bindings"] = {row["source_key"]: accounts[0]}
    row = preview(client, data)[0]
    assert apply(client, data, row).status_code == 200
    data["bindings"][row["source_key"]] = accounts[1]
    again = preview(client, data)[0]
    assert again["account_id"] == accounts[0] and again["mapped"] and not again["token"]
    assert apply(client, data, row).status_code == 409
    untouched = client.get(
        "/api/deposits", params={"month_id": month, "account_id": accounts[1]}
    ).json()[0]
    assert untouched["actual_interest_received"]["amount"] == "7.89"


def test_unidentified_movements_do_not_group_or_silently_change_the_other_account(env):
    client, _, month, _, accounts = env
    data = {
        "month_id": month,
        "csv": statement(movement(), movement("   "), movement("****4000"), movement("****4000")),
        "full_month": True,
    }
    good, *invalid = preview(client, data)
    assert len({r["source_key"] for r in invalid}) == len(invalid) == 3
    assert {r["label"] for r in invalid} == {"Номер не определён"}
    good = preview(client, {**data, "bindings": {good["source_key"]: accounts[0]}})[0]
    assert good["token"] is None and all(v is None for v in good["proposed"].values())
    bad_request = client.post(
        "/api/deposits/alfa/preview", json={**data, "bindings": {SOURCE_A: "wrong"}}
    )
    assert bad_request.status_code == 422 and SOURCE_A not in bad_request.text


def test_interest_reversal_preserves_interest_and_rate_while_netting_balance(env):
    client, _, month, _, accounts = env
    data = {
        "month_id": month,
        "csv": statement(
            movement(amount="100.00", category="Накопления", merchant=INTEREST),
            movement(
                amount="75.17",
                category="Накопления",
                type="Списание",
                comment="Сторно выплаты процентов",
            ),
        ),
        "full_month": True,
    }
    row = preview(client, data)[0]
    data["bindings"] = {row["source_key"]: accounts[0]}
    row = preview(client, data)[0]
    assert row["proposed"] == {
        "balance": "100024.83",
        "annual_rate": None,
        "actual_interest_received": None,
    }
    result = apply(client, data, row).json()
    assert (
        result["actual_interest_received"]["amount"] == "7.89" and result["annual_rate"] == "9.00"
    )


@pytest.mark.parametrize("intermediate", ["opening", "current"])
def test_month_end_snapshot_boundaries(env, intermediate):
    client, db, month, before, accounts = env
    data = {
        "month_id": month,
        "csv": statement(movement(category="Накопления", merchant=INTEREST)),
        "full_month": True,
    }
    row = preview(client, data)[0]
    data["bindings"] = {row["source_key"]: accounts[0]}
    old = preview(client, data)[0]
    with db.session_factory() as s:
        target = before if intermediate == "opening" else month
        m = s.get(ReportingMonth, target)
        m.snapshot_date = m.period_end.replace(day=15)
        s.commit()
    assert apply(client, data, old).status_code == 409
    new = preview(client, data)[0]
    assert new["proposed"]["balance"] is None
    if intermediate == "opening":
        assert new["proposed"]["actual_interest_received"] == "6000.00"
        result = apply(client, data, new).json()
        assert result["balance"]["amount"] == "101000.01"
    else:
        assert new["token"] is None and all(v is None for v in new["proposed"].values())
