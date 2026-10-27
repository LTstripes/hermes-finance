"""Bounded source-only partial result and separate accepted deposit receipts.

No dynamic union rate/P&L kernel exists. Do not replace these NULLs with PERF04
bridges, component rates, principal changes or current gold cost gains.
"""

from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import (
    Account,
    BrokerIdentityMapping,
    DepositSnapshot,
    ReportingMonth,
    SourceMoneyClassification,
)
from hermes_finance.services.returns_view import _source_scopes, bounds, metric
from hermes_finance.services.source_money_classifications import is_broker_transfer
from hermes_finance.services.source_monthly_returns import (
    _native_scope,
    _selected_sources,
    read_monthly_returns,
)
from hermes_finance.statement_import.mybroker import PROVIDER

CATEGORIES = ("brokerage", "iis", "deposits", "gold")
RAW_CROSSING_BLOCKERS = {"unparsed_source_rows", "4_Transfers_unsupported", "5_UFSR_unsupported"}


def category_set(value):
    items = value.split(",") if value else []
    if len(items) != len(set(items)) or set(items) - set(CATEGORIES):
        raise ValueError("basket_categories_invalid")
    return [c for c in CATEGORIES if c in items]


def _calendar_cells(start, end):
    cursor = (start + timedelta(days=1)).replace(day=1)
    while cursor <= end:
        following = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        yield cursor - timedelta(days=1), following - timedelta(days=1)
        cursor = following


def _cell(start, end, value=None, reasons=()):
    return {
        "period": bounds(start, end),
        "value_kopecks": None if value is None else str(value),
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def _component(identity, label, category, basis, method, cells):
    return dict(
        id=identity, label=label, category=category, basis=basis, method=method, cells=cells
    )


def _subtotal(components, basis, method):
    cells = [
        cell
        for c in components
        if c["basis"] == basis or (basis == "statements" and c["category"] == "brokerage_iis")
        for cell in c["cells"]
    ]
    values = [int(c["value_kopecks"]) for c in cells if c["value_kopecks"] is not None]
    return dict(
        value_kopecks=str(sum(values)) if values else None,
        covered_cells=len(values),
        total_cells=len(cells),
        method=method,
        reason_codes=list(dict.fromkeys(r for c in cells for r in c["reason_codes"])),
    )


def _sources(session, categories, cells, deposit_accounts):
    canonical = _source_scopes(session)
    groups = sorted(set(canonical.values()))
    selections = {key: _selected_sources(session, key) for key in groups}
    mappings = {}
    for identity, account in session.execute(
        select(
            BrokerIdentityMapping.provider_identity, BrokerIdentityMapping.hermes_account_id
        ).where(
            BrokerIdentityMapping.provider == PROVIDER,
            BrokerIdentityMapping.subject_kind == "account",
            BrokerIdentityMapping.status == "effective",
        )
    ):
        if identity in canonical:
            mappings.setdefault(canonical[identity], set()).add(account)
    mapped_counts = Counter(account for ids in mappings.values() for account in ids)
    original_counts = Counter(o.id for selected, _ in selections.values() for o, _, _ in selected)
    transfer_intakes = {
        row.intake_id
        for row in session.scalars(select(SourceMoneyClassification))
        if row.classification == "internal_transfer"
        or is_broker_transfer(row.operation, row.narrative)
    }
    components, represented, overlaps = [], set(), set()
    for key in groups:
        selected, native = selections[key]
        ids = mappings.get(key, set())
        represented.update(ids)
        overlaps.update(ids & deposit_accounts)
        reasons = []
        if not {"brokerage", "iis"} <= set(categories):
            reasons.append("historical_brokerage_iis_type_unproven")
        if (
            not selected
            or native != {key}
            or any(
                error
                or view is None
                or _native_scope(view["document"]) != {key}
                or original_counts[o.id] != 1
                for o, view, error in selected
            )
        ):
            reasons.append("basket_native_identity_unproven")
        if len(ids) > 1 or any(mapped_counts[a] > 1 for a in ids):
            reasons.append("basket_account_identity_overlap")
        if ids & deposit_accounts:
            reasons.append("basket_account_identity_overlap")
        # Never promote a label/current type/mapping into historical authority.
        monthly = read_monthly_returns(session, source_account=key) if not reasons else None
        rows = (
            {(row.result.opening_date, row.result.closing_date): [] for row in monthly.months}
            if monthly
            else {}
        )
        if monthly:
            for row in monthly.months:
                rows[row.result.opening_date, row.result.closing_date].append(row)
        blocked_ranges = [
            (o.covered_from, o.covered_to)
            for o, view, error in selected
            if not error
            and view
            and (
                o.id in transfer_intakes
                or RAW_CROSSING_BLOCKERS.intersection(view["document"].get("syntax_blockers", []))
            )
        ]
        projected = []
        for start, end in cells:
            codes, value = list(reasons), None
            if monthly:
                matches = rows.get((start, end), [])
                if len(matches) != 1:
                    codes.append(
                        "calendar_month_missing" if not matches else "calendar_month_ambiguous"
                    )
                else:
                    row = matches[0]
                    codes.extend((*row.result.reason_codes, *row.flags))
                    value = row.result.growth_kopecks
                    if value is None:
                        codes.append("calendar_month_unavailable")
                if any(start < f.event_date <= end for f in monthly.flows) or any(
                    left <= end and right > start for left, right in blocked_ranges
                ):
                    value = None
                    codes.append("basket_crossing_reconciliation_unavailable")
            projected.append(_cell(start, end, value, codes))
        components.append(
            _component(
                f"source:{key}",
                key,
                "brokerage_iis",
                "statements",
                "source_no_crossing_calendar_months",
                projected,
            )
        )
    return components, represented, overlaps


def _deposits(session, cells, snapshots, accounts, overlaps):
    months = list(session.scalars(select(ReportingMonth)))
    components = []
    for account_id in sorted(accounts):
        projected = []
        for start, end in cells:
            matching = [
                m
                for m in months
                if (m.period_start, m.period_end) == (start + timedelta(days=1), end)
            ]
            reasons, value = [], None
            if account_id in overlaps:
                reasons.append("basket_account_identity_overlap")
            elif len(matching) != 1 or matching[0].status != "closed":
                reasons.append("calendar_month_missing_or_not_closed")
            else:
                observed = [
                    row
                    for row in snapshots
                    if row.account_id == account_id and row.reporting_month_id == matching[0].id
                ]
                if not observed:
                    reasons.append("deposit_snapshot_missing")
                else:
                    # Canonical distinct placement rows, not product-name heuristics.
                    value = sum(row.actual_interest_received_kopecks for row in observed)
            projected.append(_cell(start, end, value, reasons))
        account = session.get(Account, account_id)
        components.append(
            _component(
                f"deposit:{account_id}",
                account.name,
                "deposits",
                "accepted",
                "deposit_received_interest",
                projected,
            )
        )
    return components


def read_basket(session, *, start, end, categories):
    if start >= end:
        raise ValueError("basket_interval_invalid")
    categories = category_set(categories)
    with coherent_read_snapshot(session):
        cells = list(_calendar_cells(start, end))
        components = []
        snapshots = list(session.scalars(select(DepositSnapshot)))
        deposit_accounts = {row.account_id for row in snapshots}
        accounts = list(session.scalars(select(Account).order_by(Account.id)))
        deposit_accounts.update(a.id for a in accounts if a.account_type in {"deposit", "savings"})
        represented, overlaps = set(), set()
        if {"brokerage", "iis"} & set(categories):
            source, represented, overlaps = _sources(session, categories, cells, deposit_accounts)
            components.extend(source)
            for account in accounts:
                if account.id not in represented and account.account_type in {"brokerage", "iis"}:
                    components.append(
                        _component(
                            f"account:{account.id}",
                            account.name,
                            "brokerage_iis",
                            "unsupported",
                            "accepted_pnl_unavailable",
                            [
                                _cell(a, b, reasons=("accepted_basket_pnl_and_category_unproven",))
                                for a, b in cells
                            ],
                        )
                    )
            if not components:
                components.append(
                    _component(
                        "source:unknown",
                        "Брокерские / ИИС",
                        "brokerage_iis",
                        "unsupported",
                        "source_inventory_unproven",
                        [_cell(a, b, reasons=("source_inventory_unproven",)) for a, b in cells],
                    )
                )
        if "deposits" in categories:
            # Source selection is still examined for overlap when broker boxes are OFF.
            if not ({"brokerage", "iis"} & set(categories)):
                _, _, overlaps = _sources(session, categories, [], deposit_accounts)
            components.extend(_deposits(session, cells, snapshots, deposit_accounts, overlaps))
            if not deposit_accounts:
                components.append(
                    _component(
                        "deposits:unknown",
                        "Депозиты и накопительные",
                        "deposits",
                        "accepted",
                        "deposit_received_interest",
                        [_cell(a, b, reasons=("deposit_inventory_unproven",)) for a, b in cells],
                    )
                )
        if "gold" in categories:
            components.append(
                _component(
                    "gold:unknown",
                    "Физическое золото",
                    "gold",
                    "unsupported",
                    "physical_gold_period_unavailable",
                    [
                        _cell(a, b, reasons=("physical_gold_period_evidence_unavailable",))
                        for a, b in cells
                    ],
                )
            )
        # All readers use calendar cells; incomplete edge months are never admitted.
        for component in components:
            for cell in component["cells"]:
                if cell["period"]["start"] < start or cell["period"]["end"] > end:
                    cell["value_kopecks"] = None
                    cell["reason_codes"].append("partial_calendar_month")
        source = _subtotal(components, "statements", "source_no_crossing_calendar_months")
        deposits = _subtotal(components, "accepted", "deposit_received_interest")
        reasons = ["basket_full_result_unproven"] if categories else ["basket_empty_selection"]
        return dict(
            period=bounds(start, end),
            categories=categories,
            partial=True,
            result_kopecks=None,
            known_partial_subtotal_kopecks=source["value_kopecks"],
            rate=metric(reasons=("selected_basket_rate_model_unavailable",), unit="fraction"),
            reason_codes=reasons,
            source_subtotal=source,
            deposit_received_interest=deposits,
            components=components,
        )
