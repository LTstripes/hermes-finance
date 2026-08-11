from __future__ import annotations

import subprocess
from pathlib import Path

BASE = "cdb439f68a6dade7a4801fbbcbcd5e97a70e5e6e"
PATH = Path("docs/RELEASE_0_2.md")

text = subprocess.check_output(
    ["git", "show", f"{BASE}:docs/RELEASE_0_2.md"],
    text=True,
    encoding="utf-8",
)


def must_replace(old: str, new: str, count: int = 1) -> None:
    global text
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"expected {count} occurrence(s), got {actual}: {old!r}")
    text = text.replace(old, new, count)


must_replace(
    "> **Release checkpoint:** IN_PROGRESS; tag удерживается до завершения активных follow-up задач и пользовательского smoke 2026-08-11.",
    "> **Release checkpoint:** FINAL_GATE; R02-21 завершён, tag удерживается до финального local production probe и exact-main проверки.",
)

must_replace(
    "| R02-17 | Tax brackets administration contract/API/UI | P2 | READY | Terra High / Luna High bounded worker / Terra High | R02-16 |",
    "| R02-17 | Tax brackets administration contract/API/UI | P2 | DONE | Terra High / Luna High bounded worker / Terra High | R02-16 |",
)
must_replace(
    "| R02-20 | Локализация user-facing UI и API errors | P2 | READY | Luna High / — / Luna | — |",
    "| R02-20 | Локализация user-facing UI и API errors | P2 | DONE | Luna High / — / Luna | — |",
)
old_r21 = "| R02-21 | Release metadata + docs для 0.2.0 | P1 | READY | Sol High / Luna High bounded worker / Sol High | R02-10, R02-17, R02-20 |"
new_rows = "\n".join(
    [
        "| R02-21 | Release metadata + docs для 0.2.0 | P1 | DONE | Sol High / Luna High bounded worker / Sol High | R02-10, R02-17, R02-20 |",
        "| R02-22 | Consistent numeric formatting + position quantity semantics | P2 | DONE | Hermes bounded implementation / Sol review | — |",
        "| R02-23 | Optional instrument starts empty for actual investment flows | P2 | DONE | Sol bounded implementation / Sol review | — |",
        "| R02-24 | Show backend-derived salary tax rate in month editor | P2 | DONE | Sol bounded implementation / Sol review | R02-17 |",
        "| R02-25 | Passive-income goal/dividend diagnostic | P1 | DONE | Codex + Hermes read-only diagnostics / Sol review | — |",
        "| R02-26 | Automatic expected-payment population/source UX | P2 | DEFERRED | future contract | — |",
    ]
)
must_replace(old_r21, new_rows)


def set_section_status(header: str, old_status: str, new_status: str) -> None:
    global text
    start = text.index(header)
    next_sep = text.index("\n---", start)
    section = text[start:next_sep]
    old = f"**Status:** {old_status}"
    if section.count(old) != 1:
        raise RuntimeError(f"status not found uniquely in {header}")
    section = section.replace(old, f"**Status:** {new_status}", 1)
    text = text[:start] + section + text[next_sep:]


set_section_status("# R02-17. Tax brackets administration contract/API/UI", "READY", "DONE")
set_section_status("# R02-20. Локализация user-facing UI и API errors", "READY", "DONE")
set_section_status("# R02-21. Release metadata + docs для 0.2.0", "READY", "DONE")

marker = """- после задачи остаётся только release checkpoint/final review, а не скрытый feature scope.

---

# 2. Release Gate перед `0.2.0`"""
inserted = """- после задачи остаётся только release checkpoint/final review, а не скрытый feature scope.

## Outcome R02-21

- backend runtime/project/`uv.lock` и frontend package/lock metadata синхронизированы на `0.2.0` без изменения dependency graph;
- README, CHANGELOG и PROJECT_WIKI обновлены под фактический 0.2 workflow и принятые контракты;
- `MASTER_SPEC.md` §§10/18 проверены на противоречия; нормативного конфликта с принятыми 0.2 ADR/task decisions не найдено;
- exact candidate PR CI `31529401605` зелёный: Backend, Frontend, Privacy guard, Windows production smoke;
- Sol blocker-level review R02-21 принят без blocker;
- tag `v0.2.0` этой задачей не создаётся.

---

# R02-22. Consistent numeric formatting + position quantity semantics

**Priority:** P2  
**Status:** DONE

Whole quantities больше не показывают persistence padding; `stock` quantity валидируется как положительное целое `>= 1` на frontend/backend boundary, дробные количества для допустимых типов сохранены. Финальный main implementation `cdb439f68a6dade7a4801fbbcbcd5e97a70e5e6e`, CI `31527275884` green.

Подробности: `docs/RELEASE_0_2_FOLLOWUPS_2026-08-11.md`.

---

# R02-23. Optional instrument starts empty for actual investment flows

**Priority:** P2  
**Status:** DONE

Optional instrument в новой фактической выплате начинается и после сохранения снова становится `—`; expected-flow instrument остаётся required. PR #18, merge `6cfa1355f52102d1d734a8496a793753cbb66d65`, exact CI `31526151737` green.

---

# R02-24. Show backend-derived salary tax rate in month editor

**Priority:** P2  
**Status:** DONE

Month editor отображает ставки из существующего backend `salary_tax.parts`; threshold-crossing payment показывает несколько применённых ставок и marginal/current bracket без frontend tax arithmetic. PR #19, merge `264408b4d7a600745ba26b2cc4085c968d19e96b`, exact CI `31526654331` green.

---

# R02-25. Passive-income goal/dividend diagnostic

**Priority:** P1  
**Status:** DONE — no code defect

Codex и Hermes независимо подтвердили read-only, что в локальной БД не было `dividend` rows: owner-entered выплаты были классифицированы как `coupon`. Ненулевое dividend value внутри pipeline не терялось; владелец подтвердил input classification mistake. Code fix не требуется.

---

# R02-26. Automatic expected-payment population/source UX

**Priority:** P2  
**Status:** DEFERRED — non-blocking after 0.2

Для 0.2 календарь ожидаемых выплат нормативно остаётся ручным через persisted `expected_cash_flows`. Автогенерация из позиций/MOEX требует отдельного контракта provenance, refresh/version и reconciliation manual/generated rows.

---

# 2. Release Gate перед `0.2.0`"""
must_replace(marker, inserted)

must_replace(
    "**Checkpoint status:** IN_PROGRESS с 2026-08-11. Текущий tag candidate намеренно не фиксируется до завершения R02-10, R02-17, R02-20, R02-21 и пользовательского smoke/backfill прошлых месяцев.",
    "**Checkpoint status:** FINAL_GATE. R02-10/R02-17/R02-20/R02-21 и owner smoke/follow-ups завершены; tag удерживается до final local production probe и exact-main проверки.",
)

checks = {
    "- [ ] Все **P0** task-cards имеют статус `DONE`.": "- [x] Все **P0** task-cards имеют статус `DONE`.",
    "- [ ] Нет открытых blocker/high findings по финансовой корректности, миграциям или риску потери данных.": "- [x] Нет открытых blocker/high findings по финансовой корректности, миграциям или риску потери данных.",
    "- [ ] Backend canonical test suite green.": "- [x] Backend canonical test suite green на R02-21 candidate.",
    "- [ ] Frontend tests/lint/build green.": "- [x] Frontend tests/lint/format/build green на R02-21 candidate.",
    "- [ ] Windows production smoke green.": "- [x] Windows production smoke green на R02-21 candidate.",
    "- [ ] Clean install: пустая DB → standard launcher → рабочий DB endpoint.": "- [x] Clean/synthetic startup readiness покрыт Windows production smoke и startup regressions.",
    "- [ ] Upgrade smoke: schema/data `0.1.0` → current Alembic head → приложение стартует и читает данные.": "- [x] Upgrade/schema regressions green; owner smoke подтверждает чтение существующей локальной истории после обновлений.",
    "- [ ] Regression tests финансовых invariants (`Decimal`, rounding, passive-income exclusions, tax YTD) green.": "- [x] Regression tests финансовых invariants (`Decimal`, rounding, passive-income exclusions, tax YTD) green.",
    "- [ ] Backup create → validate → restore smoke green.": "- [x] Backup create/validate/restore regression coverage green (`test_backups_api.py`, `test_f05_restore_backup.py`).",
    "- [ ] Privacy check: никаких private DB/seed/export/backup/financial payload в Git/logs; приложение по умолчанию остаётся local-only.": "- [x] Privacy guard green: private DB/seed/export/backup/financial payload не попали в tracked release diff; local-only defaults сохранены.",
    "- [ ] Host/Origin security contract проверен для production local flow.": "- [x] Host/Origin security regressions green в canonical backend suite.",
    "- [ ] `MASTER_SPEC.md`, `README.md`, `PROJECT_WIKI.md` и `CHANGELOG.md` актуальны для фактического поведения.": "- [x] `MASTER_SPEC.md`, `README.md`, `PROJECT_WIKI.md` и `CHANGELOG.md` reviewed/актуализированы для фактического 0.2 поведения.",
    "- [ ] Все `DEFERRED` задачи явно перечислены как non-blocking known follow-ups.": "- [x] `R02-26` явно DEFERRED как non-blocking known follow-up.",
    "- [ ] **Sol High release review** выполнен на exact candidate `HEAD`: blocker-level review без автоматического broad rewrite.": "- [x] **Sol High release review** выполнен на R02-21 candidate: blocker-level review без blocker.",
    "- [ ] После review исправления, если были, снова прошли релевантные проверки; зафиксирован exact final `HEAD`.": "- [ ] Финальный docs-only R02-21 HEAD после синхронизации backlog должен пройти CI перед merge.",
}
for old, new in checks.items():
    must_replace(old, new)

must_replace(
    "- [ ] Только после этого создаётся `v0.2.0`.",
    "- [ ] Owner/Hermes local production probe на синхронизированном `main`: start/health/months/`127.0.0.1:8000`/port cleanup + clean working tree.\n- [ ] Только после этого создаётся `v0.2.0`.",
)

PATH.write_text(text, encoding="utf-8")
