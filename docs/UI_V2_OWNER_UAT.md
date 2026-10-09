# Owner UAT — common UI / Performance candidate (#572)

This is an Owner-only runbook for the final candidate reported by the #572 draft PR. Source anchor `b05487b822252fad9d9ec7cf4410d6d96c91c8bb` identifies code/CI/specs; use the **final code+docs candidate SHA**, not an old leaf/staging SHA. Only Integrator can mark READY_FOR_OWNER_UAT after the required CI and independent integration/product/lifecycle review. Worker synthetic tests do not provide Owner PASS.

## Assignment and backup first

Integrator/Owner must first identify the exact candidate SHA, trusted control checkout, independent Preview checkout, Preview data directory/database, Stable checkout/data/database and representative-history source. These private local assignments remain Owner-controlled and absent from repository evidence. Missing assignment is a remaining gate; do not invent paths or use a developer workspace.

Stop the relevant Owner runtime through its supported operation. Create and verify a backup with the existing Owner backup/recovery procedure **before copying or changing any history**. Use a consistent verified physical database copy, with confirmed isolation from Stable and its SQLite sidecars. The copy must contain representative existing history: older and latest closed reports, a draft, meaningful account/class/cash/instrument contexts and relevant return boundaries. An empty/synthetic stand cannot demonstrate real-history UAT. Development agents never receive the source, DB, backup, statements, screenshots containing values or raw diagnostics.

Use the accepted OPS03 command from a trusted control checkout. Variables below are the explicit Owner assignment, not suggested paths:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-preview.ps1 `
  -CandidateSha $CandidateSha `
  -PreviewCheckout $PreviewCheckout `
  -PreviewDataDirectory $PreviewDataDirectory `
  -PreviewDatabase $PreviewDatabase `
  -StableCheckout $StableCheckout `
  -StableDataDirectory $StableDataDirectory `
  -StableDatabase $StableDatabase `
  -ControlCheckout $ControlCheckout
```

OPS03 validates separation, pins an independent clone, and composes Prepare/Validate. It does not Start or directly migrate. After its boundary is prepared, Owner populates Preview with the verified isolated representative-history copy using the existing supported Owner process, rechecks the selected DB assignment, and starts from that approved Preview checkout:

```powershell
git rev-parse HEAD
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $PreviewCheckout -Validate
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Confirm the reported HEAD equals the selected final candidate and startup selects only the assigned Preview DB. Start uses existing migration semantics for that isolated DB. A failed identity/boundary/backup check stops UAT. Do not bypass prepared-state or recovery guards. See [Owner runtime operations](OWNER_RUNTIME_OPERATIONS.md#6-exact-previewuat-preparation) and [runtime safety ADR](adr/0014-launcher-runtime-profile-safety.md).

**Preview writes are only Preview writes.** A September close/reopen/import in Preview does not close/reopen/import production. No automatic copying back, database promotion, Stable repointing or deletion follows UAT. Actual production close requires the separately approved exact code/runtime update and Owner operation; retain the original history and verified backup.

## Short journey and expected results

Use loopback UI in the approved Preview. Select exact targets locally; do not publish IDs, dates/amounts or screenshots. For each step record only PASS/FAIL/NOT TESTED and a non-reconstructive observation. A failed mandatory step blocks Owner PASS; missing applicable source evidence stays unavailable.

| Step | Actual UI labels / route | Expected result |
| --- | --- | --- |
| 1. Confirm picture/history | `Мои финансы`, `Капитал`, `Все отчёты`; open an older `Исторический отчёт` | Latest CLOSED is the confirmed picture; archive has the selected older closed report, correct context and read-only values; Back/refresh keeps its target. A draft is not an archived fact. |
| 2. Prepare the draft | Open `/v2/close`, inspect the chosen month; use `Бюджет` / `Изменить`, then `Редактор месяца` | Edit only the intended draft, save a harmless known test change in Preview, and verify confirmation/readback. `Вернуться к закрытию` preserves month and step and refreshes readiness. Cancel/discard an unsaved edit explicitly. |
| 3. Native import | Close's statement action, or `Данные` -> payouts for that month; `Проверить отчёт`, `Подготовить к импорту`, `Применить выбранные строки` | Only rows belonging to the selected month can apply. `Отмена` writes nothing. `Подтвердить и применить` writes once, then authoritative reread/reload shows the result; re-import is a duplicate. Owner-only existing local statement/source; no live provider call is needed for this test. |
| 4. Final review and close | Final step, `Закрыть месяц`, confirmation `Закрыть` | Review actual refreshed state and blockers. Escape/cancel leaves a draft. Confirm only in Preview; `Месяц зафиксирован` follows persisted CLOSED and fresh workflow. Mutation/Edit actions disappear. |
| 5. Return/reopen | `Создать следующий месяц`, `Вернуться к закрытию исходного месяца`, `Открыть месяц заново`, `Открыть заново` | Return keeps the original month/step. Reopen requires explicit confirmation; cancel keeps CLOSED, confirmed reopen becomes the same draft after reread. Check desktop, keyboard focus and Back/refresh. |
| 6. Monetary result and allocation | `Капитал` -> `Денежный результат`; `Распределение и концентрация` | Older/latest closed result has separate cash-income and unrealized-snapshot meaning; cash-only rows keep nulls, zero/loss stay truthful. Account and class cuts need not total alike. Allocation preserves local month, canonical denominator/support and future-event exclusions. |
| 7. Performance Phase A | `Капитал` -> `Доходность`, exact period and account/portfolio selection; `Проверить данные` | Snapshot dates/scope/currency remain exact. Unavailable reasons are visible. XIRR-only is valid when TWRR evidence is missing. Save only actual supported evidence already possessed by Owner; never manufacture PRE/POST amounts, infer membership from current flags or mark empty histories complete. TWRR becomes available only when canonical evidence supports it. Back/refresh retains period/scope. Classes remain deferred. |
| 8. Income / local tools | `Доход и планы`, Goals, Tax/IIS planner/account catalogs; Scenario `Рассчитать сценарий` and local export | Actual income, forecast and principal remain distinct. Local month/as-of/account/year context survives actions. Goals main/active behavior and IIS confirmation/readback remain correct; Scenario export represents the chosen calculation. Global historical/draft Dashboard planning is intentionally de-scoped by D2. |
| 9. Recovery on the isolated copy, if applicable | `Экспорт и копии`; create a local backup and confirm its exact restore target | Test only against the assigned Preview copy. Cancel/failed/ambiguous restore does not claim success or silently retry. Confirmed success retains pre-restore backup evidence and reloads current reads; a removed month must show missing, not silently select another. Afterward verify the same assigned database/identity. |
| 10. Reconcile and report | Latest/older report, monetary result, Performance, settings/diagnostics; explicit previous-interface escape if needed | Report only labelled PASS/FAIL/NOT TESTED and sanitized UI observations. Separate intentional v1 fallback from missing ordinary action. Keep private values/files/backup IDs locally. No production transition, release or v1 retirement is implied. |

Earlier Performance Owner PASS explicitly deferred representative real-history evidence. It does not cover this common candidate. Integrator records the actual Owner disposition on this exact tree, or explicitly proves tree equivalence; after that, main merge, exact-main push CI, release identity and supported runtime update are separate decisions.
