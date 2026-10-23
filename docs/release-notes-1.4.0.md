# Hermes Finance 1.4.0

Release preparation from accepted main `418b88a8c9a1b9b8e5f2d72e6112426282f3d285`
(2026-10-23), after #935. Backend manifest/package/uv lock, frontend manifest/lock and
current health/identity checks use 1.4.0. This publication-ready content does not assert
that a tag, Release or Stable update exists. Current disposition belongs in
[CURRENT_STATUS](CURRENT_STATUS.md) and the release PR.

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
- Per-instrument returns (#915) expose available price-effect/payout components and
  partial/missing coverage/NKD flags. The current rate uses `total / (opening_value + all_buys)`;
  all-time percentage remains NULL. The new #891 changing-quantity event/Dietz implementation
  is outside this release.
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
- Security/CI/docs maintenance includes #929, #916/#918/#919/#920/#941. Release notes retain
  full CI classification; a docs-only verdict is not a release gate.

## Database transition: 0058 → 0062

Published v1.3.0 (`a9c88266fffe26e83688c52fc8f425b04fa14812`) supports
`0058_broker_money_ownership`. The selected head is `0062_security_reg_isin_mappings`.

| Revision | Effect and preservation boundary |
| --- | --- |
| `0059_source_intake` | Adds journal/observations/review structures. No original import or financial promotion. Populated journal refuses downgrade. |
| `0060_source_money_classifications` | Adds provisional classifications. No legacy backfill; missing classification is explicit. Downgrade loses choices. |
| `0061_money_instrument_links` | Adds nullable link/registration/issuer fields, index/checks/FK through SQLite batch alteration. Existing rows stay unprocessed/NULL; no automatic relink. Downgrade loses link fields. |
| `0062_security_reg_isin_mappings` | Adds an empty crosswalk. No private seed. Downgrade drops mappings; re-upgrade does not recover them. |

Forward migration preserves existing CLOSED/DRAFT/history/receipts/provenance. Released
migration sources, including `backend/migrations/README`, remain unchanged. Candidate tests
exercise direct 0058→head and every hop with synthetic CLOSED/history rows, integrity/FK,
online-backup readback and isolated forward recovery. This is not production rollback.

## Update and recovery

Follow the [candidate checklist](releases/1.4.0-test-run.md),
[recovery disposition](releases/1.4.0-rollback.md) and O3/O4. Integrator must resolve recovery
before production migration: stock OPS02 refuses older target versions even before DB mutation;
in-app restore requires an exact schema signature; O4 writes only a fresh isolated target.
No stock procedure returns migrated Stable to the old code/database pair.

After acceptance/publication: stop owned runtime → one backup-first OPS02 from trusted
Control outside Stable with explicit existing physical `-DatabasePath` and disjoint
`-BackupDirectory` → verify pin/Prepare/Validate → separate stock Start on that same DB.
OPS02 does not read Stable's `.env` fallback, migrate or Start. Start migrates the DB.
No Test-data copy, private seed, bulk history reimport, Apply, Close or Reopen belongs here.

## Evidence and limits

Reuse [#940 Owner/Test evidence](https://github.com/LTstripes/hermes-finance/issues/940):
monthly account results/multi-account upload were checked at earlier Test baseline
`31e7b41d444945ed5ae5c4e4a813997329c3a354` / 0062 with a private seed. This is attributed
local evidence, not per-instrument numerical UAT, new release identity or seedless Stable
mapping acceptance. Reuse #935's accepted review/CI only for its covered behavior; release
packaging needs its own exact-candidate CI and Integrator disposition.

Source returns remain provisional (`financial_authority=none`). Approximate Dietz/chained
rates are not exact TWRR. Instrument results are not cost-basis/net-of-tax accounting.
Missing/non-RUB/unsupported/conflicting facts remain NULL with reasons. Bond valuation and
assumed face/NKD basis remain explicit limitations; payouts are not counted twice as investor
flows. Owner account checks do not remove those limitations.

Parser-generation drift fails closed. Retain unchanged originals for a separately accepted
fresh rebuild; no manifest rewrite, trigger removal or in-place V1 reparse bypass. Reported
reg-ISIN CLI non-UTF8 output/`~` path issues remain outside this preparation. Full instrument
economic return and forecast-ingestion seams remain separate work.
