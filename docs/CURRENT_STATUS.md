# Hermes Finance — current status

Canonical Owner/Integrator checkpoint, **2026-10-03**. Live GitHub refs and completed CI remain authoritative; this is a milestone record, not a moving HEAD alias. Published release, development integration and local runtime are different states.

## Published and local Stable

**v1.1.0 is published**: commit `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`, tree `7f5a3198fa650b71545550301063c9afd887f8f8`, annotated tag object `9b402190bafc5d8415b217580da5e18ed35a6331`. Exact-main push CI `36776904188` and Guarded Release `36777962224` succeeded; #643/#644 own publication evidence.

Owner confirmed the local clean detached Stable checkout at that release and completed the first real September close. **#572 is CLOSED: Owner PASS WITH DOCUMENTED LIMITATIONS**, including manual/v1 use and provider limitations. This is not all-native/all-provider success or proof that every XIRR/TWRR is available on personal history. [Actual acceptance](https://github.com/LTstripes/hermes-finance/issues/572#issuecomment-5937693786).

The earlier `OWNER_AUTHORIZED_UAT_DEFERRAL` was the pre-publication decision, not the current acceptance state. Historical preparation evidence remains in the [prior checkpoint](https://github.com/LTstripes/hermes-finance/blob/d4e5bb6067f60932d4a35b000d0aa8a5ceda9d7a/docs/CURRENT_STATUS.md) and [release record](releases/1.1.0.md).

## Post-release product wave — integrated, not newly released

Owner-tested aggregate: `d282d09647f129cd83c99e14a10024901a1cf6da`, tree `cf39e2c933f78691e7ec0db14872f640df903ec5`. Aggregate CI `37108969114` and UI `37108969154` succeeded. Owner completed the supplied isolated Preview route and authorized integration with documented UX follow-ups: [#662 acceptance](https://github.com/LTstripes/hermes-finance/pull/662#issuecomment-5967980369).

**#662 merged to main at `a0396e9971be119038b8c28d29398191449b0c0c`**, preserving the tested tree. Its main push CI is `37114728212`; relevant jobs, including frontend, backend, native journeys, Windows production smoke and synthetic visual audit, completed successfully.

| Slice | Delivered result | Retained boundary |
| --- | --- | --- |
| #647 | Exact-month edit/reopen/direct final review; local saved-data reread; one Settings/Diagnostics entry | Earlier month-list usability findings are #667, not silently fixed |
| #648 | Initially collapsed future-payout groups, bulk and individual Apply, truthful per-group results | Per-group atomicity, sequential submissions and no blind retry of UNKNOWN |
| #649 | Contextual validated quote mapping, Alfa attention/all/confirmed views, origin/saved/freshness distinctions | No implicit provider calls or fabricated completeness |
| #650 | Readable money units, stacked debt/link editors, saved-only totals and narrow-width containment | Existing mutation/readback/lifecycle semantics preserved |
| #651 | Fixed-set linked-account/debt explanation without double counting | Gross facts, canonical net delta and partial coverage preserved; repeated qualifier copy follows #672 |
| #645 | Bounded server-owned same-day LAST Preview evidence | Historical/HISTORY strict refetch; live qualifying LAST remains NOT TESTED by this historical-month UAT |

Full acceptance scope, source heads, maintenance disposition and model attribution: [post-release closeout](POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md). Do not rerun the complete Owner UAT just for docs or copy-only changes; changed navigation in #667 needs its own focused retest.

## Maintenance and active follow-ups

- #664 Actions SHA-pinning is integrated at `bc48b32012fd5b20e84f0389d9b7c93582d54fa8`; existing versions/triggers/permissions and #124 release controls remain unchanged.
- #665 LF and Node guards are integrated at `fa2d98f1b7e386bac5af587a9ab1af1d9ec6fb27`; recommended Node is 22.23.1. No dependency upgrades or repository-wide renormalization.
- #663 synchronizes frontend version metadata and current documentation with the released 1.1.0 plus the separate development wave. AI export schema remains independently versioned at 1.3.0.
- #672 is the Owner-requested removal of repeated Home row-label qualifiers; calculations and coverage messages are unchanged.
- **#666 is the next Owner priority:** protected Stable/Control/Preview versus disposable task workspaces, read-only inventory and a reviewed relocation/cleanup plan first. No agent access to private runtime files, automatic deletion or path migration.
- #667 retains the confusing Select/open actions, latest-report intermediary and unreadable primary link from UAT block 1.
- #646 remains separate Alfa PRO transport/vendor investigation; UI PASS is not root-cause or post-update recovery evidence.
- Grok's SQLite date-binding warning cleanup is P3; OpenAPI/pyright pilots and branch-cleanup inventory are later optional work. Do not start them automatically or redesign release triggering.

The preserved `integration/post-release-uat-wave` branch is historical staging, not another main. No release was published or local Stable/Preview updated by these GitHub merges.

## Completed foundations and deferred scope

Native parity #570/#571/#643 and the original #572 Owner gate are complete. Portfolio/account Performance Phase A is delivered; class-return #535/#540 and the remaining #541 scope are separate, not inferred from allocation or monetary-result tables. #528 coordinates the later Performance choices.

Data-integrity #484–#498/#536–#539 and #621–#624, Decision Support v1, and owner durability #417 remain accepted. Prior closeouts are retained: [data integrity](DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md), [durability](OWNER_DURABILITY_CLOSEOUT_2026-09-25.md), [Decision Support](DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md), [Performance v1](PERFORMANCE_V1_CLOSEOUT_2026-09-12.md).

Deferred: #629 launcher removal with dependency/runtime review, #630 representative synthetic stand, #573 explicit v1-retirement decision, #389 dashboard composer. `/v1` stays. #124 is permanent release infrastructure; #127/#528/#554 are coordination, not automatic implementation queues.

## Operating boundaries

Stable is pinned to a published release, not development main. Control is a separate trusted code checkout; Preview is exact-SHA and has its own Owner-only data. User paths belong in local configuration, not tracked machine-specific absolute paths. [Owner runtime operations](OWNER_RUNTIME_OPERATIONS.md) define supported Prepare/Validate/Start/Preview/Stable-update commands; dated version examples there do not override this checkpoint or live release evidence.

Single-user Windows, `127.0.0.1:8000`, exact money, explicit provider actions, authoritative backend and CLOSED guards remain unchanged. Owner DB/.env/backups/exports never enter Git, CI or agent workspaces. Publication and backup-first local Stable update require their separate Owner decision.
