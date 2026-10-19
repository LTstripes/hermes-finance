# Hermes Finance 0.8.0

Hermes Finance 0.8.0 is the owner-workflow release: the monthly close, broker/import steps, reconciliation, final review and close lifecycle are now joined into one guided local workflow, while preserving the existing backend authorities and explicit-action safety boundaries.

## Highlights

- **Guided Monthly Close Wizard (#236 A–H):** month-scoped workflow with one obvious next action, exact-month return context, Alfa baseline/reconciliation, T-Invest quotes and future payouts, Alfa payout PDF orchestration, compact final review, explicit Close/Reopen, and backend-owned next-month outlook.
- **Owner-first month UX:** money input grouping, table/layout/overlay fixes, clearer notes/actions, human-readable Close/readiness presentation, and Dashboard/Risk readability improvements from the first real Stable month close.
- **Safer Alfa workflow:** clearer Hermes-vs-Alfa wording, explicit payout-statement instrument mapping, preserved narrow PDF statement contract, and comparison-only provider Price/UchPrice/NKD/P&L boundaries.
- **Instrument cleanup:** read-only cleanup inspection plus fail-closed deletion guards for duplicate/inactive instruments; referenced or mapped instruments remain protected.
- **Portfolio review handoff:** explicit owner-triggered concise/full JSON and Markdown packages generated from the same backend facts for ChatGPT/LLM analysis. No automatic upload, cloud call, provider call or write-back is introduced.
- **Windows launcher:** branded Stable/Preview launcher plus package/install artifact verification, shortcut validation, synthetic install/start/stop smoke and Git-mutation guards.

## Safety and semantics preserved

- Local single-user Windows-first runtime remains bound to `127.0.0.1:8000`.
- No cloud account, auth layer, telemetry, background provider refresh or automatic upload is added.
- Provider/network/file-processing actions remain explicit owner actions.
- Closed months remain immutable until explicit Reopen.
- Alfa provider valuation fields remain comparison-only unless an existing accepted contract explicitly says otherwise.
- Unknown/unavailable evidence is not silently converted to financial zero.
- Redemption principal remains separate from passive income.

## Verification

- #236 implementation slices A–H were integrated and automated verification completed successfully.
- Exact-main CI #480 / run `33627908629` succeeded on the completed #236 tree.
- Final pre-release exact-main CI #481 / run `33655913775` succeeded on `3e35bf3ca36bbe8c57006c9b1a161b381cacd95c`.
- CI coverage includes backend/frontend suites, privacy guard, Windows production smoke, Windows launcher safety, release safety, timezone regression and synthetic visual audit.

## Owner acceptance note

The owner explicitly chose to publish 0.8.0 before the previously planned Preview UAT because the Preview launcher still requires release identity and does not yet provide a launcher-owned `update Preview from main` workflow. Final hands-on acceptance will therefore be performed on released Stable 0.8.0. Any concrete defects found there will be tracked as patch/follow-up work rather than being represented here as pre-release UAT passes.

Launcher follow-up is tracked separately so future Preview testing can be performed from the launcher without manual Git, PowerShell or config editing.
