# Hermes adapter

<a id="workspace-isolation"></a><a id="handoff"></a>
[AGENTS.md](../../AGENTS.md) is the task entrypoint; Hermes is a first-class Worker client.
Use the Owner-configured Hermes workspace root under the shared [machine-layout contract](../OWNER_MACHINE_LAYOUT.md); concrete paths remain machine-local.

## Manual Worker route

The receiving Hermes session owns the final candidate. Optional bots/subagents are bounded helpers unless explicitly assigned another role.
Keep helpers inside the accepted scope and assemble one accountable candidate; helpers do not obtain project acceptance or merge authority.
Do not require a delegate/fallback ledger for an ordinary handoff. Report only a material deviation that affects ownership, evidence or trust.

## No permanent provider/model lock

Provider/model/effort come from the selected launch/runtime. Record only evidenced identity.
Do not change shared Hermes defaults to satisfy one task without an explicit request.

## Relationship to Codex orchestration

Hermes does not need Codex-local skills. An ordinary task does not activate a queue; explicitly coordinated work follows the common orchestration procedure.
