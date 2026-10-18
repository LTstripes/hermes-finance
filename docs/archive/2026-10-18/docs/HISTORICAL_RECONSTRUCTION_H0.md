# Historical reconstruction H0 — read-only inventory

Authority: [#720](https://github.com/LTstripes/hermes-finance/issues/720), the
[#709 plan](https://github.com/LTstripes/hermes-finance/issues/709#issuecomment-6025043634)
and its [Integrator acceptance](https://github.com/LTstripes/hermes-finance/issues/709#issuecomment-6025126898).
Consumes accepted [S1](MYBROKER_S1.md) and [S2-A](MYBROKER_S2_A.md) identities and readers.

`POST /api/historical-reconstruction/preview` takes only a selection:

```json
{
  "account_ids": [1, 2],
  "requested_from": "2030-01-01",
  "requested_to": "2030-03-31"
}
```

Dates and accounts above are synthetic. Select every account relevant to the
intended scope, including non-MyBroker accounts. This API reports the explicit
selection; it does not infer a portfolio universe from current inclusion flags.
Missing source or historical membership for a selected account remains visible.
Selections allow up to 100 distinct existing Hermes accounts and 36,600 days.

The response exposes structural evidence only:

- Confirmed source report ranges, their inclusive gaps/overlaps inside the
  request, and dated observed event ranges. Confirmed quiet ranges do not prove
  economic completeness. Earliest source event and earliest active accepted
  canonical execution are separate, across all accepted history for the selected
  account. `earliest_accepted_canonical_execution` includes active accepted pending
  and settled identities; lifecycle and current conflicts remain separately visible.
- Beginning and ending observations are evaluated independently. Beginning uses
  the actual previous-day EOD, including leap-day; ending uses report-end EOD.
  Both boundaries of an intersecting report remain visible even outside the
  request. The monthly matrix joins only exact dates, never interior or nearest
  month-ends. Source component observations remain distinct from complete
  endpoint acceptance. An observed RUB zero is a cash observation only.
- Side-specific missing quantities/values/cash, common source integrity and
  mapping blockers, opaque Transfers/UFSR/unknown sections, repo/incomplete IDs,
  negative states and pending/forward/cash/custody exposure. Opening settled
  inventory is unproven even when ending actual and forward quantities agree.
  Actual S1/S2-A cash-leg dates, including later commissions and money-only
  source enrichment, independently constrain the cutoff. Current source candidates
  may strengthen blocking but cannot clear frozen canonical cash/pending exposure
  until explicit S2-A enrichment. Planned dates never clear a pending cut.
- Historical membership intervals, gaps/overlaps and cutoff inclusion, without
  using today's account inclusion or instrument class as historical evidence.
- Existing month-owned fact categories for the account, month status and exact
  snapshot date, including CLOSED and DRAFT facts. No March boundary is hard-coded.
  Overlap is reported for review; source values are not compared or reconciled.
- Informational S2-A `create/enrich/noop` candidate operations and blockers,
  using the existing source digest; identity-less observations remain unpromotable.
  These operations are not executed by H0. H0 has no Apply route.

`preview_digest` identifies the selection and committed source/mapping/canonical,
membership, month, target and dependent evidence state. Every call rereads one
query-only SQLite snapshot, including when a Session is reused. This digest is
an inventory review identity, not an Apply confirmation or an acceptance token.

Event-history observation, exact source endpoint acceptance, monthly
materialization, account/portfolio XIRR, class no-crossing/crossing XIRR and exact
TWRR availability are separate fields. H0 does not call solvers or reinterpret
existing Hermes return availability. Complete source endpoints/materialization
require the separate H1 contract; return consumers remain unevaluated here.
Opaque section event dates cannot be recovered from S1's retained structural flags.
Quiet/empty reports, missing securities or missing cash never establish zero
capital, inception or complete financial coverage.

No migration, persistence, financial mutation, coverage promotion, provider
request, backfill, price/class/cost/P&L inference or month close/reopen occurs.
The output excludes native source identifiers, holdings, amounts, filenames,
raw XML and arbitrary source text. Hermes IDs, source identity digests, dates
and structural flags support Owner-local review. Do not publish Owner-local
reports or responses as agent/GitHub artifacts; synthetic tests supply evidence.
Independent candidate review, Integrator acceptance and applicable Owner UAT
remain separate from CI and from this read-only Preview.

## Synthetic timeout diagnosis (#709)

The [bounded Integrator assignment](https://github.com/LTstripes/hermes-finance/issues/709#issuecomment-6067013225)
was reproduced from main `5144b71b05537a540b2ac11ae9e66ea751bb1446`
with four synthetic accepted S1 imports, two explicitly mapped accounts and
500 distinct settled trades with settlement money rows per import. All four
reports covered January through March 2030; H0 selected both accounts from
2029-12-31 through 2030-03-31. Setup used the existing fabricated XML fixture,
cloned its trade/money rows with distinct two-part IDs and accepted the reports
through S1 Preview/Apply. No Owner/runtime data were read.

| Measurement, same committed synthetic database | Baseline | Fixed |
| --- | ---: | ---: |
| Loopback HTTP backend duration, without profiler | 66.44 s | 4.50 s |
| Client, unchanged 45-second read deadline | ReadTimeout at 45.36 s | HTTP 200 at 4.77 s |
| Profiled service duration | 76.53 s | 5.92 s |
| Service SELECT statements | 22,067 | 4,050 |
| Disposition resolver calls in profiled service | 8,012 | 4 |
| Candidate operations returned per account | 1,000 / 1,000 | 1,000 / 1,000 |

On the baseline, `excluded_trade()` reloaded and decoded the full import union
for every S2 candidate; that path consumed 67.53 s of the profiled request.
H0 also resolved the same dispositions again per selected account. The fix
reuses the complete disposition evidence already resolved by the request's
S2 context. Its identity set and account filtering live only in that context,
inside the existing coherent read snapshot. The next request resolves anew.
Accepted, revoked, retired and invalid exclusions all retain their impact;
there is no date expiry or successful-state filter.

The complete H0 response, including `preview_digest`, was equal before/after
on the same database. All persisted tables remained equal, and both HTTP
probes recorded no INSERT/UPDATE/DELETE/REPLACE. Normal CI regressions in
`test_statement_import_historical_reconstruction.py` check one resolver call
per import with five imports/two accounts, accepted canonical evidence,
overlaps, both endpoint sides, skipped trades, identity-less B REPO and fresh
revoked/retired/invalid evidence through a reused Session. The baseline failed
the call-count assertion (42 calls instead of five); the fix passed. Existing
source/canonical/financial guard tests remain applicable.

This proves a backend scaling cause for the synthetic timeout. The H0 route
has no 45-second backend deadline; the frontend has no H0 consumer or built-in
45-second request deadline. The original private Test caller's deadline,
workload and process lifecycle were not inspected, so its precise cause and
successful H0 completion remain unverified. A separate protected Owner-local
read-only validation must record the exact candidate, selected accounts/range,
client deadline, elapsed time and complete structural readback. Synthetic
success does not prove financial completeness or Owner UAT.

This patch does not bound every remaining hot loop or promise a universal
45-second completion time. It preserves full union/Skip/REPO evidence and the
financial guards without schema, source semantics or deadline changes.

## Owner-local Test H0 speed acceptance (2026-10-08)

The exact optimization candidate in [PR #741](https://github.com/LTstripes/hermes-finance/pull/741), `9f028150475bb14dfb3c43c8bdbb9d6e2512e2fc`, passed independent read-only review [5461891387](https://github.com/LTstripes/hermes-finance/pull/741#pullrequestreview-5461891387) and exact-candidate [CI 37831179270](https://github.com/LTstripes/hermes-finance/actions/runs/37831179270). Canonical merge: `e2864668a7357365656ace4ac681288313d0ee9f`; exact push CI [37835529213](https://github.com/LTstripes/hermes-finance/actions/runs/37835529213) is a separate gate, whose live result should be checked before calling integration complete.

Owner-local isolated Test on the exact candidate (reported by the local operator, not independently rerun by the Integrator) used the original H0 Preview API in SQLite read-only mode with an unchanged 45-second caller deadline. Both complete HTTP 200 responses took **0.538s / 0.524s** and their full bodies and `preview_digest` matched. Test schema `0054`, all database tables/file bytes, 18 prior report responses and three source GETs (Skip/REPO included) were unchanged; zero SQL writes, no reimport or migration. Protected isolation, fresh verified backup and OPS03 Prepare/Validate passed; no listener remained.

The old timed-out attempt left **no complete H0 response** for old-vs-new payload comparison. The exact cause of the earlier private timeout cannot be established from a missing result, and ordinary Start/shutdown smoke was not repeated. These constraints do not invalidate the bounded successful read-only inventory UAT. H0 has **no financial Apply** and does not accept actual endpoint valuations, owner cash-flow completeness or real XIRR/TWRR. Parent #709 remains open for that separate financial proof.
