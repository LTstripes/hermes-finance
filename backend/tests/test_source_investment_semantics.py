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
    "services/source_custody_compat.py",
    "services/source_money_classifications.py",
    "services/source_redemption_evidence.py",
    "services/source_monthly_internal_evidence.py",
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
# V5 carries dated redemption quantity and scopes structure-only confirmations;
# compatibility with older proofs
# requires independent review and unchanged account-proof dependencies.
SEMANTICS_PIN = (
    "source_investment_semantics_v6",
    "e86d6418264530382ce95ef43dfa6252a7b19edf18d114221ed5e3e8bdeb89ca",
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


def test_custody_compatibility_is_bound_to_reviewed_implementation():
    from hermes_finance.services import source_custody_compat, source_return_proofs

    actual = hashlib.sha256(Path(source_return_proofs.__file__).read_bytes()).hexdigest()
    assert actual == source_custody_compat.CURRENT_CUSTODY_CODE_SHA256


# A grammar/meaning change must advance the scoped custody revision; an ordinary
# release must not invalidate its immutable source evidence merely by file bytes.
CUSTODY_MODULES = (
    "services/source_return_proofs.py",
    "statement_import/mybroker.py",
    "statement_import/mybroker_return_structure.py",
    "statement_import/mybroker_draft_structure.py",
    "statement_import/mybroker_metadata.py",
)
CUSTODY_PIN = (
    "source_custody_structure_v2",
    "722f7f91e3edeaa5431657cdbe083709abe37f393c48d9856b0afe20e297da1a",
)


def test_scoped_custody_semantics_match_reviewed_grammar():
    from hermes_finance.services import source_return_proofs

    package = Path(proofs.__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for name in CUSTODY_MODULES:
        digest.update(name.encode() + b"\0")
        digest.update((package / name).read_text(encoding="utf8").encode() + b"\0")
    assert (source_return_proofs.STRUCTURE_SEMANTICS, digest.hexdigest()) == CUSTODY_PIN
