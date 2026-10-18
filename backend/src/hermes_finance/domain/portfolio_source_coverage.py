"""Coverage metadata for the known liquid-capital subtotal."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class PortfolioSourceCoverage:
    status: Literal["complete", "partial", "unavailable"]
    reason_codes: tuple[str, ...] = ()
    missing_account_ids: tuple[int, ...] = ()
    # Separate from the historical account-presence claim above.
    source_account_financial_coverage: dict | None = None
