"""Review tripwire for derived investment semantics; never a runtime dependency."""

import hashlib
from pathlib import Path

from hermes_finance.services import source_investment_proofs as proofs

# Keep the semantic module list here only. Include new helpers when extracting
# any parser, classification, payout-linking, Decimal/money/XIRR or evidence logic.
# Whole files deliberately require review even for nonsemantic edits within them.
SEMANTIC_MODULES = (
    "domain/instrument_return.py",
    "domain/money_security.py",
    "domain/monthly_return_chain.py",
    "domain/source_money_classifications.py",
    "domain/xirr.py",
    "domain/xirr_roots.py",
    "services/mybroker_money_candidates.py",
    "services/source_investment_proofs.py",
    "services/source_instrument_events.py",
    "services/source_instrument_returns.py",
    "services/source_money_classifications.py",
    "services/source_monthly_returns.py",
    "services/source_report_preview.py",
    "services/source_return_evidence.py",
    "services/source_return_proofs.py",
    "statement_import/investment_money.py",
    "statement_import/investment_report.py",
    "statement_import/money.py",
    "statement_import/mybroker.py",
    "statement_import/mybroker_draft_structure.py",
    "statement_import/mybroker_empty_money.py",
    "statement_import/mybroker_metadata.py",
    "statement_import/mybroker_return_structure.py",
)

# Pin the revision alongside the digest so bumping either alone fails the guard.
# V4 adds exact payout receipt attribution; compatibility with older proofs
# requires independent review and unchanged account-proof dependencies.
SEMANTICS_PIN = (
    "source_investment_semantics_v4",
    "ec6afa7c96d3b7a0e2d6037ae48d092655dcfd40709e2c58943abe118bd3b3bb",
)


def test_investment_semantic_modules_match_revision_pin():
    package = Path(proofs.__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for name in SEMANTIC_MODULES:
        digest.update(name.encode("utf-8") + b"\0")
        # Git checkouts can use LF or CRLF on Windows; normalize only newlines.
        digest.update((package / name).read_text(encoding="utf-8").encode("utf-8") + b"\0")
    actual = (proofs.SEMANTICS_REVISION, digest.hexdigest())
    assert actual == SEMANTICS_PIN, (
        "Investment semantic modules changed: bump SEMANTICS_REVISION and update "
        f"SEMANTICS_PIN after reviewing the semantic module list. Actual: {actual!r}"
    )
