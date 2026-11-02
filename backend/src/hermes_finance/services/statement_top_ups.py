"""Read-only account/month subtotals from effective broker-money funding proofs.

Account funding is not evidence of money entering the whole liquid capital.
No source coverage or portfolio classification is inferred from these events.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import Account, HistoricalOwnerFlow
from hermes_finance.services import broker_money


@dataclass(frozen=True, slots=True)
class StatementTopUpTotal:
    account_id: int
    year: int
    month: int
    known_top_ups: RubleAmount | None
    accepted_event_count: int
    excluded_event_count: int
    reason_codes: tuple[str, ...]


@coherent_read_operation
def statement_top_up_totals(session: Session) -> tuple[StatementTopUpTotal, ...]:
    """Count each canonical funding target once, using its latest proof only.

    Empty/missing evidence is unavailable, never an attestation of zero activity.
    Replays and corroborating/overlapping statements are not extra cash movements.
    """
    groups: dict[tuple[int, int, int], list] = {}
    for receipt, proof, target in broker_money.latest_proofs(session).values():
        if target["role"] != "account_funding":
            continue
        account = session.get(Account, receipt.account_id)
        if account is None or account.account_type not in {"brokerage", "iis"}:
            continue
        flow = session.get(HistoricalOwnerFlow, target["target_id"])
        # Frozen facts locate a retired/deleted target's exclusion, not its amount.
        facts = target.get("facts") or {}
        day = date.fromisoformat(facts["event_date"])
        key = (receipt.account_id, day.year, day.month)
        group = groups.setdefault(key, [0, 0, 0, set()])
        reasons = broker_money.proof_blockers(session, receipt, proof, target)
        if flow is None or flow.account_id != receipt.account_id or flow.currency != "RUB":
            reasons = [*reasons, "statement_funding_scope_mismatch"]
        if reasons:
            group[2] += 1
            group[3].update(reasons)
        else:
            group[1] += 1
            if flow.direction == "contribution":
                group[0] += flow.boundary_amount_kopecks
    return tuple(
        StatementTopUpTotal(
            account_id=account_id,
            year=year,
            month=month,
            known_top_ups=RubleAmount(total) if accepted else None,
            accepted_event_count=accepted,
            excluded_event_count=excluded,
            reason_codes=tuple(sorted(reasons)),
        )
        for (account_id, year, month), (total, accepted, excluded, reasons) in sorted(
            groups.items()
        )
    )


def export_statement_top_ups(
    session: Session, account_refs: dict[int, str], *, through: tuple[int, int]
) -> dict:
    """Allowlisted projection shared by the compact and recommended AI exports."""
    from hermes_finance.services.ai_analysis_bundle import _metric

    rows = []
    for total in statement_top_up_totals(session):
        if (total.year, total.month) > through or total.account_id not in account_refs:
            continue
        rows.append(
            {
                "account_ref": account_refs[total.account_id],
                "period": {"year": total.year, "month": total.month},
                "period_label": f"{total.year:04d}-{total.month:02d}",
                "period_start": date(total.year, total.month, 1).isoformat(),
                "period_end": date(
                    total.year, total.month, monthrange(total.year, total.month)[1]
                ).isoformat(),
                "known_top_ups": _metric(
                    total.known_top_ups.kopecks if total.known_top_ups is not None else None,
                    source="backend_derived",
                    reason_codes=[
                        *total.reason_codes,
                        "statement_funding_history_completeness_unproven",
                    ],
                ),
                "accepted_event_count": total.accepted_event_count,
                "excluded_event_count": total.excluded_event_count,
                "reason_codes": list(total.reason_codes),
            }
        )
    rows.sort(key=lambda row: (row["period_label"], row["account_ref"]))
    return {
        "source": "broker_money",
        "scope": "investment_account",
        "coverage": "unknown",
        "portfolio_scope": "unknown",
        "reason_codes": ["statement_funding_history_completeness_unproven"],
        "months": rows,
    }
