"""Read-only source-intake provisional estimate; no financial writer or receipt.

The journal owns recognized, original-bound observations.  This service verifies
the exact original, reuses those observations and the existing MyBroker parser
patterns, and builds an ephemeral scenario.  It never calls Preview/Apply,
creates H2/Money evidence, changes can_apply/Close or persists a number.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, DecimalException, localcontext
from xml.etree import ElementTree as ET

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.broker_statement_provisional import (
    MAX_CANDIDATES,
    METHOD,
    VERSION,
    ProvisionalAssumptions,
    ProvisionalCash,
    ProvisionalContext,
    ProvisionalFlow,
    ProvisionalJournal,
    ProvisionalKnownPayout,
    ProvisionalObserved,
    ProvisionalPosition,
    ProvisionalRequirement,
    evaluate_context,
)
from hermes_finance.persistence import Account, BrokerIdentityMapping, SourceIntakeOriginal
from hermes_finance.services import source_intake
from hermes_finance.services.mybroker_money_candidates import _narratives, _pattern
from hermes_finance.statement_import.mybroker import (
    MONEY_LINKAGE,
    MyBrokerError,
    digest,
    parse_mybroker,
)

SOURCE_KEYS = (
    "provider",
    "parser",
    "document_sha256",
    "filename_account",
    "covered_from",
    "covered_to",
    "positions",
    "rub_money",
    "endpoint_basis",
    "endpoint_blockers",
    "endpoint_conflicts",
    "trades",
    "money",
    "section_inventory",
    "syntax_blockers",
)
ENDPOINT_CODES = frozenset(
    {
        "provisional_endpoint_basis_unsupported",
        "provisional_endpoint_value_unavailable",
        "provisional_endpoint_value_invalid",
        "provisional_rub_cash_unavailable",
        "provisional_rub_cash_incomplete",
        "provisional_rub_cash_ambiguous",
        "provisional_rub_cash_negative",
        "provisional_position_row_unclassified",
        "provisional_no_observed_totals",
        "provisional_quantity_invalid",
        "provisional_quantity_value_conflict",
    }
)
ACCOUNT_CODES = frozenset(
    {
        "provisional_filename_account_unproven",
        "provisional_source_account_unproven",
        "provisional_multiple_source_accounts",
    }
)
BASE_LIMITATIONS = (
    "Предварительная оценка, не факт: не S3, не Close, не XIRR/TWRR и не финансовый Apply.",
    "Наблюдаемые величины — нативные EOD-оценки брокера; сценарий не подтверждает экономическую полноту периода.",
    "Стоимость всех распознанных бумаг и отдельная RUB cash-строка суммируются один раз; cash не дублируется.",
    "Внешние движения: только явно выбранные распознанные входящие кандидаты; другие пополнения и выводы не моделируются и остаются неизвестными.",
    "Комиссии, НКД, купоны, расчёты по сделкам и pending не приравниваются к нулю и не дают отдельного потока инвестора в этой модели.",
    "Процент не аннулизирован и относится только к фактическому периоду; годовая доходность и доверительный интервал не рассчитываются.",
    "Валюта — RUB как валюта нативного отчёта и отдельной cash-строки; отдельное доказательство валюты каждой бумаги не заявляется.",
)


class ProvisionalStaleError(ValueError):
    """The exact original or context no longer matches the displayed journal."""


def _minor(value) -> int | None:
    """Exact source decimal to integer kopecks; None for missing or unrepresentable."""
    if value is None:
        return None
    try:
        with localcontext() as context:
            context.prec = 100
            minor = Decimal(value) * 100
        if (
            not minor.is_finite()
            or minor != minor.to_integral_value()
            or not -(2**63) <= minor <= 2**63 - 1
        ):
            return None
        return int(minor)
    except (DecimalException, ValueError, TypeError):
        return None


def _source_value(value) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _matching_source(stored: dict, document: bytes, filename: str) -> dict:
    """Reproduce the journal grammar without trusting a later financial receipt."""
    for version in (MONEY_LINKAGE, None):
        try:
            fresh = parse_mybroker(document, filename, money_linkage_version=version)
        except MyBrokerError:
            continue
        if all(fresh.get(key) == stored.get(key) for key in SOURCE_KEYS):
            return fresh
    raise ProvisionalStaleError("provisional_source_parser_changed")


def _account_alias_reasons(session, native_accounts, rows, account_id) -> set[str]:
    reasons: set[str] = set()
    aliases = set(native_accounts)
    aliases.add(rows.get("filename_account"))
    aliases.update(row.get("source_account") for row in rows.get("positions", []))
    aliases.update(row.get("source_account") for row in rows.get("rub_money", []))
    aliases.update(row.get("source_account") for row in rows.get("money", []))
    aliases.update(row.get("source_account") for row in rows.get("trades", []))
    aliases.discard(None)
    for alias in sorted(aliases):
        mappings = list(
            session.scalars(
                select(BrokerIdentityMapping).where(
                    BrokerIdentityMapping.provider == rows.get("provider"),
                    BrokerIdentityMapping.subject_kind == "account",
                    BrokerIdentityMapping.provider_identity == alias,
                )
            )
        )
        effective = [mapping for mapping in mappings if mapping.status == "effective"]
        if len(effective) > 1 or any(
            mapping.hermes_target_id != account_id for mapping in effective
        ):
            reasons.add("provisional_multiple_source_accounts")
        elif not effective:
            reasons.add("provisional_source_account_unproven")
    return reasons


@coherent_read_operation
def read_context(
    session,
    *,
    intake_id: int,
    original: bytes,
    filename: str,
    expected_manifest_digest: str,
):
    view = source_intake.read_intake(session, intake_id)
    original_row = session.get(SourceIntakeOriginal, intake_id, populate_existing=True)
    if original_row is None:
        raise MyBrokerError("source_intake_not_found")
    if (
        hashlib.sha256(original).hexdigest() != original_row.document_sha256
        or len(original) != original_row.byte_length
        or digest(filename) != original_row.filename_digest
    ):
        raise ProvisionalStaleError("provisional_original_mismatch")
    if view["manifest_digest"] != expected_manifest_digest:
        raise ProvisionalStaleError("provisional_manifest_stale")
    stored = view["document"]
    fresh = _matching_source(stored, original, filename)
    if fresh["document_sha256"] != original_row.document_sha256 or (
        fresh["covered_from"],
        fresh["covered_to"],
    ) != (original_row.covered_from.isoformat(), original_row.covered_to.isoformat()):
        raise ProvisionalStaleError("provisional_source_parser_changed")

    account_id = view["state"]["account_id"]
    if account_id is None:
        raise MyBrokerError("provisional_account_binding_required")
    account = session.get(Account, account_id, populate_existing=True)
    if (
        account is None
        or account.status != "active"
        or account.account_type not in {"brokerage", "iis"}
    ):
        raise MyBrokerError("provisional_account_unavailable")

    t0 = original_row.covered_from - timedelta(days=1)
    t1 = original_row.covered_to
    hard: set[str] = set()
    limitations = list(BASE_LIMITATIONS)
    positions_raw = stored.get("positions", [])
    rub_raw = stored.get("rub_money", [])
    money_raw = stored.get("money", [])
    trades_raw = stored.get("trades", [])
    native_accounts = json.loads(original_row.native_accounts_json)
    filename_account = stored.get("filename_account")
    if filename_account not in native_accounts:
        hard.add("provisional_filename_account_unproven")
    hard.update(
        _account_alias_reasons(
            session,
            native_accounts,
            {**stored, "filename_account": filename_account},
            account_id,
        )
    )

    if stored.get("endpoint_basis") != {
        "beginning_value": "previous_day_eod",
        "ending_value": "covered_to_eod",
    }:
        hard.add("provisional_endpoint_basis_unsupported")
    for code in stored.get("endpoint_blockers", []):
        if code == "endpoint_beginning_quantity_unavailable":
            limitations.append(
                "Начальное количество по одной или нескольким бумагам отсутствует; "
                "стоимость взята из нативного поля value, количество не участвует в сумме."
            )
        elif code in {
            "endpoint_value_unavailable",
            "rub_money_unavailable",
            "rub_money_incomplete",
            "position_row_unclassified",
        }:
            hard.add(code)
        else:
            hard.add("provisional_endpoint_diagnostic_unmapped")
            hard.add(code)
    for code in stored.get("endpoint_conflicts", []):
        hard.add(code)

    positions: list[ProvisionalPosition] = []
    positions_opening = 0
    positions_closing = 0
    position_values_valid = True
    for row in positions_raw:
        beginning = _minor(row.get("beginning_value"))
        closing = _minor(row.get("ending_value"))
        if (row.get("beginning_value") is not None and beginning is None) or (
            row.get("ending_value") is not None and closing is None
        ):
            hard.add("provisional_endpoint_value_invalid")
            position_values_valid = False
        elif beginning is None or closing is None:
            hard.add("provisional_endpoint_value_unavailable")
            position_values_valid = False
        elif beginning < 0 or closing < 0:
            hard.add("provisional_endpoint_value_invalid")
            position_values_valid = False
        else:
            positions_opening += beginning
            positions_closing += closing
        for quantity_key, value in (
            ("beginning_actual_quantity", beginning),
            ("actual_quantity", closing),
        ):
            raw_quantity = row.get(quantity_key)
            if raw_quantity is None or value is None:
                continue
            try:
                quantity = Decimal(raw_quantity)
            except (DecimalException, ValueError, TypeError):
                hard.add("provisional_quantity_invalid")
                position_values_valid = False
                continue
            if quantity == 0 and value != 0:
                hard.add("provisional_quantity_value_conflict")
                position_values_valid = False
        positions.append(
            ProvisionalPosition(
                source_reference=(f"position:{intake_id}:{row['ordinal']}:{digest(row)}"),
                isin=row["isin"],
                ordinal=row["ordinal"],
                beginning_quantity=_source_value(row.get("beginning_actual_quantity")),
                ending_quantity=_source_value(row.get("actual_quantity")),
                beginning_value=_source_value(row.get("beginning_value")),
                ending_value=_source_value(row.get("ending_value")),
                beginning_value_kopecks=None if beginning is None else str(beginning),
                ending_value_kopecks=None if closing is None else str(closing),
            )
        )

    cash = None
    if len(rub_raw) > 1:
        hard.add("provisional_rub_cash_ambiguous")
    elif not rub_raw:
        hard.add("provisional_rub_cash_unavailable")
    else:
        row = rub_raw[0]
        beginning = _minor(row.get("beginning_amount"))
        closing = _minor(row.get("ending_amount"))
        if beginning is None or closing is None:
            hard.add("provisional_rub_cash_incomplete")
        elif beginning < 0 or closing < 0:
            hard.add("provisional_rub_cash_negative")
        else:
            cash = ProvisionalCash(
                source_reference=f"cash:{intake_id}:{row['ordinal']}:{digest(row)}",
                beginning_amount=_source_value(row.get("beginning_amount")),
                ending_amount=_source_value(row.get("ending_amount")),
                beginning_kopecks=str(beginning),
                ending_kopecks=str(closing),
            )
    if not positions and cash is None:
        hard.add("provisional_no_observed_totals")

    endpoint_broken = bool(hard & ENDPOINT_CODES)
    account_broken = bool(hard & ACCOUNT_CODES)
    total_opening = total_closing = reported_change = None
    if not endpoint_broken and not account_broken and cash is not None:
        total_opening = positions_opening + int(cash.beginning_kopecks)
        total_closing = positions_closing + int(cash.ending_kopecks)
        reported_change = total_closing - total_opening

    payouts: list[ProvisionalKnownPayout] = []
    candidates: list[ProvisionalFlow] = []
    money_refs: list[str] = []
    try:
        narratives = list(_narratives(original))
    except (ET.ParseError, UnicodeError, ValueError) as error:
        raise ProvisionalStaleError("provisional_source_money_inventory_invalid") from error
    if len(narratives) != len(money_raw):
        raise ProvisionalStaleError("provisional_money_inventory_changed")
    unresolved_negative = 0
    unsupported_money = 0
    for row, (operation, narrative, _locator) in zip(money_raw, narratives, strict=True):
        reference = f"money:{intake_id}:money:{row['ordinal']}:{digest(row)}"
        money_refs.append(reference)
        amount = _minor(row.get("amount"))
        kind = _pattern(operation, narrative) if row.get("kind") == "unsupported" else "unsupported"
        if kind in {
            "account_cash_in_candidate",
            "coupon_paid_candidate",
            "trade_paid_nkd_candidate",
        }:
            try:
                event_date = date.fromisoformat(row["date"])
            except (KeyError, TypeError, ValueError):
                hard.add("provisional_money_date_invalid")
                continue
        else:
            event_date = None
        if kind == "account_cash_in_candidate":
            if row.get("currency") != "RUB":
                hard.add("provisional_candidate_currency_unsupported")
            elif amount is None or amount <= 0:
                hard.add("provisional_candidate_amount_invalid")
            elif not t0 < event_date <= t1:
                hard.add("provisional_candidate_date_unmodelled")
            else:
                candidates.append(
                    ProvisionalFlow(
                        source_reference=reference,
                        event_date=event_date,
                        signed_amount_kopecks=str(amount),
                        source_amount=_source_value(row.get("amount")),
                    )
                )
        elif kind in {"coupon_paid_candidate", "trade_paid_nkd_candidate"}:
            payouts.append(
                ProvisionalKnownPayout(
                    source_reference=reference,
                    event_date=event_date,
                    kind=kind,
                    source_amount=_source_value(row.get("amount")),
                    amount_kopecks=(
                        None if amount is None or row.get("currency") != "RUB" else str(amount)
                    ),
                )
            )
        elif row.get("kind") == "unsupported":
            unsupported_money += 1
            if amount is not None and amount < 0:
                unresolved_negative += 1

    if len(candidates) > MAX_CANDIDATES:
        hard.add("provisional_candidate_capacity_exceeded")
    if unsupported_money:
        limitations.append(
            "Нераспознанные Money-проводки не моделируются как внешние движения: "
            f"{unsupported_money} наблюдений, из них отрицательных {unresolved_negative}; "
            "их внешность и влияние остаются неизвестными."
        )

    trade_refs = [f"trade:{intake_id}:{row['ordinal']}:{digest(row)}" for row in trades_raw]
    repo_trades = [row for row in trades_raw if row.get("repo_observed")]
    structural_repo = [
        observation
        for observation in view["observations"]
        if observation["section"] == "structure"
        and "repo_no" in (observation.get("facts", {}).get("native_references") or {})
    ]
    repo_observed = bool(repo_trades or structural_repo)
    repo_refs = list(f"trade:{intake_id}:{row['ordinal']}:{digest(row)}" for row in repo_trades)
    if structural_repo and not repo_trades:
        repo_refs.append(f"structure:{intake_id}:repo_no:{len(structural_repo)}")
    if repo_observed:
        limitations.append(
            "REPO: сценарий условно полагается на "
            "native_totals_include_REPO_as_reported; сумма, кастодиальный и "
            "экономический эффект REPO остаются неизвестными."
        )
    pending = [row for row in trades_raw if row.get("state") == "pending"]
    if pending:
        limitations.append(
            f"Pending-сделки ({len(pending)}) не добавляют отдельного cash или "
            "корректировки в этой модели; их расчётный эффект остаётся неизвестным."
        )
    if payouts:
        limitations.append(
            "Распознанные купоны/НКД показаны отдельно и не добавляются к внешним "
            "движениям повторно; их налоговая/экономическая база остаётся неизвестной."
        )
    if candidates:
        limitations.append(
            "Кандидат — нативная проводка; её внешность для портфеля не доказана, "
            "а дата проводки не доказывает дату банковского списания."
        )

    syntax_blockers = tuple(stored.get("syntax_blockers", []))
    if syntax_blockers:
        limitations.append(
            "Нераспознанные/opaque строки сохранены; их экономический смысл и влияние "
            "на итоги неизвестны. Сценарий условно полагается на нативные итоги брокера."
        )
    if view["exceptions"]:
        limitations.append(
            "Журнал source-intake сохраняет исключения: "
            + ", ".join(view["exceptions"])
            + ". Сценарий не превращает их в финансовый факт."
        )

    native_ref = f"source:{intake_id}:{view['document_sha256']}:{view['manifest_digest']}"
    candidate_refs = tuple(candidate.source_reference for candidate in candidates)
    payout_refs = tuple(payout.source_reference for payout in payouts)
    requirements = [
        ProvisionalRequirement(
            requirement_id="native_basis",
            subject="Нативные EOD-итоги выбранного счёта",
            slot="native_basis",
            source_references=(native_ref,),
            choices=("native_totals_continuously",),
        )
    ]
    for candidate in candidates:
        _, _intake, _section, ordinal, fingerprint = candidate.source_reference.split(":")
        requirements.append(
            ProvisionalRequirement(
                requirement_id=f"candidate:{ordinal}:{fingerprint[:12]}",
                subject=(
                    f"{candidate.event_date.isoformat()} · входящий кандидат · "
                    f"+{candidate.source_amount} RUB"
                ),
                slot="candidate",
                source_references=(candidate.source_reference,),
                choices=(
                    "include_as_account_inflow",
                    "exclude_from_external_schedule",
                ),
            )
        )
    requirements.append(
        ProvisionalRequirement(
            requirement_id="schedule",
            subject="Явный график выбранных внешних движений",
            slot="schedule",
            source_references=candidate_refs,
            choices=("use_displayed_schedule",),
        )
    )
    requirements.append(
        ProvisionalRequirement(
            requirement_id="remaining_crossings",
            subject="Только выбранный счёт и его точный период",
            slot="remaining_crossings",
            source_references=tuple(
                sorted(
                    {
                        native_ref,
                        *candidate_refs,
                        *payout_refs,
                        *money_refs,
                        *trade_refs,
                    }
                )
            ),
            choices=("no_other_account_crossings",),
        )
    )
    if trades_raw or money_raw:
        requirements.append(
            ProvisionalRequirement(
                requirement_id="trades_money_basis",
                subject=(
                    f"Сделки/расчёты/комиссии/НКД/pending: {len(trades_raw)} сделок, "
                    f"{len(money_raw)} Money-проводок"
                ),
                slot="trades_money_basis",
                source_references=tuple(sorted({*trade_refs, *money_refs})),
                choices=("no_additional_flow_or_adjustment",),
            )
        )
    if repo_observed:
        requirements.append(
            ProvisionalRequirement(
                requirement_id="repo_basis",
                subject=(
                    f"REPO: {len(repo_trades) or len(structural_repo)} наблюдений; "
                    "сумма и кастодиальный эффект неизвестны"
                ),
                slot="repo_basis",
                source_references=tuple(sorted(set(repo_refs))),
                choices=("native_totals_include_REPO_as_reported",),
            )
        )
    if syntax_blockers:
        requirements.append(
            ProvisionalRequirement(
                requirement_id="unparsed_basis",
                subject="Нераспознанные разделы: " + ", ".join(syntax_blockers),
                slot="unparsed_basis",
                source_references=tuple(f"syntax:{code}" for code in syntax_blockers),
                choices=("unparsed_rows_reflected_in_native_totals",),
            )
        )

    observed = ProvisionalObserved(
        positions_value_opening_kopecks=(str(positions_opening) if position_values_valid else None),
        cash_opening_kopecks=cash.beginning_kopecks if cash else None,
        total_opening_kopecks=None if total_opening is None else str(total_opening),
        positions_value_closing_kopecks=(str(positions_closing) if position_values_valid else None),
        cash_closing_kopecks=cash.ending_kopecks if cash else None,
        total_closing_kopecks=None if total_closing is None else str(total_closing),
        reported_value_change_kopecks=(None if reported_change is None else str(reported_change)),
        positions=tuple(positions),
        cash=cash,
    )
    journal = ProvisionalJournal(
        intake_id=intake_id,
        head_seq=view["head_seq"],
        manifest_digest=view["manifest_digest"],
        document_sha256=view["document_sha256"],
        parser=stored.get("parser", ""),
        finance_link_present=bool(view["finance_link"]),
        exceptions=tuple(view["exceptions"]),
    )
    payload = dict(
        intake_id=intake_id,
        account_id=account_id,
        t0=t0,
        t1=t1,
        journal=journal,
        observed=observed,
        candidates=tuple(sorted(candidates, key=lambda f: (f.event_date, f.source_reference))),
        known_payouts=tuple(sorted(payouts, key=lambda p: (p.event_date, p.source_reference))),
        required_assumptions=tuple(requirements),
        hard_blockers=tuple(sorted(hard)),
        limitations=tuple(limitations),
    )
    provisional = ProvisionalContext(**payload, context_fingerprint="0" * 64)
    fingerprint = digest(
        {
            "method": METHOD,
            "version": VERSION,
            "context": provisional.model_dump(mode="json", exclude={"context_fingerprint"}),
        }
    )
    return provisional.model_copy(update={"context_fingerprint": fingerprint})


@coherent_read_operation
def evaluate(
    session,
    *,
    assumptions: ProvisionalAssumptions,
    expected_context_fingerprint: str,
    expected_result_fingerprint: str | None = None,
    **source,
):
    context = read_context(session, **source)
    if context.context_fingerprint != expected_context_fingerprint:
        raise ProvisionalStaleError("provisional_context_stale")
    assumptions = assumptions.model_copy(
        update={
            "selections": tuple(
                sorted(assumptions.selections, key=lambda choice: choice.requirement_id)
            )
        }
    )
    result = evaluate_context(context, assumptions)
    if (
        expected_result_fingerprint is not None
        and result.result_fingerprint != expected_result_fingerprint
    ):
        raise ProvisionalStaleError("provisional_result_stale")
    return result
