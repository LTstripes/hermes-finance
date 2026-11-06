"""Ephemeral clean projection of fully proved same-issue REPO pairs.

Native observations and legacy event/receipt semantics remain unchanged.
"""

from collections import defaultdict
from copy import copy
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

from hermes_finance.domain.clean_instrument_return import clean_trade_date, cost_only_trade
from hermes_finance.domain.instrument_return import Coverage, InstrumentEvent
from hermes_finance.services.source_report_preview import _repo_pair_blockers
from hermes_finance.services.source_trade_identity import repo_return_identities
from hermes_finance.statement_import.mybroker import PROVIDER, digest


def _instant(event):
    try:
        value = datetime.fromisoformat(event.trade_time)
    except (ValueError, TypeError):
        return None
    if value.tzinfo is not None or ("T" not in event.trade_time and " " not in event.trade_time):
        return None
    return value


def _missing_fee_only(event, trade):
    try:
        amount = Decimal(trade["core"]["trade_amount"])
        quantity = Decimal(trade["core"]["quantity"])
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return False
    return (
        (trade.get("bank_commission") is None or trade.get("accrued_interest") is None)
        and amount.is_finite()
        and amount >= 0
        and quantity.is_finite()
        and quantity != 0
        and event.quantity_delta == quantity
        and event.attribution_basis == "native_trade_settlement"
        and {"repo_trade_unsupported", "trade_components_missing"} <= set(event.reason_codes)
        and set(event.reason_codes)
        <= {
            "repo_trade_unsupported",
            "trade_components_missing",
            "trade_missing_settlement",
            "depository_settlement_missing",
        }
    )


def without_proven_closed_repo(analysis, views, isin):
    """Return a disposable copy only if every affected REPO is fully proven."""
    repo_events = [e for e in analysis.events if "repo_trade_unsupported" in e.reason_codes]
    if not repo_events:
        return analysis
    if any(
        e.isin != isin
        or not e.current
        or not e.native_identity
        or not e.native_identity.startswith("repo:")
        or not set(e.reason_codes) <= {"repo_trade_unsupported", "trade_components_missing"}
        for e in repo_events
    ):
        return analysis
    ids = {e.native_identity for e in repo_events}
    if len(ids) != len(repo_events):
        return analysis
    native_ids = {e.native_ids for e in repo_events}
    tokens = {
        (event.native_source_account, event.native_ids[0])
        for event in repo_events
        if len(event.native_ids) == 1
    }
    for view in views:
        counts = defaultdict(int)
        for trade in view["document"].get("trades", ()):
            for token in trade.get("ids", ()):
                key = (trade.get("core", {}).get("source_account"), token)
                if key not in tokens:
                    continue
                counts[key] += 1
                if (
                    trade.get("section") != "completed"
                    or not trade.get("repo_observed")
                    or trade.get("core", {}).get("isin") != isin
                ):
                    return analysis
        if any(count != 1 for count in counts.values()):
            return analysis

    # Witnessed identity and reciprocal partner/leg facts are reconstructed
    # from retained inventory, not from a guessed B-number match.
    records, conflicted = {}, set()
    witnessed_by_view = []
    for view in views:
        identities = repo_return_identities(view)
        witnessed_by_view.append((view, {item[0] for item in identities.values()}))
        for trade in view["document"].get("trades", ()):
            if not trade.get("repo_observed") or trade.get("section") != "completed":
                continue
            witness = identities.get(trade.get("ordinal"))
            if witness is None:
                if tuple(trade.get("ids", ())) in native_ids:
                    return analysis
                continue
            identity, (partner, leg_digest) = witness
            leg = {digest("репо ч.1"): "репо ч.1", digest("репо ч.2"): "репо ч.2"}.get(leg_digest)
            if leg is None:
                return analysis
            record = {**trade, "repo_partner": partner, "repo_leg": leg}
            signature = (
                trade["core"],
                trade.get("settlement_date"),
                trade.get("depo_settlement_date"),
                trade.get("settlement_time"),
                trade.get("bank_commission"),
                trade.get("accrued_interest"),
                trade.get("face_value"),
                partner,
                leg,
            )
            if identity in records and records[identity][1] != signature:
                conflicted.add(identity)
            else:
                records[identity] = (record, signature)
    if ids & conflicted or not ids <= records.keys():
        return analysis
    selected = [records[key][0] for key in ids]
    # Every covering original must contain the same witnessed occurrence.
    for identity in ids:
        trade = records[identity][0]
        execution = date.fromisoformat(trade["core"]["trade_time"][:10])
        settlement = date.fromisoformat(trade["settlement_date"])
        for view, witnessed in witnessed_by_view:
            if (
                date.fromisoformat(view["covered_from"]) <= execution
                and settlement <= date.fromisoformat(view["covered_to"])
                and identity not in witnessed
            ):
                return analysis
    # Partner must be one of the exact event identities, not merely another
    # B-number somewhere in the account or an overlapping original.
    if any(
        "repo:" + digest([PROVIDER, t["core"]["source_account"], t["repo_partner"]]) not in ids
        for t in selected
    ):
        return analysis
    try:
        if _repo_pair_blockers(selected, analysis.opening_date, analysis.closing_date):
            return analysis
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return analysis

    by_id = {e.native_identity: e for e in repo_events}
    for identity in ids:
        trade = records[identity][0]
        event = by_id[identity]
        if (
            event.native_ids != tuple(trade["ids"])
            or event.native_source_account != trade["core"]["source_account"]
            or event.isin != trade["core"]["isin"]
            or event.quantity_delta != Decimal(trade["core"]["quantity"])
            or event.cash_settlement_date is None
            or event.depository_settlement_date is None
            or event.cash_settlement_date.isoformat() != trade["settlement_date"]
            or event.depository_settlement_date.isoformat() != trade["depo_settlement_date"]
            or (
                "trade_components_missing" in event.reason_codes
                and not _missing_fee_only(event, trade)
            )
        ):
            return analysis
        if trade["repo_leg"] == "репо ч.1":
            partner = "repo:" + digest(
                [PROVIDER, trade["core"]["source_account"], trade["repo_partner"]]
            )
            first, second = _instant(event), _instant(by_id[partner])
            if first is None or second is None or first >= second:
                return analysis

    changing = [
        e for e in analysis.events if e.isin == isin and e.kind in {"BUY", "SELL", "REDEMPTION"}
    ]
    if analysis.opening.quantity is None or analysis.closing.quantity is None:
        return analysis
    by_execution_day, by_delivery = defaultdict(list), defaultdict(list)
    for event in changing:
        if (
            event.kind == "REDEMPTION"
            or event.quantity_delta is None
            or event.depository_settlement_date is None
        ):
            return analysis
        if not event.current or (
            event not in repo_events and not (event.counted or cost_only_trade(event))
        ):
            return analysis
        instant = _instant(event)
        if instant is None or instant.date() > event.depository_settlement_date:
            return analysis
        by_execution_day[instant.date()].append(instant)
        by_delivery[event.depository_settlement_date].append(event.quantity_delta)
    if any(len(times) != len(set(times)) for times in by_execution_day.values()):
        return analysis
    # Settlement dates do not prove intraday custody order. Require holdings to
    # stay nonnegative even if same-day outgoing legs happen before incoming.
    with localcontext() as context:
        context.prec = 200
        held = analysis.opening.quantity
        for day in sorted(by_delivery):
            changes = by_delivery[day]
            if held + sum((q for q in changes if q < 0), Decimal(0)) < 0:
                return analysis
            held += sum(changes, Decimal(0))
        if held != analysis.closing.quantity:
            return analysis

    # Exact REPO keys are excluded only from this temporary clean projection.
    # Every original event remains in the regular source/receipt read.
    remaining = tuple(e for e in analysis.events if e not in repo_events)
    for event in remaining:
        if event.isin == isin and event.kind in {"BUY", "SELL"}:
            day = clean_trade_date(event)
            if (
                day is None
                or event.depository_settlement_date is None
                or not (
                    analysis.opening_date < day <= analysis.closing_date
                    and analysis.opening_date
                    < event.depository_settlement_date
                    <= analysis.closing_date
                )
            ):
                return analysis
    coverage = copy(analysis.coverage)
    for name, ignored in (
        ("events", {"repo_trade_unsupported"}),
        (
            "quantity",
            {
                "quantity_events_incomplete",
                "quantity_reconciliation_mismatch",
                "cross_boundary_settlement",
            },
        ),
    ):
        old = coverage[name]
        if (
            name == "events"
            and any("trade_components_missing" in e.reason_codes for e in repo_events)
            and not any("trade_components_missing" in e.reason_codes for e in remaining)
        ):
            ignored = ignored | {"trade_components_missing"}
        reasons = tuple(reason for reason in old.reason_codes if reason not in ignored)
        coverage[name] = Coverage(not reasons and (old.complete or bool(old.reason_codes)), reasons)
    return replace(analysis, events=remaining, coverage=coverage)


class _RepoBarrierCoverage(dict):
    """Private read-only barrier; never a new API or persisted source field."""

    def __init__(self, *args, barrier=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fifo_repo_barrier = barrier
        source = args[0] if args else None
        self.fee_only_bridge = getattr(source, "fee_only_bridge", False)
        self.unresolved_cost_only = getattr(source, "unresolved_cost_only", False)


def saved_proof_repo_evidence_complete(session, source_account, start, end, views, isin):
    """Validate a matching current receipt's REPO ordinals without modifying it."""
    from hermes_finance.services.source_investment_proofs import _report_rows, read_reports

    if len(views) != 1:
        return True  # The available-period reader uses raw originals for overlaps.
    reports = read_reports(
        session, source_account=source_account, opening_date=start, closing_date=end
    )
    current = {report["proof_id"] for report in reports if report["status"] == "current"}
    for row, plan in _report_rows(session, source_account):
        if (
            row.id not in current
            or plan.get("source_sha256") != views[0]["document"]["document_sha256"]
        ):
            continue
        trades = [
            t
            for t in views[0]["document"].get("trades", ())
            if t.get("repo_observed") and t.get("core", {}).get("isin") == isin
        ]
        if not trades:
            return True
        identities = repo_return_identities(views[0])
        legs = plan.get("native", {}).get("repo_legs", [])
        if not isinstance(legs, list):
            return False
        for trade in trades:
            ordinal = trade.get("ordinal")
            matches = [
                entry
                for entry in legs
                if isinstance(entry, list) and len(entry) == 3 and entry[0] == ordinal
            ]
            witness = identities.get(ordinal)
            if len(matches) != 1 or witness is None:
                return False
            partner, leg = witness[1]
            if matches[0][1] != partner or digest(matches[0][2]) != leg:
                return False
        return True
    return True


def _closed_historical_repo_tokens(views, account, isin, opening):
    """Prove reciprocal, identical witnessed occurrences ended before opening."""
    occurrences = defaultdict(list)
    for view in views:
        identities = repo_return_identities(view)
        for trade in view["document"].get("trades", ()):
            if trade.get("core", {}).get("source_account") != account:
                continue
            for token in trade.get("ids", ()):
                occurrences[token].append((view, trade, identities.get(trade.get("ordinal"))))
    closed = set()

    def identical(entries):
        if not entries or len({id(view) for view, _, _ in entries}) != len(entries):
            return False
        signatures = []
        for _, trade, witness in entries:
            if (
                not witness
                or trade.get("section") != "completed"
                or trade.get("state") != "settled"
            ):
                return False
            signatures.append(
                digest(
                    [
                        trade.get("core"),
                        trade.get("ids"),
                        trade.get("settlement_date"),
                        trade.get("depo_settlement_date"),
                        trade.get("settlement_time"),
                        trade.get("bank_commission"),
                        trade.get("accrued_interest"),
                        trade.get("face_value"),
                        witness,
                    ]
                )
            )
        return len(set(signatures)) == 1

    for own, entries in occurrences.items():
        if not identical(entries):
            continue
        view, trade, witness = entries[0]
        if not witness or trade.get("core", {}).get("isin") != isin:
            continue
        partner, leg_digest = witness[1]
        peers = occurrences.get(partner, ())
        if not identical(peers):
            continue
        peer, peer_witness = peers[0][1:]
        leg_names = {digest("репо ч.1"): "репо ч.1", digest("репо ч.2"): "репо ч.2"}
        try:
            first = {**trade, "repo_partner": partner, "repo_leg": leg_names[leg_digest]}
            second = {
                **peer,
                "repo_partner": peer_witness[1][0],
                "repo_leg": leg_names[peer_witness[1][1]],
            }
            if _repo_pair_blockers([first, second], date.min, opening):
                continue
            times = [datetime.fromisoformat(t["core"]["trade_time"]) for t in (first, second)]
            if any(t.tzinfo is not None for t in times):
                continue
            if any(
                instant.date() > date.fromisoformat(trade[field])
                for trade, instant in zip((first, second), times, strict=True)
                for field in ("settlement_date", "depo_settlement_date")
            ):
                continue
            earlier, later = times if first["repo_leg"] == "репо ч.1" else times[::-1]
            if earlier >= later:
                continue
            for token, items in ((own, entries), (partner, peers)):
                member_views = {id(item[0]) for item in items}
                observed_trade = items[0][1]
                execution = date.fromisoformat(observed_trade["core"]["trade_time"][:10])
                settlement = max(
                    date.fromisoformat(observed_trade[field])
                    for field in ("settlement_date", "depo_settlement_date")
                )
                if any(
                    date.fromisoformat(v["covered_from"]) <= execution
                    and settlement <= date.fromisoformat(v["covered_to"])
                    and id(v) not in member_views
                    for v in views
                ):
                    break
            else:
                closed.update((own, partner))
        except (ValueError, TypeError, KeyError, ArithmeticError):
            continue
    return closed


def clean_and_purchase_repo_projections(analysis, views, isin, *, allow_pair=True):
    """Prove a closed pair or preserve only FIFO facts before an uncertain REPO."""
    accounts = {
        event.native_source_account
        for event in analysis.events
        if event.isin == isin and event.native_source_account
    }
    if len(accounts) != 1:
        if any(
            trade.get("repo_observed") and trade.get("core", {}).get("isin") == isin
            for view in views
            for trade in view["document"].get("trades", ())
        ):
            return analysis, _barrier_analysis(
                analysis, analysis.opening_date + timedelta(days=1), views
            )
        return analysis, analysis
    account = next(iter(accounts))
    historical = _closed_historical_repo_tokens(views, account, isin, analysis.opening_date)
    source_trades = [
        trade
        for view in views
        for trade in view["document"].get("trades", ())
        if trade.get("repo_observed")
        and trade.get("core", {}).get("isin") == isin
        and trade.get("core", {}).get("source_account") == account
        and not (len(trade.get("ids", ())) == 1 and trade["ids"][0] in historical)
    ]
    relevant = []
    for trade in source_trades:
        try:
            execution = date.fromisoformat(trade["core"]["trade_time"][:10])
        except (ValueError, TypeError, KeyError):
            # An undated obligation could affect the entire selected interval.
            return analysis, _barrier_analysis(
                analysis, analysis.opening_date + timedelta(days=1), views
            )
        # A prior leg can represent an obligation still open at the boundary.
        # Do not infer that it was closed merely from its own settlement date.
        if execution <= analysis.closing_date:
            relevant.append(trade)
    if not relevant:
        return analysis, analysis
    barrier = min(date.fromisoformat(t["core"]["trade_time"][:10]) for t in relevant)
    for trade in relevant:
        try:
            barrier = min(barrier, date.fromisoformat(trade["depo_settlement_date"]))
        except (ValueError, TypeError, KeyError):
            barrier = analysis.opening_date + timedelta(days=1)
    barrier = max(barrier, analysis.opening_date + timedelta(days=1))
    if not allow_pair:
        return analysis, _barrier_analysis(analysis, barrier, views)
    raw_repo = [
        event for event in analysis.events if "repo_trade_unsupported" in event.reason_codes
    ]
    candidate = analysis
    if not raw_repo:
        # The investment report projects REPO financing at account scope, so
        # its ordinary InstrumentAnalysis has no REPO events. Reconstruct only
        # ephemeral custody witnesses from the same current source inventory.
        synthetic, seen = [], set()
        for view in views:
            identities = repo_return_identities(view)
            for trade in view["document"].get("trades", ()):
                if trade not in relevant or trade.get("section") != "completed":
                    continue
                witness = identities.get(trade.get("ordinal"))
                if witness is None:
                    return analysis, _barrier_analysis(analysis, barrier, views)
                identity = witness[0]
                if identity in seen:
                    continue
                seen.add(identity)
                try:
                    quantity = Decimal(trade["core"]["quantity"])
                    settlement = date.fromisoformat(trade["settlement_date"])
                    delivery = date.fromisoformat(trade["depo_settlement_date"])
                except (ValueError, TypeError, KeyError, ArithmeticError):
                    return analysis, _barrier_analysis(analysis, barrier, views)
                synthetic.append(
                    InstrumentEvent(
                        event_key="clean-ephemeral:" + identity,
                        provider=PROVIDER,
                        native_source_account=trade["core"]["source_account"],
                        isin=isin,
                        kind="BUY" if quantity > 0 else "SELL",
                        source_references=(),
                        event_date=settlement,
                        native_identity=identity,
                        native_ids=tuple(trade["ids"]),
                        execution_date=date.fromisoformat(trade["core"]["trade_time"][:10]),
                        trade_time=trade["core"]["trade_time"],
                        cash_settlement_date=settlement,
                        depository_settlement_date=delivery,
                        quantity_delta=quantity,
                        counted=False,
                        reason_codes=("repo_trade_unsupported",),
                    )
                )
        if not synthetic:
            return analysis, _barrier_analysis(analysis, barrier, views)
        candidate = replace(analysis, events=(*analysis.events, *synthetic))
    proven = without_proven_closed_repo(candidate, views, isin)
    if proven is not candidate:
        return proven, proven
    return analysis, _barrier_analysis(analysis, barrier, views)


def _barrier_analysis(analysis, barrier, views):
    """Isolate unknown REPO from FIFO only; keep unrelated blockers intact."""
    proven_local = set()
    for view in views:
        identities = repo_return_identities(view)
        for trade in view["document"].get("trades", ()):
            witness = identities.get(trade.get("ordinal"))
            if not witness:
                continue
            for event in analysis.events:
                reasons = set(event.reason_codes)
                allowed = {
                    "repo_trade_unsupported",
                    "trade_components_missing",
                    "trade_missing_settlement",
                    "depository_settlement_missing",
                    "trade_currency_unsupported",
                }
                if (
                    event.native_identity == witness[0]
                    and event.native_ids == tuple(trade.get("ids", ()))
                    and event.native_source_account == trade["core"]["source_account"]
                    and event.isin == trade["core"]["isin"]
                    and event.current
                    and event.attribution_basis == "native_trade_settlement"
                    and "repo_trade_unsupported" in reasons
                    and reasons <= allowed
                    and (
                        "trade_components_missing" not in reasons or _missing_fee_only(event, trade)
                    )
                    and (
                        "trade_missing_settlement" not in reasons
                        or trade.get("settlement_date") is None
                    )
                    and (
                        "depository_settlement_missing" not in reasons
                        or trade.get("depo_settlement_date") is None
                    )
                ):
                    proven_local.add(event.event_key)
    repo_events = [
        e
        for e in analysis.events
        if set(e.reason_codes) == {"repo_trade_unsupported"} or e.event_key in proven_local
    ]
    remaining = tuple(e for e in analysis.events if e not in repo_events)
    coverage = _RepoBarrierCoverage(analysis.coverage, barrier=barrier)
    for name, ignored in (
        (
            "events",
            {"repo_trade_unsupported", "repo_position_open_at_boundary", "repo_pair_unproven"},
        ),
        (
            "quantity",
            {
                "quantity_events_incomplete",
                "quantity_reconciliation_mismatch",
                "cross_boundary_settlement",
                "repo_position_open_at_boundary",
                "repo_pair_unproven",
            },
        ),
    ):
        old = coverage[name]
        for reason in {
            "trade_components_missing",
            "trade_missing_settlement",
            "depository_settlement_missing",
            "trade_currency_unsupported",
        }:
            if any(
                e.event_key in proven_local and reason in e.reason_codes for e in repo_events
            ) and not any(reason in event.reason_codes for event in remaining):
                ignored = ignored | {reason}
        reasons = tuple(reason for reason in old.reason_codes if reason not in ignored)
        coverage[name] = Coverage(not reasons and (old.complete or bool(old.reason_codes)), reasons)
    return replace(analysis, events=remaining, coverage=coverage)
