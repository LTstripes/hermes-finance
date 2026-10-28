"""Synthetic parity/currentness checks for the presentation read optimizations."""

from collections import Counter
from datetime import date

import pytest
from test_returns_view_service import END, SCOPE, START, basket_source
from test_source_instrument_returns_service import save
from test_source_monthly_returns_service import snapshot
from test_statement_import_mybroker import ACCOUNT

from hermes_finance.services import returns_view, source_intake
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.source_money_classifications import choose_classification
from hermes_finance.services.source_monthly_returns import (
    _selected_sources,
    source_read_snapshot,
)


@pytest.fixture
def db(tmp_path, source_returns_database_factory):
    database = source_returns_database_factory(tmp_path)
    yield database
    database.engine.dispose()


def test_source_views_are_verified_once_per_snapshot_and_never_shared_mutably(db, monkeypatch):
    basket_source(db)
    basket_source(db, month=5)
    original = source_intake._view
    calls = Counter()

    def counted(session, row, **kwargs):
        calls[row.id] += 1
        return original(session, row, **kwargs)

    monkeypatch.setattr(source_intake, "_view", counted)
    with db.session_factory() as session:
        returns_view.read_context(session)
        assert sorted(calls.values()) == [1, 1]
        returns_view.read_context(session)
        assert sorted(calls.values()) == [2, 2]
        with source_read_snapshot(session):
            first, _ = _selected_sources(session, ACCOUNT)
            first[0][1]["document"]["positions"].clear()
            again, _ = _selected_sources(session, ACCOUNT)
            assert again[0][1]["document"]["positions"]
        assert sorted(calls.values()) == [3, 3]


def test_failed_snapshot_drops_memo_and_later_reader_failure_is_visible(db, monkeypatch):
    basket_source(db)
    with db.session_factory() as session:
        with pytest.raises(RuntimeError, match="abort"):
            with source_read_snapshot(session):
                selected, _ = _selected_sources(session, ACCOUNT)
                assert selected[0][1] is not None
                raise RuntimeError("abort")

        def unavailable(*args, **kwargs):
            raise ValueError("changed source")

        monkeypatch.setattr(source_intake, "_view", unavailable)
        with source_read_snapshot(session):
            selected, _ = _selected_sources(session, ACCOUNT)
            assert selected[0][1:] == (None, "source_reader_unavailable")


def test_reused_session_revalidates_changed_classification_between_reads(db):
    intake_id = basket_source(db, extra=(("Synthetic payment", "Synthetic receipt", "100"),))
    with db.session_factory() as session:
        with source_read_snapshot(session):
            selected, _ = _selected_sources(session, ACCOUNT)
            previous = selected[0][1]["money_classifications"][0]
            assert previous["classification"] != "fee"
        # A supported source-only decision in the disposable test DB changes a
        # dependency. The old verified view must not survive into another GET.
        with db.session_factory() as writer:
            choose_classification(writer, intake_id, previous["source_reference"], "fee")
        with source_read_snapshot(session):
            changed, _ = _selected_sources(session, ACCOUNT)
            current = changed[0][1]["money_classifications"][0]
            assert current["classification"] == "fee"
            assert current["origin"] == "user_choice"


@pytest.mark.parametrize("bond", [None, ("2", "3", "2000", "3150")])
def test_selected_overview_and_detail_equal_full_history_reader(db, monkeypatch, bond):
    save(db, bond=bond)
    save(db, 5, bond=bond)
    before = snapshot(db)

    def read():
        with db.session_factory() as session:
            overview = returns_view.read_overview(session, scope=SCOPE, start=START, end=END)
            details = [
                returns_view.read_detail(
                    session, scope=SCOPE, start=START, end=END, isin=row["isin"]
                )
                for row in overview["instruments"]
            ]
        return overview, details

    selected = read()
    instrument_reader = returns_view.read_instrument_returns

    def with_history(*args, **kwargs):
        return instrument_reader(*args, **{**kwargs, "include_monthly_history": True})

    monkeypatch.setattr(returns_view, "read_instrument_returns", with_history)
    assert read() == selected
    assert snapshot(db) == before


def test_accepted_scope_does_not_decode_source_journal(db, monkeypatch):
    basket_source(db)

    def unexpected(*args, **kwargs):
        raise AssertionError("accepted scope decoded an unrelated source")

    monkeypatch.setattr(source_intake, "_view", unexpected)
    with db.session_factory() as session:
        result = returns_view.read_overview(session, scope="portfolio", start=START, end=END)
    assert result["selected"]["pnl"]["method"] == "PERF04A"


def test_month_journal_keeps_only_bound_or_calendar_overlapping_unbound_sources(db, monkeypatch):
    april = basket_source(db, month=4)
    may = basket_source(db, month=5)
    with db.session_factory() as session:
        month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 31))
        month_id = month.id
        session.commit()
    with db.session_factory() as session:
        assert {v["id"] for v in source_intake.list_intakes(session)} == {april, may}
        assert [v["id"] for v in source_intake.list_intakes(session, month_id, True)] == [may]

    read = source_intake._view

    def bound(session, row, **kwargs):
        value = read(session, row, **kwargs)
        if row.id == april:
            value["state"]["reporting_month_id"] = month_id
        return value

    monkeypatch.setattr(source_intake, "_view", bound)
    with db.session_factory() as session:
        assert {v["id"] for v in source_intake.list_intakes(session, month_id, True)} == {
            april,
            may,
        }
