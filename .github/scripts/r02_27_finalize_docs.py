from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, got {count}: {old!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "docs/RELEASE_0_2.md",
    "| R02-27 | Passive-income goal current-value semantics | P1 | REVIEW | Sol bounded implementation / Sol reviewer | R02-04, R02-13 |",
    "| R02-27 | Passive-income goal current-value semantics | P1 | DONE | Sol bounded implementation / Sol reviewer | R02-04, R02-13 |",
)
replace_once(
    "docs/RELEASE_0_2.md",
    "# R02-27. Passive-income goal current-value semantics\n\n**Priority:** P1\n**Status:** REVIEW",
    "# R02-27. Passive-income goal current-value semantics\n\n**Priority:** P1\n**Status:** DONE",
)
replace_once(
    "docs/RELEASE_0_2.md",
    "- backend/full exact-head CI green; никаких migrations/schema changes.\n\n---",
    "- backend/full exact-head CI green; никаких migrations/schema changes.\n\n## Outcome R02-27\n\n- passive-income Goal `current_value`/`progress_pct` переключены с C04 forecast monthly total на C03 rolling average фактического net passive income по CLOSED месяцам;\n- C04 forecast сохранён как отдельная прогнозная метрика; exact gap/progress formula и capital-goal semantics не менялись;\n- integration regression покрывает deposit interest + coupon + dividend при пустом `expected_cash_flows`;\n- PR #21 candidate CI `31532650301` green: Backend, Frontend, Privacy guard, Windows production smoke;\n- migrations/schema changes отсутствуют.\n\n---",
)
replace_once(
    "docs/RELEASE_0_2.md",
    "**Checkpoint status:** FINAL_GATE. R02-27 закрывает последний owner-smoke semantic finding; tag удерживается до его exact-head CI/merge и final local production probe на новом `main`.",
    "**Checkpoint status:** FINAL_GATE. R02-27 DONE и candidate CI green; tag удерживается до merge, exact-main CI и final local production probe на новом `main`.",
)
replace_once(
    "docs/RELEASE_0_2.md",
    "- [ ] Финальный docs-only R02-21 HEAD после синхронизации backlog должен пройти CI перед merge.\n- [ ] Owner/Hermes local production probe на синхронизированном `main`: start/health/months/`127.0.0.1:8000`/port cleanup + clean working tree.",
    "- [x] R02-21 merged main exact CI `31530369330` green после финальной синхронизации release metadata/docs.\n- [x] R02-27 candidate exact CI `31532650301` green, включая actual-passive-income regression и Windows production smoke.\n- [ ] Owner/Hermes local production probe на финальном `main`: start/health/months/`127.0.0.1:8000`/port cleanup + clean working tree.",
)

replace_once(
    "docs/RELEASE_0_2_SMOKE_2026-08-11.md",
    "**Статус:** R02-27 REVIEW.",
    "**Статус:** R02-27 DONE; PR #21 candidate CI `31532650301` green.",
)
replace_once(
    "docs/RELEASE_0_2_SMOKE_2026-08-11.md",
    "**Решение:** Goal current/progress переводится на C03 actual average; C04 forecast остаётся отдельной прогнозной метрикой.",
    "**Решение:** Goal current/progress использует C03 actual average; C04 forecast остаётся отдельной прогнозной метрикой.",
)
replace_once(
    "docs/RELEASE_0_2_SMOKE_2026-08-11.md",
    "R02-21 synchronizes version metadata, README/Wiki/CHANGELOG, canonical `RELEASE_0_2.md` status and this smoke record. The final `v0.2.0` tag remains blocked until the release gate and exact-candidate review are complete.",
    "R02-21 и R02-27 синхронизировали release metadata/docs и закрыли owner-smoke findings. `v0.2.0` tag остаётся удержан до merge R02-27, exact-main CI и финального локального production probe на новом `main`.",
)

replace_once(
    "docs/RELEASE_0_2_FOLLOWUPS_2026-08-11.md",
    "## R02-27 — Passive-income goal current-value semantics\n\n**Priority:** P1\n**Status:** REVIEW",
    "## R02-27 — Passive-income goal current-value semantics\n\n**Priority:** P1\n**Status:** DONE",
)
replace_once(
    "docs/RELEASE_0_2_FOLLOWUPS_2026-08-11.md",
    "Owner smoke подтвердил semantic mismatch: Goal `Текущее значение` использовало C04 forecast monthly total, поэтому при пустом manual expected-calendar фактические проценты депозитов и купоны не участвовали в прогрессе. Нормативное решение: current/progress = C03 rolling average actual net passive income по CLOSED месяцам; C04 остаётся отдельным прогнозом. Canonical contract/task-card находится в `docs/RELEASE_0_2.md`.",
    "Owner smoke подтвердил semantic mismatch: Goal `Текущее значение` использовало C04 forecast monthly total, поэтому при пустом manual expected-calendar фактические проценты депозитов и купоны не участвовали в прогрессе. Исправлено: current/progress = C03 rolling average actual net passive income по CLOSED месяцам; C04 остаётся отдельным прогнозом. PR #21 candidate CI `31532650301` green. Canonical contract/task-card находится в `docs/RELEASE_0_2.md`.",
)
replace_once(
    "docs/RELEASE_0_2_FOLLOWUPS_2026-08-11.md",
    "- R02-26 is explicitly DEFERRED and non-blocking for 0.2;\n- R02-21 owns final version/docs/backlog synchronization and release-candidate review preparation.",
    "- R02-26 is explicitly DEFERRED and non-blocking for 0.2;\n- R02-27 is DONE with exact candidate CI green;\n- after merge only exact-main CI + final local production probe remain before `v0.2.0` tag.",
)
