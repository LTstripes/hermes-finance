"""Disposable, fabricated S3 native bond statement + existing zero-crossing proof."""

from datetime import date
from xml.etree import ElementTree as ET


def seed_statement_return(database):
    from hermes_finance.domain.source_cash_coverage import SourceCashIntent
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.broker_months import (
        apply_broker_month,
        preview_broker_month,
    )
    from hermes_finance.services.reporting_months import create_reporting_month
    from test_statement_import_broker_statement_return import native_xml
    from test_statement_import_source_cash_coverage import (
        certify,
        claims,
        continuous_membership,
    )

    root = ET.fromstring(native_xml())
    row = root.find(".//{MyBroker}Details[@ISIN1]")
    row.set("ISIN1", "RU000A000001")
    row.set("active_type", "Облигации")
    row.set("active_name", "Synthetic bond")
    raw = ET.tostring(root, encoding="utf-8").replace(b"1234567", b"9999000")
    filename = "Брокерский 9999000 (01.07.30-31.07.30).xml"
    with database.session_factory() as session:
        account = create_account(
            session, name="Synthetic statement broker", account_type="brokerage"
        )
        create_account(session, name="Synthetic empty statement broker", account_type="brokerage")
        month = create_reporting_month(session, year=2030, month=7, snapshot_date=date(2030, 7, 31))
        kwargs = {
            "document": raw,
            "filename": filename,
            "reporting_month_id": month.id,
            "account_id": account.id,
            "optional_hashes": [],
        }
        plan = preview_broker_month(session, **kwargs)
        assert plan["can_apply"], plan
        apply_broker_month(
            session,
            **kwargs,
            request_id="synthetic-statement-return",
            confirmation_digest=plan["confirmation_digest"],
            reviewed_account_bindings=plan["account_bindings"],
        )
        continuous_membership(session, account.id)
        intent = SourceCashIntent(
            account_id=account.id,
            opening_date=date(2030, 6, 30),
            closing_date=date(2030, 7, 31),
        )
        certify(
            session,
            claims(session, intent, zero=True),
            request="synthetic-statement-coverage",
        )
