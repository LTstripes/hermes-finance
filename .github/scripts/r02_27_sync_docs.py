from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, got {count}: {old!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, block: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if block.strip() in text:
        return
    count = text.count(marker)
    if count != 1:
        raise RuntimeError(f"{path}: expected one marker, got {count}: {marker!r}")
    file_path.write_text(text.replace(marker, block + marker, 1), encoding="utf-8")


replace_once(
    "README.md",
    "Основная passive-income цель использует backend forecast monthly total, а не просто фактическую сумму выбранного месяца.",
    "Основная passive-income цель использует rolling average фактического net passive income по закрытым месяцам (до последних 12). Это же фактическое среднее является `Текущим значением` и источником прогресса цели. C04 forecast остаётся отдельной прогнозной метрикой и не подменяет фактический прогресс; при истории короче 12 месяцев UI явно показывает, сколько закрытых месяцев учтено.",
)

replace_once(
    "docs/PROJECT_WIKI.md",
    "Основная passive-income цель использует backend forecast monthly passive income. Прогноз даты достижения не придумывает future growth: если траектории нет, статус остаётся `not_projectable`/локализованным пользовательским сообщением.",
    "Основная passive-income цель использует rolling average фактического net passive income по `closed` reporting months (C03, максимум последние 12) как `current_value` и источник `progress_pct`. C04 forecast остаётся отдельной прогнозной метрикой и не подменяет фактический прогресс. Прогноз даты достижения по-прежнему не придумывает future growth: если траектории нет, статус остаётся `not_projectable`/локализованным пользовательским сообщением. Это уточнение R02-27 сознательно supersede'ит только выбор source metric из R02-12, не меняя exact progress/gap formula.",
)

replace_once(
    "CHANGELOG.md",
    "- optional instrument в новой фактической инвестиционной выплате теперь по умолчанию пуст и сбрасывается после сохранения;\n- пользовательская документация и runtime/package metadata синхронизированы с 0.2.0.",
    "- optional instrument в новой фактической инвестиционной выплате теперь по умолчанию пуст и сбрасывается после сохранения;\n- прогресс основной passive-income цели теперь использует rolling average фактического net passive income по закрытым месяцам, а не C04 forecast monthly total; forecast остаётся отдельной прогнозной метрикой;\n- пользовательская документация и runtime/package metadata синхронизированы с 0.2.0.",
)

replace_once(
    "CHANGELOG.md",
    "- диагностированный `0 ₽` dividend component не оказался дефектом: owner подтвердил, что выплата была заведена как `coupon`; расчётная цепочка dividend → rolling average → forecast → goal изменений не потребовала.",
    "- диагностированный `0 ₽` dividend component не оказался потерей данных: owner подтвердил, что выплата была заведена как `coupon`; отдельный последующий smoke выявил уже продуктовую семантику Goal — фактические купоны/проценты не должны исчезать из `Текущего значения` только из-за пустого expected-calendar, что исправлено R02-27.",
)

replace_once(
    "docs/RELEASE_0_2.md",
    "| R02-26 | Automatic expected-payment population/source UX | P2 | DEFERRED | future contract | — |",
    "| R02-26 | Automatic expected-payment population/source UX | P2 | DEFERRED | future contract | — |\n| R02-27 | Passive-income goal current-value semantics | P1 | REVIEW | Sol bounded implementation / Sol reviewer | R02-04, R02-13 |",
)

r02_27_card = """
# R02-27. Passive-income goal current-value semantics

**Priority:** P1
**Status:** REVIEW
**Route:** Sol bounded implementation / Sol reviewer
**Depends on:** R02-04, R02-13

## Проблема

Owner smoke показал, что Dashboard корректно отображает фактический net passive income и его rolling average по закрытым месяцам, но основная passive-income цель использует `forecast_passive_income.monthly_total` как `current_value`. При пустом ручном expected-payment calendar это обнуляет фактические проценты депозитов и купоны; в Goal остаётся только dividend average. В результате подпись `Текущее значение` показывает прогнозную, а не фактическую метрику прогресса.

## Нормативное решение

- `current_value` и `progress_pct` цели `passive_income / monthly_net_passive_income` используют C03 rolling average **фактического net passive income** по `closed` reporting months, максимум последние 12;
- до накопления 12 месяцев среднее считается по доступным закрытым месяцам и сопровождается явным предупреждением `Среднее за доступный период. Учтено N месяцев из 12.`;
- депозитные проценты, купоны, дивиденды и прочий passive income попадают в Goal ровно через существующий C02 → C03 actual pipeline;
- C04 `forecast_passive_income` остаётся отдельной прогнозной метрикой и больше не является source of truth для user-facing `Текущего значения`/progress;
- `source_forecast_version` для actual-progress passive goal равен `null`; query `forecast_version` сохраняется для API backward compatibility;
- exact gap/progress formula и `ROUND_HALF_UP` из `goal_achievement_v1` не меняются;
- future achievement trajectory по-прежнему не изобретается: ниже target статус остаётся `not_projectable / no_trajectory_model`;
- capital goal semantics не меняются.

## Acceptance

- закрытые месяцы с фактическими deposit interest/coupon/dividend дают Goal тот же rolling actual average, что C03/Dashboard;
- пустой `expected_cash_flows` calendar не обнуляет купоны/проценты в `current_value`;
- draft months не входят в среднее;
- история короче 12 месяцев явно сообщает использованный count;
- frontend не считает деньги или progress самостоятельно, а отображает backend-derived values;
- regression test покрывает actual deposit interest + coupon + dividend при пустом expected calendar;
- backend/full exact-head CI green; никаких migrations/schema changes.

---

"""
append_once("docs/RELEASE_0_2.md", "# 2. Release Gate перед `0.2.0`", r02_27_card)

replace_once(
    "docs/RELEASE_0_2.md",
    "**Checkpoint status:** FINAL_GATE. R02-10/R02-17/R02-20/R02-21 и owner smoke/follow-ups завершены; tag удерживается до final local production probe и exact-main проверки.",
    "**Checkpoint status:** FINAL_GATE. R02-27 закрывает последний owner-smoke semantic finding; tag удерживается до его exact-head CI/merge и final local production probe на новом `main`.",
)

smoke_block = """
## Smoke finding 4 — passive-income Goal подменял текущее значение forecast-метрикой

**Статус:** R02-27 REVIEW.
**Наблюдение:** Dashboard показывал фактический passive income/rolling average по закрытым месяцам, а Goal при пустом expected-calendar учитывал только dividend average и игнорировал фактические deposit interest/coupons в `Текущем значении`.
**Root cause:** `goal_achievement` использовал `forecast_passive_income.monthly_total` вместо C03 actual rolling average.
**Решение:** Goal current/progress переводится на C03 actual average; C04 forecast остаётся отдельной прогнозной метрикой.
**Regression:** actual deposit interest + coupon + dividend при пустом expected calendar должны давать ненулевой Goal current value.

"""
append_once("docs/RELEASE_0_2_SMOKE_2026-08-11.md", "## Release handoff", smoke_block)

followup_block = """
## R02-27 — Passive-income goal current-value semantics

**Priority:** P1
**Status:** REVIEW

Owner smoke подтвердил semantic mismatch: Goal `Текущее значение` использовало C04 forecast monthly total, поэтому при пустом manual expected-calendar фактические проценты депозитов и купоны не участвовали в прогрессе. Нормативное решение: current/progress = C03 rolling average actual net passive income по CLOSED месяцам; C04 остаётся отдельным прогнозом. Canonical contract/task-card находится в `docs/RELEASE_0_2.md`.

"""
append_once("docs/RELEASE_0_2_FOLLOWUPS_2026-08-11.md", "## Release handling", followup_block)
