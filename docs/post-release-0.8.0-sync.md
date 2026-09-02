# Hermes Finance 0.8.0 — post-release documentation sync

This temporary coordination note records the narrow post-release documentation sync after the already published `v0.8.0` release.

Canonical release evidence:

- published release: `v0.8.0`;
- annotated tag object: `2f27d9e34271843d97eed1138bd8b388630bd7a8`;
- peeled released main commit: `ec185deab8d3fe949e7d579e5041d23216a6d73f`;
- release candidate before merge: `920cca87066190a7776e8583e3d639ecfd89c5be`;
- exact-head PR CI run `33665746651`: SUCCESS;
- post-merge exact-main CI run `33668924186`: SUCCESS;
- guarded Release run `33669922698`: SUCCESS.

The earlier Backend cancellation was infrastructure-only: the monolithic GitHub Actions Backend job hit its previous 15-minute timeout after reaching about 83% of the suite; no product failure was reported. The release-only unblock changed Backend timeout from 15 to 30 minutes. Durable CI performance work is tracked in #282.

This sync must update only owner-facing/project-history documentation (README, CHANGELOG, PROJECT_WIKI, EXECUTION_HISTORY and any canonical release-history pointer required by repository convention). It must not change product code, financial/provider semantics, migrations, release tag, or released artifact identity.

Owner acceptance note: pre-release Preview UAT was intentionally skipped because the current launcher cannot update an unreleased Preview checkout itself. Hands-on acceptance is to happen on released Stable 0.8.0; concrete defects become follow-up/patch work. Launcher normalization starts with #277.
