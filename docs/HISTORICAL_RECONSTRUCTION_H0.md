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
  settled canonical execution are separate, across all accepted history for the
  selected account. Accepted executions retain current conflict disclosures.
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
  Current S1 projections cannot clear frozen canonical pending exposure until
  explicit S2-A enrichment. Planned settlement dates never clear a pending cut.
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
