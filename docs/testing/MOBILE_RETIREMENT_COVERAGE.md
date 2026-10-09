# Desktop coverage after phone-test retirement — #747

Baseline: canonical `main` at `589f08f5476913e9d2110f619d43a2b6eef882a7`, after docs PR #750. This map describes the #747 candidate; exact candidate/check identities belong in its PR. No application, backend, schema, financial calculation, responsive CSS, dependency or workflow changes are included.

## Removed versus retained scenarios

Paths in this table are under `frontend/e2e/`. Removal means a phone execution/layout requirement, not removal of its shared financial assertions.

| Suite | Removed coverage | Retained desktop coverage |
| --- | --- | --- |
| `performance-preparation.visual.spec.ts` | Five 390px variants: values, evidence, XIRR-only, account preparation, class preparation | The same five bodies at 1366px: independent availability/nulls, provenance, keyboard, period/scope identity, writes/readback, stale and CLOSED lifecycle. Canonical source only; frozen #744 is not incorporated. |
| `ui-v2-month-editor.visual.spec.ts` | Three 390px duplicates; phone-only table overflow/scroll branch | Existing 1280px keyboard/reopen, six-leaf writes/readback/navigation, long debt/link editor Save/Cancel reachability; all dirty/Back, ambiguous/expired and CLOSED tests remain. |
| `ui-v2-capital-allocation.spec.ts` | 390px matrix member | Existing 1366px deep link, selected-month coverage, unsupported denominator and keyboard disclosure. |
| `ui-v2-months.spec.ts` | 390px matrix member | Existing 1366px create/clone/delete, exact local selection, keyboard and navigation. |
| `ui-v2-scenario.spec.ts` | 390px duplicate and phone-only internal table-overflow assertion | Existing 1366px explicit calculation, no calculation on mount, keyboard, result invalidation after month change, export disablement, bad identity, Back/reload. |
| `ui-v2-payout-forecast.spec.ts` | Two 390px variants | Both existing desktop bodies: forecast/calendar identity, principal versus income, ambiguity/failure and CLOSED protection. |
| `ui-v2-statement-import.spec.ts` | Three 390px variants | Existing 1366px inspect/prepare/cancel/apply/readback plus failure/ambiguity/duplicate cases and standalone stale/CLOSED tests. |
| `ui-v2-iis-forms.spec.ts` | 390px matrix member | Existing 1366x768 account/year identity, explicit writes/readback, ambiguous lock and keyboard. |
| `ui-v2-default-switch.spec.ts` | 390px viewport in rollback case | Unique v1 rollback visibility/focus/Enter scenario moved to 1440x900; passive-write, lazy failure and hard-reload/deep-link tests remain. |
| `ui-v2.visual.spec.ts` | Phone back-to-top, archive-card and historical-report duplicates; duplicate excluded-source 390px execution; linked-pair 700px capture | Back-to-top bounding-box assertions folded into existing 1440px focus/keyboard test. Existing desktop archive/report financial values, gaps and links remain. Excluded-source provenance/disclosure remains at 1440px. Unique Home/Capital long-number fixtures and actual-payouts Close step moved to 1440x900 once; no zero/unknown/error fixture removed. Linked-pair gross/residual/missing-link assertions remain in all desktop projects. |
| `ui-v2-data.visual.spec.ts` | Four phone duplicates and navigation phone capture | Existing freshness/catalogs/navigation tests remain. Provider-on-click copy assertion folded into reconciliation desktop case; irreversible-action warning folded into restore desktop case. No passive restore/provider write added. |
| `ui-v2-income.visual.spec.ts` | Phone collapse duplicate | Existing desktop facts/plan/ladder/principal assertions remain. Unique plan-row/amount overlap probe folded into existing desktop scenario, checking rectangle intersections across desktop columns rather than assuming one vertical list; absent plan and explicit zero remain distinct. |
| `performance-real-backend.spec.ts` | 390px viewport and `performance-390-*` artifact names | Entire unique actual-backend scenario at 1440x900: unavailable → XIRR-only → observed PRE/POST → TWRR; explicit attestation/write/readback, CLOSED 409, reopen, material correction invalidation, stale capture 409, Back/reload and page-error checks. Artifacts are `performance-1440-*`. |
| `monthly-close.acceptance.ts` | Two embedded 390px loop members; phone CLOSED capture | All four actual-backend scenarios remain; edit/return/close/report/reopen, old-month identity, keyboard/diagnostics selection and no passive writes run on desktop. |
| `statement-import.acceptance.ts` | Phone prepared-statement capture | Whole actual-backend native/legacy scenario remains at 1440px, including cancel, foreign-month disabled row, one keyboard write, persisted reread/reload and duplicate protection. |
| `alfa-baseline.acceptance.ts`, `quote-mapping.acceptance.ts`, `payout.acceptance.ts` | Phone substeps/artifact names and payout 390px matrix member | Unique actual-backend apply/reconciliation/provider-failure/response-loss and keyboard assertions retained on desktop; existing 1366px payout journey unchanged. These supported standalone configs remain available even where they are outside current required native CI selection. |

## Collection evidence

Collected with locked frontend dependencies and unchanged configs, using `playwright test --list --reporter=json` on baseline and candidate. These are discovered project/test slots, including runtime-skipped slots, **not executed/pass counts**. Embedded substeps (such as the two Monthly Close loops) do not create additional collected tests.

| Config / project | Baseline | Candidate |
| --- | ---: | ---: |
| Visual: 1366x768 | 86 | 78 |
| Visual: 1440x900 | 125 | 99 |
| Visual: 1920x1080 | 86 | 78 |
| Visual total | 297 | 255 |
| Default: Desktop Chrome | 128 | 102 |
| Native Monthly Close | 4 | 4 |
| Native statement import | 1 | 1 |

No speedup is inferred from collection counts. Comparable CI duration evidence is required before making a timing claim.

## Fixtures, expected images and active checks

- No tracked phone expected images or snapshot directories existed at baseline (`git ls-files frontend` image inventory). Screenshots are generated artifacts; retired phone filenames/captures are removed or renamed on retained desktop behavior. Owner-local artifacts and dated closeouts are outside this cleanup.
- Shared API fixtures, long names/amounts, no-closed/first-closed/zero/partial/error states and synthetic provider/PDF builders retain desktop consumers. No fixture/data file is deleted. Monetary `390` values remain unchanged.
- Playwright configs, active visual launcher, path filters, UI-evidence identity proof and all workflows have no phone-specific project/dependency to remove. They remain unchanged: desktop 1366/1440/1920, privacy, frontend/backend, native actual-backend, Windows timezone/production smoke and release/runtime safety gates still run. No blanket exclusion, new skip or disabled evidence is introduced.
- Current UAT and Performance V17 instructions require desktop/laptop, keyboard, focus/Back, long content and supported zoom. Dated historical reports retain their original mobile evidence.
- #744 stays frozen. Its later reconciliation belongs to Integrator: retain all new desktop assertions and do not restore phone members. #747 does not assert real-history XIRR readiness or authorize runtime operations.

Validation outcomes, independent coverage review and exact-head CI are recorded in the draft PR. CBM: used `D-Codex-index-sources-hermes-finance-main` to locate Playwright configuration surfaces; checked against current assigned-checkout source. The index timestamp preceded this baseline, so it supplied navigation only.
