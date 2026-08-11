# Release 0.2 — canonical release record

> **Релиз:** `0.2.0`  
> **Статус release checkpoint:** REVIEW  
> **Tag:** удерживается до exact-candidate CI, локального production probe и final Sol blocker-level review.  
> **Бизнес-источник истины:** `docs/MASTER_SPEC.md` + принятые ADR.  
> **Verification:** `docs/VERIFICATION_POLICY.md`.  
> **Исторический MVP backlog:** `docs/HERMES_TASKS.md`.

## 0. Назначение

Этот файл — канонический итог release train 0.2. Подробные промежуточные task-card формулировки сохранены в Git history; owner-led smoke и временные follow-ups находятся в:

- `docs/RELEASE_0_2_SMOKE_2026-08-11.md`;
- `docs/RELEASE_0_2_FOLLOWUPS_2026-08-11.md`.

Новые post-0.2 задачи не добавляются сюда автоматически: после релиза для них создаётся следующий active release backlog.

Статусы: `IDEA → SPECIFIED → READY → IN_PROGRESS → REVIEW → DONE`; также используются `BLOCKED` и `DEFERRED`.

## 1. Итоговый backlog 0.2

| ID | Задача | Priority | Status | Итог |
|---|---|---:|---|---|
| R02-01 | Startup migrations + schema readiness gate | P0 | DONE | Canonical launchers применяют Alembic до readiness; DB endpoint входит в smoke. |
| R02-02 | Контракт opening YTD gross для НДФЛ | P0 | DONE | Принят fail-closed opening-YTD contract и ADR. |
| R02-03 | Реализация opening YTD gross для НДФЛ | P0 | DONE | Annual opening context реализован без double count; обязательный `salary_tax_history_incomplete`. |
| R02-04 | Passive-income invariants / double-count protection | P0 | DONE | Active income/cashback не могут стать passive; deposit interest имеет канонический источник. |
| R02-05 | Localhost Host/Origin protection | P1 | DONE | Unsafe requests защищены local Host/Origin contract без auth/cloud. |
| R02-06 | True-offline UI / external fonts | P2 | DONE | Внешняя font-зависимость удалена. |
| R02-07 | Exact-money frontend boundary | P1 | DONE | Финансовая арифметика не проходит через JS `Number`; chart conversion только presentation boundary. |
| R02-08 | Windows production smoke CI | P1 | DONE | CI запускает production launcher и проверяет local startup/readiness. |
| R02-09 | Safe backup/restore serialization | P1 | DONE | Process-local DB maintenance guard, request drain и pre-restore safety. |
| R02-10 | SQLite locking decision | P2 | DONE | `journal_mode=delete`, effective `busy_timeout=5000 ms`; WAL осознанно не включён. |
| R02-11 | Goals API + main-goal source of truth | P1 | DONE | Persistent `is_main`, CRUD и compatibility seed/mirror. |
| R02-12 | Goal achievement forecast contract/backend | P1 | DONE | `goal_achievement_v1`; no invented future growth. |
| R02-13 | Goals UI + Dashboard main goal | P1 | DONE | Полноценный Goals UI и backend-derived Dashboard goal panel. |
| R02-14 | Fixed desktop sidebar | P2 | DONE | Desktop navigation закреплена и owner-smoke accepted. |
| R02-15 | Accounts & Instruments UI | P2 | DONE | Placeholder заменён полноценным справочником. |
| R02-16 | Settings UI baseline | P2 | DONE | Placeholder заменён рабочими настройками. |
| R02-17 | Tax brackets administration | P2 | DONE | Year-scoped atomic contract/API/UI; closed-year history protected from silent rewrite. |
| R02-18 | Income cash-flow inclusion contract | P1 | DONE | Принята нормативная matrix для `include_in_cash_flow` и OTHER. |
| R02-19 | Income cash-flow implementation | P1 | DONE | Monthly cash balance реализует R02-18 без passive double count. |
| R02-20 | User-facing localization | P2 | DONE | Internal reason/error identifiers локализованы/скрыты из обычного UX. |
| R02-21 | Release metadata + docs для 0.2.0 | P1 | REVIEW | Version/docs синхронизируются; exact candidate review ещё не завершён. |
| R02-22 | Numeric formatting + quantity semantics | P2 | DONE | Whole quantities cleanly rendered; stock quantity positive whole integer on UI/backend. |
| R02-23 | Optional actual-flow instrument | P2 | DONE | Optional instrument starts/resets to `—`; expected-flow contract unchanged. |
| R02-24 | Salary NDFL rate in editor | P2 | DONE | UI displays backend `salary_tax.parts`, including threshold crossing. |
| R02-25 | Passive-goal/dividend diagnostic | P1 | DONE | No defect: owner-entered flow was `coupon`, not `dividend`; two read-only diagnostics agreed. |
| R02-26 | Automatic expected-payment population | P2 | DEFERRED | 0.2 keeps explicit manual expected-flow workflow; automatic source/refresh semantics deferred. |

## 2. Нормативные 0.2 решения

### 2.1. Salary tax / opening YTD

- known historical month = existing `reporting_month` with status `closed`;
- draft is unknown, not a known zero;
- reopen makes that month unknown again for downstream YTD;
- incomplete history fails closed with `salary_tax_history_incomplete`;
- annual opening context covers January 1 through the month immediately before `effective_from_month` and is included exactly once;
- historical draft editor remains usable when only the calculated tax slice is unavailable;
- tax bracket administration operates on one complete calendar-year scale and is blocked once that year contains closed months unless history is explicitly reopened.

Normative opening contract: `docs/adr/0002-opening-ytd-gross.md`.

### 2.2. Passive income and cash flow

- salary/bonus/side income/cashback are not passive income;
- deposit actual interest comes only from `deposit_snapshots.actual_interest_received`;
- redemption is principal return, not income;
- `include_in_cash_flow` controls income inclusion in monthly cash balance according to the accepted R02-18 matrix;
- actual dividend stays in the month received; forecast dividend component averages actual net dividends across available closed months, max rolling 12.

### 2.3. Goals

- `goals` is runtime source of truth;
- main passive-income goal consumes backend forecast monthly passive income;
- no synthetic growth trajectory is invented when none exists;
- internal calculation/reason codes are not primary user-facing UI.

### 2.4. Exact money

- persistence/domain money: integer minor units / `Decimal` + `ROUND_HALF_UP`;
- API money: decimal strings + currency;
- frontend does not perform financial money arithmetic through binary float;
- position quantity persistence may remain decimal where legitimate, but `stock` quantity is a positive whole integer.

### 2.5. SQLite / backup / local security

- local-only default remains `127.0.0.1:8000`;
- no cloud/auth/telemetry added;
- Host/Origin protections cover unsafe local requests;
- backup/restore operations are serialized with active request draining where required;
- SQLite remains rollback-journal mode with `busy_timeout=5000 ms`; WAL requires a future reproducible need.

### 2.6. Expected payment calendar

0.2 uses persisted, manually entered `expected_cash_flows`. Automatic MOEX/position-derived schedules are not implemented and are explicitly DEFERRED (R02-26) until provenance, refresh/version and manual/generated reconciliation semantics are defined.

## 3. Owner-led smoke 2026-08-11

Smoke/backfill produced two real defects and one diagnostic false alarm:

1. **Historical draft blocked by incomplete tax history** — fixed in PR #15 / merge `83271d106ca1065ddf6778540065fe45c0e508cc`.
2. **Populated draft could not be deleted** — fixed in PR #16 / merge `8a77ba92716f5f9b897c91d007e13e16814164b2`.
3. **Dividend forecast/main goal zero** — no code defect; local DB contained coupon flows and zero dividend rows, confirmed independently by Codex and Hermes; owner confirmed input classification error.

Additional smoke polish R02-22/23/24 is DONE. See the dedicated smoke/follow-up logs for detail.

## 4. R02-21 — Release metadata + docs

**Priority:** P1  
**Status:** REVIEW  
**Route:** Sol High primary / bounded mechanical worker if required / Sol High reviewer.

### Scope

- canonical backend/frontend/runtime version → `0.2.0`;
- synchronize package/lock metadata that carries project version;
- README → actual 0.2 startup/workflow/UI/limitations;
- CHANGELOG → 0.2.0 release entry;
- PROJECT_WIKI → current source-of-truth hierarchy, stack, accepted contracts and verification policy;
- reconcile this backlog and owner smoke follow-ups;
- inspect `MASTER_SPEC.md` for contradictions without broad historical rewrite;
- do not create `v0.2.0` before mandatory gate and exact candidate review.

### MASTER_SPEC audit

`MASTER_SPEC.md` §§10 and 18 remain compatible with the accepted 0.2 invariants: backend-only financial formulas, exact money, passive-income exclusions, redemption semantics, local-only architecture and manual expected-flow forecast remain intact.

The version roadmap in §16 is historical planning rather than a prohibition on shipping features earlier: Goals/forecast capabilities were intentionally promoted into 0.2 through accepted R02-11…13. No financial formula or non-negotiable §18 rule requires a spec rewrite for R02-21.

### Acceptance

- [ ] runtime `/api/health` and canonical package/lock metadata consistently report `0.2.0`;
- [x] README no longer describes completed Goals/Settings/Accounts pages as placeholders;
- [x] CHANGELOG contains actual 0.2 changes and current limitations;
- [x] PROJECT_WIKI uses the active release/verification protocol rather than `HERMES_TASKS.md` as post-MVP source of truth;
- [x] R02-22…26 outcomes are reconciled;
- [x] docs contain no private financial data by design;
- [ ] exact candidate CI green;
- [ ] final Sol blocker-level review accepted.

## 5. Release Gate перед `v0.2.0`

Tag/release создаётся только после отдельного exact-candidate checkpoint.

- [x] Все P0 task-cards DONE.
- [x] Нет известного открытого blocker/high finding по финансовой корректности из owner smoke; R02-25 закрыт как input classification issue, а не code defect.
- [ ] Backend canonical test suite green на exact 0.2 candidate HEAD.
- [ ] Frontend tests/lint/build green на exact 0.2 candidate HEAD.
- [ ] Windows production smoke green на exact 0.2 candidate HEAD.
- [ ] Clean-install startup contract подтверждён final probe/CI evidence.
- [ ] Upgrade/read-existing-data contract подтверждён final probe/relevant regression evidence.
- [ ] Финансовые invariant regressions green на exact candidate.
- [ ] Backup create/validate/restore relevant regression/probe green.
- [ ] Privacy guard green; local-only defaults сохранены.
- [ ] Host/Origin security regression green.
- [x] `MASTER_SPEC.md`, README, Wiki and CHANGELOG reviewed for 0.2 behavior; final diff still awaits exact-candidate review.
- [x] DEFERRED задачи перечислены: R02-26 — automatic expected-payment population.
- [ ] Sol High release review on exact candidate HEAD completed with no blockers.
- [ ] If review creates fixes, the final resulting HEAD passes required checks again.
- [ ] Only then create tag `v0.2.0`.

## 6. Parallel work rule

Until the tag is created:

- one write task has one primary owner;
- independent local read-only smoke/probes may run in parallel;
- no new feature scope is folded into R02-21;
- any new material defect becomes a bounded task before release;
- reports do not substitute for diff/tests/exact-HEAD evidence.
