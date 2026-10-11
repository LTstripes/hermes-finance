# MyBroker original-bound identity Preview and staging

Authority: [#771](https://github.com/LTstripes/hermes-finance/issues/771),
[#768 accepted amendment](https://github.com/LTstripes/hermes-finance/issues/768#issuecomment-6106797516)
and [confirmed metadata manifest](https://github.com/LTstripes/hermes-finance/issues/771#issuecomment-6106946806).

`POST /api/mybroker-import/identity-preview` accepts the unchanged original XML
and strict source-range filename, plus optional multipart `intent` JSON:

```json
{"account_bindings": [{"identity": "1234567-000", "hermes_id": 1}]}
```

The example is synthetic. Filename account and every row account remain separate
aliases. An existing effective mapping supplies its accepted binding; a new alias
requires an explicit account binding in the reviewed intent. Accounts are never
created or inferred from names, external codes or suffixes. All aliases in one
original must resolve to the same brokerage/IIS account. Duplicate request aliases
and duplicate resolved position aliases block the entire batch.

The `mybroker-identity-v1` envelope reparses authoritative bytes using the bounded
`mybroker-s1-v2` family and adds metadata separately. Existing S1 normalized rows,
source acceptance, receipts, Skip and correction lifecycle remain unchanged.
There are no invented root dates. The Preview binds the original hash, filename
range/account, parser identities, observed row accounts/ISINs/type/names/custody,
trade currency observations, proposals and current dependency revision. Its
confirmation digest is deterministic. Preview uses the committed read-only
snapshot and writes nothing.

Only row-level Positions `active_type=Акции|Облигации`, `active_name`, `ISIN1`,
`acc_code` and `place` provide security metadata. Completed Trades supplies
`isin_reg`, `p_name`, `acc_code`, `curr_calc` and `Textbox14`. Contradictory
`curr_calc`/`Textbox14` observations refuse the entire batch with
`trade_currency_observation_conflict`, without deriving security denomination.
Trade type must link
to Positions by exact account and ISIN. Trade-only type remains unproven; names,
group placement and current catalogue type cannot manufacture source authority.
Unknown/unparsed rows, invalid ISINs, unsupported asset types, REPO, account/type/
mapping alias conflicts and incompatible revoked bindings refuse the whole batch.
Opaque UFSR/transfer source warnings remain visible; identity eligibility does not
attest their financial semantics or source completeness.

## Currency limitation in the confirmed original

The confirmed stock/bond Positions shape has **no security denomination field**.
`curr_calc=RUB`, `Textbox14=RUB`, the RUB cash row and source valuation totals do
not establish `Instrument.currency`. Preview therefore proposes new stock/bond
metadata with `currency=null` and the typed `instrument_currency_unproven` gap.
The whole batch has `can_stage=false`; compatible rows are not partially persisted.
No database/application RUB default is used as evidence. Nominal, ticker and quote
are not derived from source totals or trade prices.

A compatible existing global Instrument is reused, including inactive instruments,
with its existing currency and metadata preserved. The Preview labels that currency
`existing_catalogue`; source currency remains separately `unproven`. One instrument
mapping is global across accounts. Exact replay/overlap reuse the same identity and
effective mapping. Instrument/account/source changes, including A→B→A changes in
the existing monotonic correction journal, retire the old Preview.

New-card staging requires a separately accepted authoritative currency source or
compatible model sub-slice. This PR adds neither a trusted-reference resolver nor
nullable Instrument denomination, provider calls or a currency override input.
The manifest's currency gap is an explicit creation blocker, not an automatic Skip.

## Internal transaction contract for the later S2 writer

`services.mybroker_identity.stage_identity` is a Python helper, with **no HTTP
Apply route and no commit**. Call it before staging month facts, using original
bytes/filename, the reviewed account intent and confirmation digest. It reserves
SQLite's single writer with the existing no-op source-ledger UPDATE, expires ORM
state and recomputes the entire plan under that same writer reservation. A stale
digest or any conflict/evidence gap refuses before identity writes.

All identity/mapping staging uses one savepoint and the existing mapping lifecycle
helper with `commit=False`. A flush error rolls back all staged identity rows;
success retains the outer writer transaction and returns the exact mapping IDs.
The later source→month orchestrator owns its single final commit, and must roll
back the outer transaction on any later failure. The helper does not accept source
lineage, create a month, write positions/cash/income/trades, Close or reconcile Skip.
Callers must not expose it as a permanent standalone metadata Apply.

Synthetic regressions cover confirmed field placement, typed new-stock/bond gaps,
inactive catalogue reuse with a currency differing from settlement, two accounts
sharing one global instrument, replay/overlap, aliases, revoked mappings, legacy
Skip, original/range/catalogue/mapping/source staleness, savepoint failure and
independent-session visibility/outer rollback. Real new-instrument Owner UAT and
source-month financial acceptance remain later gates.
