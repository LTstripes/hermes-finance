# Durable MyBroker source intake — #889 first slice

Authority: [accepted first slice and lifecycle amendments](https://github.com/LTstripes/hermes-finance/issues/889#issuecomment-6251043135).
This is a local non-economic journal, not a partial financial writer. The existing
strict source-month Preview/Apply/independent GET is still the only financial path.
The [#888 source result](https://github.com/LTstripes/hermes-finance/issues/888#issuecomment-6248776412)
permits observations only. June source identity, REPO economics/custody/cash scope
and financial DRAFT remain blocked; catalogue/EOD audits are not repeated here.

## Saved evidence and progress

Migration `0059_source_intake` adds three empty tables:
`source_intake_originals`, `source_intake_observations`, and
`source_intake_revisions`. They retain original hash/length/filename digest,
period/native accounts, all recognized occurrences, a bounded whole-tree
structural inventory, and append-only review/policy/link history. Structural
inventory stores tag/attribute names, value/text fingerprints, child counts and
bounded native account/ISIN/trade/REPO partner references. Unknown attributes,
including numeric zero, receive no economic authority. A partner reference is not
a second execution ID. Frozen S1 and accepted financial receipts are unchanged.

Raw XML, filenames/absolute paths, browser File objects and arbitrary source
narratives are not cached. Originals remain with the Owner. Reload retains the
queue and decisions; mutation/reparse requires reselecting the exact original.
The server rechecks bytes, filename authority, manifest, versions and current
dependencies. Parser/generation drift refuses rather than silently reinterpreting
stored observations. Browser storage and implicit outbound lookups are absent.

The first intentional save records the already Owner-authorized RUB preference.
`owner_default_rub` and explicit account/instrument overrides are revision-backed
proposals. They do not attest denomination, settlement/quote units, NKD, tax or
completeness, and do not create Instrument or mapping rows. Existing catalogue,
official nominal evidence, Owner selection, default, unknown and conflict remain
distinct. Explicit official FX evidence is retained with provenance; expiry or
cache loss leaves a stale exception and never converts it into assumed RUB.
The public lookup remains opt-in/session-local; journal reads never fetch data.

## API and transaction boundaries

All routes are under `/api/broker-months/intakes`:

| Route | Effect |
| --- | --- |
| `POST /` | Multipart original + typed save intent/request ID; save complete observations and optional explicitly reviewed account/month attachment. No financial effects. |
| `GET /`, `GET /{id}` | Independent coherent read of current proposals, full saved observations, history, binding and blockers. List supports month filtering and optional unbound observations. |
| `POST /{id}/review-preview` | Original + grouped decisions/expected head; zero writes/network; returns digest and zero financial effects. |
| `POST /{id}/decisions` | Original + exact reviewed digest/request ID; append decisions/policy/overrides only. |
| `POST /{id}/finance-link` | Same reviewed command protocol, referencing an existing strict SOURCE receipt; append a link only. |

Save/decision/link commands reserve SQLite's writer before revalidation and commit
one transaction. Stale heads, changed original/dependencies, unsupported flags or
forked journal refuse. Same request/intent is read-only replay; another intent with
that request ID conflicts. Native occurrences are not duplicated on repeated
upload. Policy/decision/dependency revisions detect A→B→A. Restore admission epoch
and process incarnation invalidate outstanding review confirmations even when
restored values and sequence numbers match. Committed journal evidence survives
the supported SQLite online-backup/restore path.

An ACK followed by failed GET recovers by GET, without another POST. A financial
commit followed by missing link recovers by financial GET then idempotent link,
without another financial POST. Link acceptance checks exact original/generation,
account/period, accepted S1, strict receipt and its own live projection/source
authority under the writer reservation. It does not require aggregate Close
readiness, which includes the unsatisfied intake and would create a circular gate.
Incomplete strict receipts keep their financial/source blockers. Links become
ineffective on affected authority/decision/ABA changes; history remains intact.
Current journal identity conflicts, evidence gaps and explicit deferrals remain
pending even when an earlier strict SOURCE receipt is otherwise clean. Link preview,
reserved confirmation and every GET revalidate all current journal choices against
the exact accepted S1 mappings and receipt instrument binding. An incompatible choice
or deferral requires explicit journal resolution before fresh linking; an old link
cannot waive it. Acknowledged replay never restores the effectiveness of an old link.

## Binding, consumers and protected lifecycle

Unbound viewing creates no obligation for unrelated months. Binding requires an
exact native account/period and editable final-day DRAFT, with explicit alias
selection and existing conflict/revocation guards. Once bound, defer/unbind/rebind
cannot remove the obligation. Generic month DELETE and snapshot geometry changes
are explicitly refused under the writer reservation before bulk child deletion;
DELETE→recreate cannot erase journal history. CLOSED mutation remains prohibited.

One scoped resolver supplies account readiness, reserved server Close, statement
returns, actual source cash coverage, exact-performance and historical-XIRR
consumers. New unresolved evidence applies even when the account already has an
accepted financial receipt or numeric return. Unrelated account/month/manual
behavior is unchanged. The ordinary known-subtotal formula and historical
account-presence coverage are preserved. A separate
`source_account_financial_coverage` accompanies summary/Capital coverage; AI and
Markdown exports retain the corresponding partial defects. Presence is not
complete financial coverage, and unknown values are never zero.

All three tables are append-only at SQLite level. Dependency tokens contain only
table/row identity and old/new account, month and event-date scope, and are recorded
once an intake exists. Financial row edits, moves and delete/recreate cannot revive
a previous link after A→B→A; fresh explicit linking is required. Unrelated financial
scopes do not retire the link. Ordinary installations
without an intake acquire no journal history from unrelated catalogue edits.
Downgrade refuses any populated intake journal. Upgrade/downgrade does no financial
backfill and is not automatically deployed to Owner/Test/Stable by this code task.

## Explicit remaining boundary

No assumed global card, financial `broker_source_partial_v1`, filtered S1, arbitrary
12-of-13 positions/cash, REPO economics, accepted-finance correction/retirement,
FX engine, new Skip or Close waiver is implemented. Those remain the separately
gated continuation in #889. Synthetic/Windows desktop evidence is not June/July
Owner financial GO or UAT and does not authorize protected runtime operations.
