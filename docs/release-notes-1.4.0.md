# Hermes Finance 1.4.0

Selected **v1.4.0 code/Test candidate:** accepted `main@e487d57080dca0eb88484adeda52c51889b9fd5d`
(2026-10-24), including merged #953 backend Close and #954 Month UI. Backend/frontend
manifests, locks and health identity use 1.4.0. [Exact post-main push CI](https://github.com/LTstripes/hermes-finance/actions/runs/40099148969)
is SUCCESS. The bounded Month code is frozen for this release; another main change
requires an exact candidate decision. **No 1.4.0 GitHub Release or Stable update exists yet.**
Latest Test/O4 and production gates are in [CURRENT_STATUS](CURRENT_STATUS.md) and [#940](https://github.com/LTstripes/hermes-finance/issues/940).

Keep the canonical path `docs/release-notes-1.4.0.md`: the installed v1.3.0 updater reads
that path in the target commit. Publication requires accepted canonical main, exact-main
push CI, Integrator's #124 request and independent annotated-tag / peeled-SHA / Release
readback under [O3](OWNER_RUNTIME_OPERATIONS.md#o3).

## Changes since v1.3.0

- Source-intake journal (#889) retains statement facts, original identity and append-only
  review evidence. Save/ACK/readback/replay are distinct from financial Apply or Close.
  Multi-file upload on `/v2/capital/monthly-returns` (#917) exposes each file's independent
  save/readback/retry state. A GET retry does not re-upload an original.
- Monthly source/account returns (#911/#913) separate contributions and withdrawals from
  growth; provide provisional Modified Dietz estimates, an approximate chained return and
  period XIRR. Missing boundaries/unknown flows remain unavailable with reasons. Closing-day
  flows have zero Dietz weight. Long reports do not invent intermediate month ends.
- Per-instrument returns (#915, #891/#945) retain the legacy simple percentage and NULL all-time
  legacy rate, and add dated events, current payout attribution, quantity/cash reconciliation,
  monthly or selected-interval RUB P&L and Modified Dietz under `instrument_return_v2`.
  The new rate is a Decimal fraction, not the legacy percentage. Full economic results,
  known subtotals and conditional statement-value estimates remain distinct. Unknown bond
  valuation basis withholds full economic P&L/MD. Read-only instrument surfaces (#949/#951) and bounded Owner-local Test UAT are now delivered; neither proves full bond economics or unsupported historical coverage.
- Audit fixes (#924/#926/#928) tighten nominal/NKD, boundary/scope, flow coverage,
  short-period XIRR and Decimal behavior. MyBroker statement/account support (#932) preserves
  native evidence rather than filling unknown operands with zero.
- Promo/gift payouts are external top-ups; unknown money stays NULL (#934). Dividend
  classification is narrower (#933). Defaults remain provisional; user choices survive re-save.
- Nullable payout/instrument identities (#936) and an initially empty, Owner-editable
  registration-number → ISIN crosswalk (#939) support explicit resolution/relinking. Private
  seeds/Test classifications are not release assets or migration inputs. Relink reports counts,
  not an unresolved-row list.
- #935 closes B2 across applied S3, WHAT-IF, historical and provisional paths, including the
  corrected duplicate diagnostic; renamed import behavior is retained. Its independent review
  and exact candidate/main CI are linked from [#940](https://github.com/LTstripes/hermes-finance/issues/940).
- The ordinary **«Месяц»** workspace (#950/#951) combines manual-data links, multi-original
  statement intake, account-scoped source review and exceptions. It keeps actual versus
  possible-paid versus future forecasts distinct and preserves strict Apply/Close authority.
- Read-only stock returns, bond conditional estimates and T-Invest payout preview (#946/#949/#951)
  are surfaced without fabricating missing clean/dirty/NKD or automatically accepting source
  evidence. Unsupported full bond returns stay NULL. No live T-Invest was called during Test UAT.
- The server empty-month policy (#952/#953) blocks ordinary empty MANUAL-DRAFT Close. Explicit
  saved zero counts; cloned income/expense/saving templates and legacy UNKNOWN origins do not.
  The separate intentional-empty Close requires a fresh exact-period reason, writer guards and
  immutable audit/receipt. No financial or synthetic-zero backfill occurs.
- The corresponding UI (#954) requires explicit consent, exact period and server eligibility;
  unknown ACK, Back and Reload allow GET-only recovery without a second Close command.
  Real October Close was not executed; success/lost-ACK command cases were synthetic.
- Security/CI/docs maintenance includes #929, #916/#918/#919/#920/#941. Release notes retain
  full CI classification; a docs-only verdict is not a release gate.

## Database transition: 0058 → 0064

Published v1.3.0 (`a9c88266fffe26e83688c52fc8f425b04fa14812`) supports
`0058_broker_money_ownership`. The selected head is `0064_month_template_provenance`.

| Revision | Effect and preservation boundary |
| --- | --- |
| `0059_source_intake` | Adds journal/observations/review structures. No original import or financial promotion. Populated journal refuses downgrade. |
| `0060_source_money_classifications` | Adds provisional classifications. No legacy backfill; missing classification is explicit. Downgrade loses choices. |
| `0061_money_instrument_links` | Adds nullable link/registration/issuer fields, index/checks/FK through SQLite batch alteration. Existing rows stay unprocessed/NULL; no automatic relink. Downgrade loses link fields. |
| `0062_security_reg_isin_mappings` | Adds an empty crosswalk. No private seed. Downgrade drops mappings; re-upgrade does not recover them. |
| `0063_intentional_empty_close` | Adds an initially empty immutable Close audit/receipts table and triggers. No existing financial data or zeros are invented; populated audit rejects downgrade before DDL. |
| `0064_month_template_provenance` | Adds nullable actual/template provenance to income, expense and saving rows. Clone writes `clone_template_v1`; explicit amount confirmation writes `saved_actual_v1`; old NULL stays UNKNOWN. Populated origin/audit rejects downgrade. |

Forward migration must preserve existing CLOSED/DRAFT/history/receipts/provenance;
released migration sources, including `backend/migrations/README`, stay unchanged.
See [#954's consolidated receipt](https://github.com/LTstripes/hermes-finance/pull/954#issuecomment-6385205231)
for the actual Test 0062→0064 migration and synthetic migration/backup evidence.
Neither demonstrates a real Stable 0058→0064 migration or return to old code.

## Update and recovery

Follow the [candidate checklist](releases/1.4.0-test-run.md),
[recovery disposition](releases/1.4.0-rollback.md) and O3/O4. Owner-local Test **O4 PASS**
covers a managed plaintext synced backup, independent cloud SHA256 readback, and detached
same-revision **0064→0064** restoration with 76 matching table fingerprints. It does **not**
prove the existing Stable 0058 source, a **0058→0064** rehearsal or production rollback.

Before a production Start, verify Stable's real 0058 binding; collect a fresh authentic
managed 0058 point in the already Owner-accepted `owner_accepted_plaintext` /
`synced_filesystem_destination_v1` mode, confirm its independent readback, and exercise
one fresh isolated **0058→0064 forward** route with the selected published/prepared release.
The checkpoint RPO/cutoff and residual outage/forward-fix risk need explicit Owner approval.
If that cannot be established, remain HOLD; never downgrade or run old code on migrated data.

After acceptance/publication: stop owned runtime → one backup-first OPS02 from trusted
Control outside Stable with explicit existing physical `-DatabasePath` and disjoint
`-BackupDirectory` → verify pin/Prepare/Validate → separate stock Start on that same DB.
OPS02 does not read Stable's `.env` fallback, migrate or Start. Start migrates the DB.
No Test-data copy, private seed, bulk history reimport, Apply, Close or Reopen belongs here.

## Evidence and limits

Use [#954's one consolidated Test/O4 receipt](https://github.com/LTstripes/hermes-finance/pull/954#issuecomment-6385205231)
as attributed Owner-local evidence: Test installed at `e487d57080dca0eb88484adeda52c51889b9fd5d`
and schema 0064, ten retained original statements plus mappings/manual/history, bounded
Month UAT PASS, independently downloaded cloud backup with SHA256 match and detached O4
restoration/readiness PASS. The cloud Integrator verified GitHub records, not private DB bytes.
No real October Close/Apply/Reopen, live T-Invest or Stable changes were performed.
Release identity, Stable 0058 backup and explicit recovery-risk approval remain separate.

Source returns remain provisional (`financial_authority=none`). Approximate Dietz/chained
rates are not exact TWRR. Instrument results are not cost-basis/net-of-tax accounting.
Missing/non-RUB/unsupported/conflicting facts remain NULL with reasons. Bond valuation and
assumed face/NKD basis remain explicit limitations; payouts are not counted twice as investor
flows. Owner account checks do not remove those limitations.

Parser-generation drift fails closed. Retain unchanged originals for a separately accepted
fresh rebuild; no manifest rewrite, trigger removal or in-place V1 reparse bypass. Reported
reg-ISIN CLI non-UTF8 output/`~` path issues remain outside this preparation. Private instrument numerical UAT, history loading, the instrument UI and forecast-ingestion seams remain separate work.
