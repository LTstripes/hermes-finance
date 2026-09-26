"""Coverage metadata for the known liquid-capital subtotal."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class PortfolioSourceCoverage:
    status: Literal["complete", "partial", "unavailable"]
    reason_codes: tuple[str, ...] = ()
    missing_account_ids: tuple[int, ...] = ()
