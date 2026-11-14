from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import InstrumentType, RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.instruments import (
    InstrumentNotFoundError,
    create_instrument,
    delete_instrument,
    get_instrument,
    list_instruments,
    update_instrument,
)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "instruments.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


@pytest.mark.parametrize("instrument_type", list(InstrumentType))
def test_instrument_types_are_persisted(instrument_type: InstrumentType, tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session, name=f"Synthetic {instrument_type.value}", instrument_type=instrument_type
        )
        assert instrument.instrument_type == instrument_type.value
    finally:
        session.close()
        database.engine.dispose()


def test_isin_is_unique_only_when_provided(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first = create_instrument(
            session,
            name="Synthetic Bond",
            instrument_type=InstrumentType.BOND,
            isin="RU000A0JXTQ7",
        )
        without_isin = create_instrument(
            session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK
        )
        assert first.isin == "RU000A0JXTQ7"
        assert without_isin.isin is None

        with pytest.raises(ValueError, match="isin must be unique"):
            create_instrument(
                session,
                name="Synthetic Duplicate",
                instrument_type=InstrumentType.BOND,
                isin="RU000A0JXTQ7",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_isin_is_normalized_to_uppercase(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Synthetic Fund",
            instrument_type=InstrumentType.FUND,
            isin="  ru000a0jxtq7  ",
        )
        assert instrument.isin == "RU000A0JXTQ7"
        with pytest.raises(ValueError, match="isin must be unique"):
            create_instrument(
                session,
                name="Synthetic Case Duplicate",
                instrument_type=InstrumentType.FUND,
                isin="Ru000A0JXTQ7",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_instrument_crud_updates_fields_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="  Synthetic Bond  ",
            instrument_type=InstrumentType.BOND,
            ticker="SU29011RMFS5",
            moex_secid="SU29011RMFS5",
            currency="usd",
            nominal_value=RubleAmount.from_api("1000.00"),
            is_active=False,
            manual_price_allowed=False,
        )
        assert instrument.name == "Synthetic Bond"
        assert instrument.ticker == "SU29011RMFS5"
        assert instrument.currency == "USD"
        assert instrument.nominal_value_kopecks == 100_000
        assert instrument.is_active is False
        assert instrument.manual_price_allowed is False

        updated = update_instrument(
            session,
            instrument.id,
            name="Synthetic Bond Updated",
            instrument_type=InstrumentType.OTHER,
            ticker="UPDATED",
            nominal_value=RubleAmount.from_api("1500.50"),
            is_active=True,
            notes="synthetic note",
        )
        assert updated.name == "Synthetic Bond Updated"
        assert updated.instrument_type == InstrumentType.OTHER.value
        assert updated.ticker == "UPDATED"
        assert updated.nominal_value_kopecks == 150_050
        assert updated.is_active is True
        assert updated.notes == "synthetic note"
        assert get_instrument(session, instrument.id).name == "Synthetic Bond Updated"
        assert len(list_instruments(session)) == 1

        delete_instrument(session, instrument.id)
        with pytest.raises(InstrumentNotFoundError):
            get_instrument(session, instrument.id)
    finally:
        session.close()
        database.engine.dispose()


def test_instrument_validation_rejects_invalid_type_empty_name_and_negative_nominal(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        with pytest.raises(ValueError, match="must not be empty"):
            create_instrument(session, name="  ", instrument_type=InstrumentType.OTHER)
        with pytest.raises(ValueError, match="unsupported instrument type"):
            create_instrument(session, name="Synthetic", instrument_type="crypto")
        with pytest.raises(ValueError, match="nominal_value must not be negative"):
            create_instrument(
                session,
                name="Synthetic",
                instrument_type=InstrumentType.BOND,
                nominal_value=RubleAmount.from_api("-1.00"),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_short_name_strips_only_exact_identity_suffixes():
    from hermes_finance.services.instrument_names import short_instrument_name

    assert (
        short_instrument_name(
            "Synthetic (series 2) (SYN) (RU000SYN0001)", isin="RU000SYN0001", ticker="SYN"
        )
        == "Synthetic (series 2)"
    )
    assert short_instrument_name("RU000SYN0001", isin="RU000SYN0001") is None
    assert short_instrument_name("", isin="RU000SYN0001") is None


def test_catalogue_name_is_shared_and_old_fields_are_unchanged():
    from types import SimpleNamespace

    from hermes_finance.services.instrument_names import InstrumentNames

    names = InstrumentNames(
        [SimpleNamespace(id=1, isin="RU000SYN0001", ticker="SYN", name="Synthetic (SYN)")]
    )
    for prior in ("Облигация 1", "RU000SYN0001", "Long source label", None):
        original = {"isin": "RU000SYN0001", "name": prior, "pnl": {"value": None}, "accounts": []}
        result = names.project(original)
        assert result.pop("short_name") == "Synthetic"
        assert result == original
        assert "short_name" not in original
    assert names.name(instrument_id=1) == names.name(isin="RU000SYN0001")


def test_unknown_and_conflicting_names_are_not_guessed():
    from hermes_finance.services.instrument_names import InstrumentNames

    names = InstrumentNames([])
    assert names.name(isin="RU000SYN0001", name="RU000SYN0001") is None
    assert names.name(isin="RU000SYN0001", name="Source (RU000SYN0001)") == "Source"


def test_card_reuses_unambiguous_name_already_present_in_account_details():
    from hermes_finance.services.instrument_names import InstrumentNames

    original = {
        "isin": "RU000SYN0001",
        "name": "RU000SYN0001",
        "accounts": [{"clean": {"isin": "RU000SYN0001", "name": "Synthetic (RU000SYN0001)"}}],
    }
    result = InstrumentNames([]).project(original)
    assert result["short_name"] == "Synthetic"
    assert result["accounts"][0]["clean"]["short_name"] == "Synthetic"
    assert result["name"] == original["name"]
    original["accounts"].append({"clean": {"isin": "RU000SYN0001", "name": "Conflicting"}})
    assert InstrumentNames([]).project(original)["short_name"] is None


def test_statement_names_are_outside_immutable_receipt_document(monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace

    from hermes_finance.services import instrument_names as module

    names = module.InstrumentNames(
        [SimpleNamespace(id=1, isin="RU000SYN0001", ticker="SYN", name="Synthetic (SYN)")]
    )
    monkeypatch.setattr(module, "instrument_names", lambda session: names)
    document = {
        "positions": [{"isin": "RU000SYN0001", "quantity": "1"}],
        "trades": [{"core": {"isin": "RU000SYN0002", "amount": None}}],
    }
    for original in ({"document": document}, {"accepted": {"document": document}}):
        before = deepcopy(original)
        result = module.with_document_short_names(None, original)
        assert result.pop("instrument_labels") == [
            {"isin": "RU000SYN0001", "short_name": "Synthetic"},
            {"isin": "RU000SYN0002", "short_name": None},
        ]
        assert result == before == original


def test_source_name_uses_guarded_display_metadata_without_changing_old_fields(monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace

    from fastapi import Response

    from hermes_finance.api import source_instrument_returns as api
    from hermes_finance.services import (
        instrument_names,
        source_investment_proofs,
        source_monthly_returns,
    )

    monkeypatch.setattr(
        instrument_names, "instrument_names", lambda session: instrument_names.InstrumentNames([])
    )
    reads = []
    original = {"instruments": [{"isin": "RU000SYN0001", "source_name": None, "analysis": None}]}
    monkeypatch.setattr(
        api,
        "read_instrument_returns",
        lambda *a, **k: SimpleNamespace(to_dict=lambda: deepcopy(original)),
    )
    for basis in ("native", "pdf", "unknown"):
        view = {
            "document": {"positions": [], "trades": []},
            "proposals": [{"isin": "RU000SYN0001", "source_name": "Synthetic Security"}],
        }
        monkeypatch.setattr(
            source_monthly_returns,
            "_selected_sources",
            lambda *a, **k: ([(None, view, None)] if basis == "native" else [], {"SYNTHETIC"}),
        )

        def metadata(session, *, source_account, requested_isin):
            reads.append((source_account, requested_isin))
            return {
                "source": {},
                "pdf": {"RU000SYN0001": ("Synthetic Security",)} if basis == "pdf" else {},
            }

        monkeypatch.setattr(source_investment_proofs, "read_latest_display_candidates", metadata)
        result = api.instrument_returns(Response(), "SYNTHETIC", session=None)
        assert result["instruments"][0].pop("short_name") == (
            "Synthetic Security" if basis != "unknown" else None
        )
        assert result == original
    assert reads == [("SYNTHETIC", None), ("SYNTHETIC", None)]


def test_source_label_reuses_exact_registration_identity_without_financial_attribution(monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace

    from hermes_finance.services import money_instrument_links, source_instrument_events
    from hermes_finance.services.instrument_names import source_label_candidates

    resolver = SimpleNamespace(
        reg_isins={},
        conflicts=set(),
        instruments={},
        _related=lambda value: set(),
        _candidates=lambda related: [],
    )
    monkeypatch.setattr(money_instrument_links, "MoneyInstrumentResolver", lambda session: resolver)
    monkeypatch.setattr(
        source_instrument_events, "_REGISTRATION_SCOPE", {"1-01-00001-A": "RU000SYN0001"}
    )
    view = {
        "document": {"positions": [], "trades": []},
        "proposals": [],
        "money_classifications": [
            {
                "classification": "dividend",
                "narrative": 'Дивиденды за 2030 г. по акциям ПАО "Синтетика" (1-01-00001-A). (Удержан налог 1 руб.).',
            }
        ],
    }
    original = deepcopy(view)
    assert source_label_candidates(None, [view])["RU000SYN0001"]["names"] == {'ПАО "Синтетика"'}
    assert view == original
    view["money_classifications"][0]["security_issuer"] = "Conflicting issuer"
    assert not source_label_candidates(None, [view])["RU000SYN0001"]["names"]
