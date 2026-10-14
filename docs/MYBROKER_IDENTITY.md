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
In the standalone identity contract, unknown/unparsed rows, invalid ISINs, unsupported asset types, REPO, account/type/
mapping alias conflicts and incompatible revoked bindings refuse the whole batch.
Opaque UFSR/transfer source warnings remain visible; identity eligibility does not
attest their financial semantics or source completeness.

## Incomplete DRAFT structural separation

The source-month writer alone selects internal `incomplete_draft=True` for both
Preview and writer-reserved identity staging. The standalone identity Preview and
ordinary staging remain strict; no HTTP intent flag can waive source warnings.
`mybroker-incomplete-draft-identity-v1` rechecks the original tree and can defer
only structurally bounded Positions/Money side branches. The original byte hash,
classifications and contract version participate in the identity confirmation
digest. Originals without these exceptions retain their existing identity shape.

The bounded grammar includes the exact populated NDFL `Tablix3` three-attribute
leaf (unsigned D2), Money beginning/ending scalar wrappers, daily scalar displays,
the `Textbox116` summary, operation-group summary and three exact empty trees.
Money numeric displays use bounded signed decimals (48 characters) with exact
minor-unit representation; sub-kopecks are rejected without rounding. Daily
displays are explicitly empty before each group's last rn and populated together
only on that last rn; missing, empty and numeric zero remain distinct.
Currency labels are literal RUB. Tablix7 accepts only three complete ordered
label sequences under [#828](https://github.com/LTstripes/hermes-finance/issues/828):
[`Внесено по распоряжению Клиента`, `Купоны`, `Списано по тарифам Банка`],
[`Внесено по распоряжению Клиента`, `Дивиденды`, `Купоны`, `Списано по тарифам Банка`],
or [`Дивиденды`, `Купоны`, `Списано по тарифам Банка`]. Each group retains exactly
one childless p_code6/volume6 leaf under p_code6_Collection. This is not an optional
group grammar; totals do not classify dividend/coupon/fee events or Owner flows.
Keys, expanded namespaces, paths,
ordered children and singleton branches are checked, with no text/tail payload,
comments, processing instructions or nested namespace declarations. The complete
Money table order and net/operation child order match the accepted
[#804 manifest as amended](https://github.com/LTstripes/hermes-finance/issues/804#issuecomment-6129597801).
After projecting these branches out of a temporary tree, every remaining node
must lie on an actually consumed S1 Positions/Trades/Money path. Retained-node
attributes are restricted by exact path to consumed row keys or enumerated
caption keys; grouping wrappers accept no attributes. Fixed path cardinalities,
consumed S1 row counts, original hash and source inventory remain binding. Root
attributes match the exact family including Textbox6; sections remain ordered.
Only one observed row-account/RUB context is eligible; aliases still require
separate explicit mappings. Source cash/quantity mismatches remain conflicts.
Unknown roots,
extra/moved rows, hidden account/ISIN/native-ID attributes inside an exception,
malformed/foreign/duplicate shapes and all existing semantic conflicts still
refuse the batch. Optional branches are not inferred when absent.

This is identity eligibility for an explicitly incomplete DRAFT, not safe-layout
or financial acceptance. Values are never interpreted, summed or substituted.
The envelope reports `financial_authority=none` and unresolved tax/Money
classifications. S1 parser, normalized JSON, fingerprints, source warnings and
legacy receipts stay unchanged; `unparsed_source_rows` remains a source exception
and a server GET/Close blocker. Unknown tax/bond NKD, fee basis, native cash and
settlement ownership retain their existing controls. Real scratch, Apply and
independent GET/UAT require their separate Owner gates.

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
