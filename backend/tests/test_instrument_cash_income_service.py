"""Synthetic canonical ICF / Money / typed-PDF known-payout read contract."""

from datetime import date

from _statement_pdf import build_income_report_pdf
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_statement_import_apply import apply as pdf_apply
from test_statement_import_apply import preview as pdf_preview
from test_statement_import_apply import selection_from_row, sqlite_blob
from test_statement_import_mybroker import FILENAME, ISIN
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _money_apply,
    _money_decide,
    _money_setup,
    money_batch_xml,
    money_coupon_pdf,
)

from hermes_finance.main import create_app
from hermes_finance.persistence import (
    AppliedStatementEvent,
    BrokerIdentityMapping,
    Instrument,
    InvestmentCashFlow,
    ReportingMonth,
)
from hermes_finance.services.broker_identity_mappings import revoke_mapping
from hermes_finance.services.instrument_cash_income import known_instrument_cash_income
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.statement_import_apply import StatementApplyAction
from hermes_finance.services.statement_import_retract import retract_applied_statement_event

A, B = date(2029, 12, 31), date(2030, 1, 31)


def setup(database, coupons=("120",), *, distinct=False):
    client, xml, intent, bond, _ = _money_setup(
        database, money_batch_xml(coupons=coupons, distinct=distinct)
    )
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        saved = _money_apply(
            session, _money_decide(session, intent, originals, bond, funding=False), originals
        )
    return client, intent, bond, saved, originals


def read(session, intent, instrument):
    return known_instrument_cash_income(session, intent.account_id, instrument, A, B)


def test_net_120_null_tax_readonly_closed_http_and_scope(database):
    client, intent, bond, saved, _ = setup(database)
    with database.session_factory() as session:
        month = session.get(ReportingMonth, intent.reporting_month_id)
        month.status = "closed"
        session.commit()
        before = sqlite_blob(database)
        result = read(session, intent, bond)
        assert result["known_booked_net"] == {"coupon": "120.00", "dividend": None}
        assert result["coverage"] == result["completeness"] == "unknown"
        (row,) = result["events"]
        assert row["proof_state"] == "source_accepted"
        assert row["booked_net"] == "120.00" and row["tax"] is None
        assert row["gross"] is None and row["fee"] is None and not row["tax_available"]
        params = {"account_id": intent.account_id, "t0": str(A), "t1": str(B)}
        response = client.get(f"/api/instruments/{bond}/cash-income", params=params)
        assert response.status_code == 200, response.text
        assert response.json() == result
        assert (
            client.get(
                f"/api/instruments/{bond}/cash-income", params={**params, "t0": str(B)}
            ).status_code
            == 422
        )
        assert (
            client.get(
                f"/api/instruments/{bond}/cash-income", params={**params, "account_id": 9999}
            ).status_code
            == 404
        )
        assert client.post(f"/api/instruments/{bond}/cash-income", json=params).status_code == 405
        empty = known_instrument_cash_income(session, intent.account_id, bond, date(2030, 1, 17), B)
        assert empty["events"] == [] and empty["known_booked_net"]["coupon"] is None
        assert "no_observed_events" in empty["reason_codes"]
        assert sqlite_blob(database) == before


def test_multiple_equal_economic_identities_and_pdf_are_not_date_amount_dedup(database):
    _, intent, bond, _, _ = setup(database, ("120", "120"), distinct=True)
    with database.session_factory() as session:
        result = read(session, intent, bond)
        assert result["known_booked_net"]["coupon"] == "240.00"
        assert len({e["cash_flow_id"] for e in result["events"]}) == 2


def test_money_pdf_link_once_repeat_and_retract_preserves_canonical_flow(database):
    _, intent, bond, saved, originals = setup(database)
    target = saved["targets"][0]["target_id"]
    pdf = money_coupon_pdf(net="120,00")
    with database.session_factory() as session:
        row = pdf_preview(session, pdf, intent.account_id).rows[0]
        applied = pdf_apply(
            session,
            pdf,
            intent.account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=target,
                    expected_candidate_ids=(target,),
                ),
            ),
        )
        assert applied.success
        row = pdf_preview(session, pdf, intent.account_id).rows[0]
        assert pdf_apply(session, pdf, intent.account_id, (selection_from_row(row),)).success
        result = read(session, intent, bond)
        assert result["event_count"] == 1
        assert result["known_booked_net"]["coupon"] == "120.00"
        assert result["events"][0]["provenance"] == ["accepted_money_coupon", "typed_depository"]
        assert result["events"][0]["tax"] is None
        applied_event = session.scalar(select(AppliedStatementEvent))
        retract_applied_statement_event(session, applied_event.id)
        after = read(session, intent, bond)
        assert session.get(InvestmentCashFlow, target) is not None
        assert after["event_count"] == 1
        # Existing Money lifecycle retires its proof on PDF retract. Keep the
        # booked fact visible, without reviving source authority on our read.
        assert after["events"][0]["booked_net"] == "120.00"
        assert after["events"][0]["proof_state"] == "retired_or_unmatched"
        assert after["known_booked_net"]["coupon"] is None
        assert after["dependency_fingerprint"] != result["dependency_fingerprint"]
        reviewed = _money_decide(
            session, intent, originals, bond, funding=False, operation="reaffirm"
        )
        _money_apply(session, reviewed, originals, "after-retract-reaffirm")
        assert read(session, intent, bond)["known_booked_net"]["coupon"] == "120.00"


def dividend_pdf():
    return build_income_report_pdf(
        [
            {
                "isin": ISIN,
                "payment_kind": "выплата дивидендов",
                "security_name": "Synthetic equity",
                "record_date": "15.01.2030",
                "payment_date": "20.01.2030",
                "quantity": "10",
                "per_unit": "12,00",
                "gross": "120,00",
                "net": "120,00",
                "tax": "—",
                "tax_rate": "—",
            }
        ]
    )


def test_exited_dividend_typed_authority_manual_and_unknown_denomination(database):
    _, _, intent, _, _ = _money_setup(database, money_batch_xml(coupons=("120",)))
    with database.session_factory() as session:
        stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
        # No current holding is needed: immutable accepted native identity is retained.
        stock.is_active = False
        session.commit()
        pdf = dividend_pdf()
        row = pdf_preview(session, pdf, intent.account_id).rows[0]
        applied = pdf_apply(session, pdf, intent.account_id, (selection_from_row(row),))
        assert applied.success, applied
        result = read(session, intent, stock.id)
        assert result["known_booked_net"]["dividend"] == "120.00"
        assert result["events"][0]["proof_state"] == "source_accepted"
        assert result["events"][0]["tax"] is None
        target = applied.items[0].investment_cash_flow_id
        for kind in ("redemption", "commission", "deposit"):
            session.add(
                InvestmentCashFlow(
                    account_id=intent.account_id,
                    reporting_month_id=intent.reporting_month_id,
                    instrument_id=stock.id,
                    flow_type=kind,
                    event_date=date(2030, 1, 20),
                    gross_amount_kopecks=999,
                    tax_amount_kopecks=0,
                    commission_amount_kopecks=0,
                    net_amount_kopecks=999,
                    source="manual",
                )
            )
        session.commit()
        assert read(session, intent, stock.id)["event_count"] == 1
        # A statement-created retract deletes the canonical payout, not a phantom zero.
        event_id = session.scalar(select(AppliedStatementEvent.id))
        retract_applied_statement_event(session, event_id)
        assert session.get(InvestmentCashFlow, target) is None
        assert read(session, intent, stock.id)["known_booked_net"]["dividend"] is None
        manual = InvestmentCashFlow(
            account_id=intent.account_id,
            reporting_month_id=intent.reporting_month_id,
            instrument_id=stock.id,
            flow_type="dividend",
            event_date=date(2030, 1, 20),
            gross_amount_kopecks=12000,
            tax_amount_kopecks=0,
            commission_amount_kopecks=0,
            net_amount_kopecks=12000,
            source="manual",
        )
        session.add(manual)
        session.commit()
        assert read(session, intent, stock.id)["events"][0]["proof_state"] == "manual_booked"
        # Today's catalogue alone cannot fill an absent historical identity.
        unknown_stock = Instrument(
            name="Synthetic unobserved stock", instrument_type="stock", currency="RUB"
        )
        session.add(unknown_stock)
        session.flush()
        manual.instrument_id = unknown_stock.id
        session.commit()
        unknown = read(session, intent, unknown_stock.id)
        assert unknown["known_booked_net"]["dividend"] is None
        assert unknown["events"][0]["proof_state"] == "manual_booked"
        assert "historical_instrument_identity_unknown" in unknown["events"][0]["reason_codes"]
        assert unknown["dependency_fingerprint"] is None


def test_typed_dividend_historical_mapping_revocation_drops_source_authority(database):
    _, _, intent, _, _ = _money_setup(database, money_batch_xml(coupons=("120",)))
    with database.session_factory() as session:
        stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
        pdf = dividend_pdf()
        row = pdf_preview(session, pdf, intent.account_id).rows[0]
        assert pdf_apply(session, pdf, intent.account_id, (selection_from_row(row),)).success
        before = read(session, intent, stock.id)
        assert before["known_booked_net"]["dividend"] == "120.00"
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(
                BrokerIdentityMapping.subject_kind == "instrument",
                BrokerIdentityMapping.provider_identity == ISIN,
            )
        )
        revoke_mapping(session, mapping.id, reason="Synthetic revoke")
        after = read(session, intent, stock.id)
        assert after["known_booked_net"]["dividend"] is None
        assert after["events"][0]["proof_state"] == "incomplete_unknown"
        assert after["dependency_fingerprint"] != before["dependency_fingerprint"]


def test_manual_and_typed_later_month_have_no_fabricated_revision_token(database):
    _, _, intent, _, _ = _money_setup(database, money_batch_xml(coupons=("120",)))
    client = TestClient(create_app(database))
    with database.session_factory() as session:
        stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
        month = create_reporting_month(session, year=2030, month=2, snapshot_date=date(2030, 2, 28))
        # Build a February typed dividend; native identity is historical January.
        later = build_income_report_pdf(
            [
                {
                    "isin": ISIN,
                    "payment_kind": "выплата дивидендов",
                    "record_date": "15.02.2030",
                    "payment_date": "20.02.2030",
                    "quantity": "10",
                    "per_unit": "12,00",
                    "gross": "120,00",
                    "net": "120,00",
                    "tax": "—",
                    "tax_rate": "—",
                }
            ]
        )
        row = pdf_preview(session, later, intent.account_id).rows[0]
        saved = pdf_apply(session, later, intent.account_id, (selection_from_row(row),))
        assert saved.success
        target = saved.items[0].investment_cash_flow_id
        params = dict(
            account_id=intent.account_id,
            instrument_id=stock.id,
            t0=date(2030, 1, 31),
            t1=date(2030, 2, 28),
        )
        a = known_instrument_cash_income(session, **params)
        assert a["dependency_fingerprint"] is None and a["known_booked_net"]["dividend"] is None
        for value in ("121.00", "120.00"):
            response = client.patch(
                f"/api/investment-flows/{target}",
                json={
                    "gross_amount": {"amount": value, "currency": "RUB"},
                    "net_amount": {"amount": value, "currency": "RUB"},
                },
            )
            assert response.status_code == 200, response.text
            got = known_instrument_cash_income(session, **params)
            assert got["dependency_fingerprint"] is None
            assert got["events"][0]["proof_state"] != "source_accepted"
        flow = InvestmentCashFlow(
            account_id=intent.account_id,
            instrument_id=stock.id,
            reporting_month_id=month.id,
            event_date=date(2030, 2, 21),
            flow_type="dividend",
            source="manual",
            gross_amount_kopecks=12000,
            tax_amount_kopecks=0,
            commission_amount_kopecks=0,
            net_amount_kopecks=12000,
        )
        session.add(flow)
        session.commit()
        for amount in (12100, 12000):
            flow.gross_amount_kopecks = flow.net_amount_kopecks = amount
            session.commit()
            got = known_instrument_cash_income(session, **params)
            assert got["dependency_fingerprint"] is None
            assert any(e["proof_state"] == "manual_booked" for e in got["events"])


def test_active_pdf_cannot_revive_retired_money_authority(database):
    _, intent, bond, saved, _ = setup(database)
    with database.session_factory() as session:
        target = saved["targets"][0]["target_id"]
        pdf = money_coupon_pdf(net="120,00")
        row = pdf_preview(session, pdf, intent.account_id).rows[0]
        assert pdf_apply(
            session,
            pdf,
            intent.account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=target,
                    expected_candidate_ids=(target,),
                ),
            ),
        ).success
        session.add(
            InvestmentCashFlow(
                account_id=intent.account_id,
                instrument_id=None,
                reporting_month_id=intent.reporting_month_id,
                event_date=date(2030, 1, 20),
                flow_type="dividend",
                source="manual",
                gross_amount_kopecks=0,
                tax_amount_kopecks=0,
                commission_amount_kopecks=0,
                net_amount_kopecks=0,
            )
        )
        session.commit()
        result = read(session, intent, bond)
        assert result["known_booked_net"]["coupon"] is None
        assert result["events"][0]["proof_state"] == "retired_or_unmatched"
        assert result["events"][0]["provenance"] == ["typed_depository"]


def test_proven_zero_foreign_components_and_exact_account_isolation(database):
    client, _, intent, _, _ = _money_setup(database, money_batch_xml(coupons=("120",)))
    with database.session_factory() as session:
        stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
        pdf = build_income_report_pdf(
            [
                {
                    "isin": ISIN,
                    "payment_kind": "выплата дивидендов",
                    "record_date": "15.01.2030",
                    "payment_date": "20.01.2030",
                    "quantity": "10",
                    "per_unit": "0,00",
                    "gross": "0,00",
                    "net": "0,00",
                    "tax": "—",
                    "tax_rate": "—",
                }
            ]
        )
        row = pdf_preview(session, pdf, intent.account_id).rows[0]
        saved = pdf_apply(session, pdf, intent.account_id, (selection_from_row(row),))
        assert saved.success, saved
        zero = read(session, intent, stock.id)
        assert zero["known_booked_net"]["dividend"] == "0.00"
        session.add(
            InvestmentCashFlow(
                account_id=intent.account_id,
                instrument_id=stock.id,
                reporting_month_id=intent.reporting_month_id,
                event_date=date(2030, 1, 21),
                flow_type="dividend",
                source="manual",
                currency="USD",
                gross_amount_kopecks=12000,
                tax_amount_kopecks=0,
                commission_amount_kopecks=0,
                net_amount_kopecks=12000,
            )
        )
        session.commit()
        foreign = read(session, intent, stock.id)["events"][-1]
        assert all(foreign[field] is None for field in ("booked_net", "gross", "tax", "fee"))
        assert not foreign["tax_available"] and not foreign["included_in_known_net"]
        from hermes_finance.services.accounts import create_account

        other = create_account(session, name="Other synthetic scope", account_type="iis")
        assert known_instrument_cash_income(session, other.id, stock.id, A, B)["events"] == []


def test_same_month_typed_public_patch_aba_changes_joined_revision_fingerprint(database):
    client, _, intent, _, _ = _money_setup(database, money_batch_xml(coupons=("120",)))
    with database.session_factory() as session:
        stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
        pdf = dividend_pdf()
        row = pdf_preview(session, pdf, intent.account_id).rows[0]
        saved = pdf_apply(session, pdf, intent.account_id, (selection_from_row(row),))
        assert saved.success
        results = [read(session, intent, stock.id)]
        for amount in ("121.00", "120.00"):
            response = client.patch(
                f"/api/investment-flows/{saved.items[0].investment_cash_flow_id}",
                json={
                    "gross_amount": {"amount": amount, "currency": "RUB"},
                    "net_amount": {"amount": amount, "currency": "RUB"},
                },
            )
            assert response.status_code == 200, response.text
            results.append(read(session, intent, stock.id))
        assert len({r["dependency_fingerprint"] for r in results}) == 3
        assert all(r["dependency_fingerprint"] is not None for r in results)
        assert results[1]["known_booked_net"]["dividend"] is None
        assert results[0]["known_booked_net"] == results[2]["known_booked_net"]


def test_source_mapping_aba_never_revives_authority_or_digest(database):
    _, intent, bond, _, _ = setup(database)
    with database.session_factory() as session:
        a = read(session, intent, bond)
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
        )
        old = mapping.source_as_of
        mapping.source_as_of = date(2030, 1, 19)
        session.commit()
        b = read(session, intent, bond)
        mapping.source_as_of = old
        session.commit()
        again = read(session, intent, bond)
        assert a["events"][0]["proof_state"] == "source_accepted"
        assert b["events"][0]["proof_state"] != "source_accepted"
        assert again["events"][0]["proof_state"] != "source_accepted"
        assert len({r["dependency_fingerprint"] for r in (a, b, again)}) == 3


def test_snapshot_query_only_and_concurrent_source_change(database):
    _, intent, bond, _, _ = setup(database)
    # WAL allows a writer to commit while the protected reader still sees A.
    with database.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    with database.session_factory() as session:
        before = read(session, intent, bond)
        mutated = False

        def mutate(conn, cursor, statement, params, context, many):
            nonlocal mutated
            if not mutated and statement.startswith("SELECT investment_cash_flows"):
                mutated = True
                with database.session_factory() as other:
                    mapping = other.scalar(
                        select(BrokerIdentityMapping).where(
                            BrokerIdentityMapping.subject_kind == "account"
                        )
                    )
                    mapping.source_as_of = date(2030, 1, 19)
                    other.commit()

        event.listen(database.engine, "after_cursor_execute", mutate)
        try:
            coherent = read(session, intent, bond)
        finally:
            event.remove(database.engine, "after_cursor_execute", mutate)
        assert mutated and coherent == before
        assert read(session, intent, bond)["events"][0]["proof_state"] != "source_accepted"


def test_unavailable_coupon_reader_is_partial_not_fabricated_zero(database, monkeypatch):
    _, intent, bond, _, _ = setup(database)
    from hermes_finance.services import instrument_cash_income as module

    monkeypatch.setattr(
        module, "authority", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad evidence"))
    )
    with database.session_factory() as session:
        result = read(session, intent, bond)
        assert "coupon_authority_unavailable" in result["reason_codes"]
        assert result["known_booked_net"]["coupon"] is None
        assert result["events"][0]["booked_net"] == "120.00"
