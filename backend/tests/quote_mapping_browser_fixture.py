"""Loopback-only synthetic quote-mapping browser fixture; no live provider or DB.

Seeds one draft month with one unmapped stock position and serves the built
frontend. The injected ``SyntheticQuoteProvider`` is deterministic and never
touches the network; it answers both mapping verification and quote fetches.
"""

from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import mkdtemp

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType
from hermes_finance.main import create_app
from hermes_finance.market_data.capabilities import T_INVEST_CAPABILITIES
from hermes_finance.market_data.dto import (
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteKind,
    QuoteStatus,
    QuoteSuccess,
    RawPriceBasis,
)
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month

TODAY = date(2031, 5, 31)
SYNTHETIC_UID = "11111111-1111-1111-1111-111111111111"
PROPOSED_KOPECKS = 12345


class SyntheticQuoteProvider:
    """Deterministic T-Invest-shaped provider used only by this fixture."""

    def __init__(self) -> None:
        self.discover_calls = 0
        self.fetch_calls = 0

    @property
    def capabilities(self):
        return T_INVEST_CAPABILITIES

    def discover_candidates(
        self,
        *,
        query: str | None = None,
        provider_instrument_id: str | None = None,
        isin: str | None = None,
        instrument_kind: InstrumentType | None = None,
    ) -> DiscoverResult:
        self.discover_calls += 1
        if provider_instrument_id != SYNTHETIC_UID:
            return DiscoverResult(
                status=QuoteStatus.UNAVAILABLE,
                message="synthetic identity was not found",
            )
        identity = MarketIdentity(
            provider="t_invest",
            provider_instrument_id=SYNTHETIC_UID,
            provider_venue_id=None,
        )
        return DiscoverResult(
            status=QuoteStatus.OK,
            candidates=(
                DiscoverCandidate(
                    identity=identity,
                    instrument_kind=InstrumentType.STOCK,
                    name="Synthetic mapped stock",
                    ticker="SYNM",
                ),
            ),
        )

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteSuccess:
        self.fetch_calls += 1
        return QuoteSuccess(
            identity=identity,
            instrument_kind=InstrumentType.STOCK,
            raw_price="123.45",
            raw_price_basis=RawPriceBasis.CASH_PER_UNIT,
            proposed_price_kopecks=PROPOSED_KOPECKS,
            price_date=target_date,
            quote_kind=QuoteKind.HISTORY,
            fetched_at_utc=datetime(2031, 5, 31, 12, 0, tzinfo=UTC),
            freshness_status=QuoteStatus.OK,
        )

    def fetch_quotes(self, items: list[tuple[MarketIdentity, date]]) -> list[QuoteSuccess]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]


def create_browser_app():
    root = Path(__file__).resolve().parents[2]
    directory = Path(mkdtemp(prefix="hermes-quote-mapping-synthetic-"))
    database = create_database(directory / "synthetic.db")
    Base.metadata.create_all(database.engine)
    with database.session_factory() as session:
        month = create_reporting_month(session, year=2031, month=5, snapshot_date=TODAY)
        account = create_account(
            session,
            name="Synthetic broker",
            account_type=AccountType.BROKERAGE,
        )
        instrument = create_instrument(
            session,
            name="Synthetic unmapped",
            instrument_type=InstrumentType.STOCK,
        )
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity="2.000000",
            average_cost_per_unit="100.00",
            market_price_per_unit="101.00",
            price_date=TODAY,
        )
    application = create_app(
        database,
        static_dir=root / "frontend" / "dist",
        market_data_provider=SyntheticQuoteProvider(),
    )
    application.state.quote_preview_clock = lambda: TODAY
    return application
