# Current state, limitations and next actions

Evidence cut: 2026-10-18. This is the only regularly rewritten status page. Procedure/contract books describe stable rules; dated records remain snapshots. Current observations below come from GitHub decisions and explicitly attributed Owner-local receipts, without reading private originals/DBs in this documentation task.

<a id="s1"></a>
## 1. Code, published release, installed runtime and UAT are separate

| Object | Confirmed evidence and limit |
|---|---|
| Canonical main baseline | `ae302939d8f6fea4c0b15d854d62a8289c007502`, including #887 and #890. Exact [push CI 39151521923](https://github.com/LTstripes/hermes-finance/actions/runs/39151521923) SUCCESS, 14 applicable PASS/3 expected skips. This documentation candidate is based on that code; its own PR head/CI are reported in the PR. |
| Published release | [v1.3.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.3.0), release commit `a9c88266fffe26e83688c52fc8f425b04fa14812`, schema `0058_broker_money_ownership`. Later main includes source-intake migration 0059 and is a different point. |
| Installed HONOR Stable | [Owner-local #836 receipt](https://github.com/LTstripes/hermes-finance/issues/836#issuecomment-6222421447): backup-first OPS02, separate Start, original physical DB continuity, `0044 → 0058`, limited health/API/UI/reload checks. This is attributed local evidence, not a fresh live inspection by this docs Worker. |
| Test / disposable scratches | No present Test version/process claim is made from historical UAT. June and July source-only pilots used separate disposable scratches and were stopped; neither is protected Stable or a coherent multi-month financial ledger. |
| Workspace operations | Accepted source implements recoverable retirement (#864), not legacy permanent Apply. This task found and used the installed matched lifecycle API for its new code-only clone; scheduler state and future retirement outcomes were not inspected or changed. |

[#836 freeze removal](https://github.com/LTstripes/hermes-finance/issues/836#issuecomment-6225429633) permits normal main development; it does not change published or installed versions. [#841](https://github.com/LTstripes/hermes-finance/pull/841) account WHAT-IF is merged after the published 1.3.0 cut.

<a id="s2"></a>
## 2. Accepted scope and retained limitations

June source-only UAT is accepted by [#885 June acceptance](https://github.com/LTstripes/hermes-finance/issues/885#issuecomment-6253758094): intact original → journal Save → ACK → independent GET → reload/reattach/replay/ABA; 774 observations. Local Worker and independent reviewer inspected private evidence; GitHub Integrator accepted their sanitized receipt. This is not financial DRAFT acceptance.

July source-only UAT is separately accepted by [#885 July acceptance](https://github.com/LTstripes/hermes-finance/issues/885#issuecomment-6253993218): 852 observations, unbound intake, Save→ACK→GET→process restart→GET; no metadata setup or financial effects. Two native pending→settled pairs passed bounded preflight, but the full July/August seam is UNKNOWN because one source side is missing. June 774 and July 852 are in different scratches: zero financial Apply/accepted receipts/common ledger. Do not repeat those accepted pilots as the next task.

[#889 §10.1 source-only intake](https://github.com/LTstripes/hermes-finance/issues/889#issuecomment-6253440076) is code/CI/source-only-UAT accepted. §10.2 partial financial writer is **NO CODE GO**. Strict June `can_apply=false`, zero accepted financial DRAFT; unknown REPO/pending custody/complete position universe/RUB endpoint ownership remains financial evidence, not default zero. Journal observations and matched identities/default RUB do not grant Close, accepted financial return or protected deployment.

[#889 parser-upgrade guard](https://github.com/LTstripes/hermes-finance/issues/889#issuecomment-6254134701): V1 stores original hash/length/filename digest and recognized facts/opaque structural fingerprints, **not raw XML**. Safe reload is not future reparse. Preserve exact Owner-retained original bytes and authority filename. Before any future enrichment/economic promise, prove one verified route: exact reattachment; new append-only parser/generation revision with lineage/cross-generation dedup/reviewed currentness; or explicit fresh disjoint rebuild with validated original/source/review crosswalk. Current V1 fails closed on parser drift. No manifest rewrite, trigger removal, bound-month deletion or DB-row copying bypass.

Instrument known payouts/EOD/trades and stock fixed-holding WHAT-IF are delivered bounded readers (#858/#860/#862/#865), not full changing-quantity stock/bond economic returns. [#867 UAT](https://github.com/LTstripes/hermes-finance/issues/867) remains PARTIAL. Source journal alone cannot satisfy the current accepted-receipt reader for #839. Exact XIRR/TWRR, Close and AI numerical exports still need their own supported evidence.

Bounded whole-portfolio RUB no-crossing class API/UI is delivered (#700/#701) with independent C1–C5 evidence prerequisites. Delivered capability is separate from current numerical readiness and Owner UAT scope; the attributed #836 receipt above is limited, not a claim every class/history is finance-ready.

<a id="s3"></a>
## 3. Current priorities, blockers and Owner actions

The [latest #554 decision](https://github.com/LTstripes/hermes-finance/issues/554#issuecomment-6254057157) separates three concurrent goals:

1. [#769 coherent approximately 18-month source history](https://github.com/LTstripes/hermes-finance/issues/769#issuecomment-6254012362): reuse accepted #821 zero-write batches of at most eight originals, account/period/seam/overlap checks and sequential journal intake into one new disjoint history lineage. Missing source/EOD stays UNKNOWN. This planning record is not a launch or financial-write authorization.
2. [#839 conditional account-period return](https://github.com/LTstripes/hermes-finance/issues/839#issuecomment-6253883555): useful provisional numbers require observed holdings plus RUB cash endpoints, dated external contributions/withdrawals and finite explicit crossing/REPO assumptions. It is more than price rise or balance delta; the current reader still requires accepted source receipts. No silent unknown→zero or Close waiver.
3. [#891 per-instrument economic result](https://github.com/LTstripes/hermes-finance/issues/891): planned coherent stock/bond RUB/% including purchases, sales, payouts, price changes, fees, taxes and paid NKD with honest partial confidence. Unsupported numbers remain null with reasons; avoid counting payout both inside account cash and again as an investor flow. #856 AI export depends on a supported numeric read model/UAT.

Broker inquiries remain separate: [#814 September NKD/settlement/commission question](https://github.com/LTstripes/hermes-finance/issues/814) is **SENT, Owner-reported**, written reply unverified; [#888 June REPO/custody/RUB cash question](https://github.com/LTstripes/hermes-finance/issues/888) is privately drafted and **NOT SENT**. The intervening “both UNSENT” note was superseded by latest #554. No broker communication was performed in this task. Official clarification may strengthen exact accounting; it is optional for explicitly hypothetical results and is not a nonexistent reply dependency.

No new financial worker/runtime operation is launched by these status edits. Finance Integrator owns acceptance and guarded integration. This documentation Worker opens one PR and does not merge, publish, update Stable, Start, Apply or Close.

<a id="s4"></a>
## 4. Deferred directions and operational limits

Full financial source-history promotion, versioned reparse implementation, partial economic writer, general changing-quantity/bond total return, broad FX/in-kind/scope-transition valuation and unsupported provider semantics require their own accepted contracts and evidence. Do not revive old MVP release queues, model journals or historical next-session tasks.

[#838](https://github.com/LTstripes/hermes-finance/issues/838) retains the separately recorded off-device/recovery/ACL limitations; local synced readback is not proof of encryption or external device visibility. No private source, database, secret, schema fixture or released migration was changed for this consolidation.
