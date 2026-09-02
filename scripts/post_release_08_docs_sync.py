from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# README
replace_once(
    "README.md",
    "Опубликованная стабильная идентичность **0.7.0** — неизменяемый Git-тег `v0.7.0`, указывающий на exact released main SHA `06dc3ba3f4a8a8d150eca1879949a6984e1ac6b7`; exact-main CI #425 (run `33325251688`) завершился успешно, публикация состоялась 2026-08-30. Owner Stable promotion для 0.7.0 подтверждён как PASS в тот же день. Этот post-release docs sync фиксирует уже опубликованное состояние и не меняет product code или финансовую семантику.",
    "Опубликованная стабильная идентичность **0.8.0** — неизменяемый Git-тег `v0.8.0`, peel'ящийся в exact released main SHA `ec185deab8d3fe949e7d579e5041d23216a6d73f`. Exact-head PR CI run `33665746651`, post-merge exact-main CI run `33668924186` и guarded Release run `33669922698` завершились успешно; публикация состоялась 2026-09-02. Предрелизный Preview UAT сознательно не заявляется как пройденный: owner acceptance выполняется на released Stable 0.8.0, а найденные дефекты оформляются отдельными follow-up/patch задачами.",
)
replace_once("README.md", "Для 0.7.0 ожидается:", "Для 0.8.0 ожидается:")
replace_once("README.md", '"version": "0.7.0"', '"version": "0.8.0"')
replace_once("README.md", "## Что доступно в 0.7.0", "## Что доступно в 0.8.0")
replace_once(
    "README.md",
    "Released `0.7.0` фиксирует принятый R07 tree поверх уже интегрированных R07/R08 workstreams. Все provider- и owner-triggered действия остаются явными, а вычисления и финансовые границы — backend-authoritative. Доступны:",
    "Released `0.8.0` фиксирует owner-workflow release поверх принятого R07/R08 tree: Guided Monthly Close Wizard объединяет monthly close, Alfa/reconciliation, T-Invest/provider steps, final review и explicit Close/Reopen в один локальный workflow; добавлены safe instrument cleanup и explicit portfolio review handoff в JSON/Markdown. Все provider- и owner-triggered действия остаются явными, а вычисления и финансовые границы — backend-authoritative. Доступны:",
)
replace_once(
    "README.md",
    "- **Windows Stable/Preview launcher** — guarded runtime profiles и owner Start/Stop controls; launcher не перечисляет и не меняет Git branches/state и не смешивает Stable с Preview.",
    "- **Windows Stable/Preview launcher** — guarded runtime profiles, owner Start/Stop controls, package/install verification и shortcut/start-stop smoke; текущий 0.8 launcher всё ещё требует заранее подготовленный checkout и не обновляет Preview из `origin/main` сам — это tracked follow-up #277.",
)
replace_once(
    "README.md",
    "- **UI и verification** — visual-audit polish, semantic test-taxonomy work и backend CI с timeout 15 минут входят в release evidence, не расширяя финансовую семантику.",
    "- **UI и verification** — visual-audit polish, semantic test-taxonomy work и backend CI входят в release evidence; Backend timeout временно поднят с 15 до 30 минут как release unblock, а durable split/slow-test telemetry tracked в #282.",
)
replace_once("README.md", "В **0.7.0** календарь объединяет", "В **0.8.0** календарь объединяет")

# CHANGELOG
changelog = Path("CHANGELOG.md")
text = changelog.read_text(encoding="utf-8")
anchor = "Все заметные изменения Hermes Finance фиксируются в этом файле.\n\n"
if anchor not in text:
    raise SystemExit("CHANGELOG anchor not found")
entry = """## [0.8.0] — 2026-09-02

Published owner-workflow release. This entry records the already published `v0.8.0` identity; it does not introduce new product code, financial semantics or provider write behavior.

### Added

- Guided Monthly Close Wizard (#236 A–H): one month-scoped workflow for exact-month review, Alfa baseline/reconciliation, explicit T-Invest/provider actions, payout PDF orchestration, final review and explicit Close/Reopen;
- owner-facing month/readiness/Dashboard/Risk wording and layout polish;
- safe duplicate/inactive instrument cleanup with read-only inspection and fail-closed deletion guards;
- explicit concise/full portfolio review handoff packages in JSON and Markdown from the same backend facts, with no automatic upload/LLM call/write-back;
- Windows launcher package/install artifact verification, shortcut validation and synthetic start/stop/Git-mutation guards.

### Changed

- product/package identity synchronized to `0.8.0` across backend/frontend metadata and lock files;
- Backend CI timeout temporarily raised from 15 to 30 minutes after one hosted runner reached ~83% of the monolithic suite and hit the old limit; durable parallel-lane/slow-test work is tracked in #282;
- owner workflow keeps provider Price/UchPrice/NKD/P&L comparison-only and preserves unknown/unavailable states instead of converting them to financial zero.

### Release evidence

- release candidate: `920cca87066190a7776e8583e3d639ecfd89c5be`;
- exact-head PR CI run `33665746651`: SUCCESS;
- PR #281 merge / released main commit: `ec185deab8d3fe949e7d579e5041d23216a6d73f`;
- post-merge exact-main CI run `33668924186`: SUCCESS;
- guarded Release run `33669922698`: SUCCESS;
- published annotated tag `v0.8.0` object `2f27d9e34271843d97eed1138bd8b388630bd7a8`, peeled to `ec185deab8d3fe949e7d579e5041d23216a6d73f`.

### Owner acceptance note

Pre-release Preview UAT was intentionally not represented as passed because the current launcher cannot update an unreleased Preview checkout itself. Hands-on acceptance is performed on released Stable 0.8.0. Concrete defects become patch/follow-up work. Launcher normalization begins with #277.

### Follow-up / tech debt

- #277–#279 launcher normalization and owner update flows;
- #280 controlled cleanup of old `D:\\Finance` workspaces/artifacts;
- #282 split backend pytest into parallel lanes and add slow-test telemetry.

"""
changelog.write_text(text.replace(anchor, anchor + entry, 1), encoding="utf-8")

# PROJECT_WIKI
wiki = Path("docs/PROJECT_WIKI.md")
text = wiki.read_text(encoding="utf-8")
section = "## 3. Текущее стабильное состояние\n\n"
if section not in text:
    raise SystemExit("PROJECT_WIKI section 3 anchor not found")
current = """Опубликованная стабильная product identity — **0.8.0**. Annotated tag `v0.8.0` (tag object `2f27d9e34271843d97eed1138bd8b388630bd7a8`) peel'ится в exact released main SHA `ec185deab8d3fe949e7d579e5041d23216a6d73f`. Exact-head PR CI run `33665746651`, post-merge exact-main CI run `33668924186` и guarded Release run `33669922698` завершились `success`; GitHub Release опубликован 2026-09-02. Канонический release record — `docs/releases/0.8.0.md`.

0.8.0 — owner-workflow release: Guided Monthly Close Wizard объединяет month-scoped review/Alfa/reconciliation/provider steps/final review/Close-Reopen; добавлены safe instrument cleanup и explicit portfolio review handoff. Предрелизный Preview UAT не заявляется как пройденный: owner acceptance выполняется на released Stable 0.8.0. Launcher update UX вынесен в #277–#279; filesystem cleanup — #280; backend CI performance — #282.

Предыдущая опубликованная стабильная линия **0.7.0** сохранена как историческая identity: `v0.7.0` @ `06dc3ba3f4a8a8d150eca1879949a6984e1ac6b7`, опубликована 2026-08-30 с owner Stable promotion `PASS`.

"""
text = text.replace(section, section + current, 1)
old_para = "Опубликованная стабильная product identity — **0.7.0**. Annotated tag `v0.7.0` peel'ится в exact released main SHA `06dc3ba3f4a8a8d150eca1879949a6984e1ac6b7`; canonical exact-main CI #425 (run `33325251688`) для этого SHA завершился `success`, GitHub Release опубликован 2026-08-30. Канонический Alembic head — `0036_broker_baseline_provenance`.\n\n"
if old_para not in text:
    raise SystemExit("PROJECT_WIKI old 0.7 current-identity paragraph not found")
text = text.replace(old_para, "Канонический Alembic head опубликованного 0.8 tree остаётся `0036_broker_baseline_provenance`; релиз не добавлял новую миграцию.\n\n", 1)
text = text.replace(
    "Подробная release фиксация находится в разделе 20 и `docs/releases/0.7.0.md`; 0.6.3 остаётся исторической предыдущей стабильной линией.",
    "Подробная release фиксация 0.8 находится в `docs/releases/0.8.0.md`; 0.7.0 и 0.6.3 остаются историческими предыдущими стабильными линиями.",
    1,
)
text = text.replace(
    "- UI/visual-audit polish, semantic test-taxonomy/verification work и backend CI timeout 15 минут;",
    "- UI/visual-audit polish, semantic test-taxonomy/verification work; Backend CI timeout временно 30 минут после release unblock, durable split/telemetry tracked в #282;",
    1,
)
wiki.write_text(text, encoding="utf-8")

# EXECUTION_HISTORY
hist = Path("docs/EXECUTION_HISTORY.md")
text = hist.read_text(encoding="utf-8")
anchor = "---\n\n# 0.4.x development"
if anchor not in text:
    raise SystemExit("EXECUTION_HISTORY anchor not found")
record = """---

# 0.8.0 release

### 0.8.0 — owner-workflow release publication

- **Published:** 2026-09-02
- **Reviewer/integrator:** ChatGPT + owner-authorized guarded release flow
- **Frozen pre-release feature main:** `3e35bf3ca36bbe8c57006c9b1a161b381cacd95c`
- **Release candidate:** `920cca87066190a7776e8583e3d639ecfd89c5be`
- **PR:** #281
- **Released main / PR merge:** `ec185deab8d3fe949e7d579e5041d23216a6d73f`
- **Tag:** annotated `v0.8.0`, tag object `2f27d9e34271843d97eed1138bd8b388630bd7a8`, peeled commit `ec185deab8d3fe949e7d579e5041d23216a6d73f`
- **Verification:** exact-head PR CI run `33665746651` SUCCESS; post-merge exact-main CI run `33668924186` SUCCESS; guarded Release run `33669922698` SUCCESS.
- **Release blocker/iteration:** an earlier Backend job was cancelled only because the monolithic pytest suite reached the previous 15-minute Actions timeout at ~83%; no product test failure was reported. The release candidate changed Backend timeout `15 -> 30` minutes only. Durable CI parallelization/telemetry is tracked in #282.
- **Owner acceptance:** pre-release Preview UAT was intentionally not claimed as passed because the launcher could not update unreleased Preview without manual Git/config work. Hands-on acceptance is performed on released Stable 0.8.0; concrete defects are follow-up/patch work.
- **Scope note:** 0.8.0 integrates Guided Monthly Close Wizard A–H, owner workflow/Alfa/reconciliation UX, safe instrument cleanup, explicit portfolio review package handoff, and guarded Windows launcher/package verification while preserving local-only/no-cloud/no-auth/provider-explicit-action boundaries.
- **Follow-ups:** launcher normalization #277–#279; workspace cleanup #280; backend CI performance #282.

# 0.4.x development"""
hist.write_text(text.replace(anchor, record, 1), encoding="utf-8")
