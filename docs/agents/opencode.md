# OpenCode adapter

[AGENTS.md](../../AGENTS.md) is the task entrypoint. OpenCode is a normal Worker/reviewer client and does not add another project policy layer.

Use the Owner-configured OpenCode workspace root under the shared [machine-layout contract](../OWNER_MACHINE_LAYOUT.md). Every writing or local-verification task owns one `<issue>-<slug>` directory below that root. Concrete machine paths remain local.

Do not inspect or edit another client's physical workspace by default. Review sibling work through GitHub PRs/remote refs, or use an explicitly assigned independent review clone/path.

Model/provider/effort come from the selected OpenCode runtime. Report the actual evidenced identity using the two-field Model evidence block from AGENTS.md. Ordinary tasks do not activate an unattended queue or authorize merge/release/runtime changes.
