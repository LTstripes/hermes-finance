from pathlib import Path

ROOT = Path('.')
release_path = ROOT / 'docs' / 'RELEASE_0_2.md'
smoke_path = ROOT / 'docs' / 'RELEASE_0_2_SMOKE_2026-08-11.md'
followups_path = ROOT / 'docs' / 'RELEASE_0_2_FOLLOWUPS_2026-08-11.md'
out_path = ROOT / 'docs' / 'releases' / '0.2.0.md'
start_prompt = ROOT / 'docs' / 'HERMES_START_PROMPT.md'


def clean_trailing_whitespace(text: str) -> str:
    cleaned = '\n'.join(line.rstrip() for line in text.splitlines())
    return cleaned + ('\n' if text.endswith('\n') else '')


release = release_path.read_text(encoding='utf-8')
smoke = smoke_path.read_text(encoding='utf-8')
followups = followups_path.read_text(encoding='utf-8')

release = release.replace(
    '# Release 0.2',
    '# Hermes Finance 0.2.0 — release archive',
    1,
)

release_meta = '''

> **Released:** 2026-08-12
> **Tag:** `v0.2.0`
> **Release commit:** `346d865e73cb44753a5b1adece7432fde4a275dc`
> **Final exact-main CI:** `31533137143` — Backend / Frontend / Privacy guard / Windows production smoke green.
> **Final local production probe:** ACCEPT on the same commit; health `0.2.0`, `/api/months` PASS, bind `127.0.0.1:8000`, port cleanup PASS, working tree clean.
'''

first_newline = release.find('\n')
release = release[:first_newline] + release_meta + release[first_newline:]

release = release.replace(
    '**Checkpoint status:** FINAL_GATE. R02-27 DONE и candidate CI green; tag удерживается до merge, exact-main CI и final local production probe на новом `main`.',
    '**Checkpoint status:** RELEASED. Все обязательные release-gate проверки пройдены; `v0.2.0` создан на exact commit `346d865e73cb44753a5b1adece7432fde4a275dc`.',
)
release = release.replace(
    '- [ ] Owner/Hermes local production probe на финальном `main`: start/health/months/`127.0.0.1:8000`/port cleanup + clean working tree.',
    '- [x] Owner/Hermes local production probe на финальном `main`: start/health/months/`127.0.0.1:8000`/port cleanup + clean working tree — ACCEPT.',
)
release = release.replace(
    '- [ ] Только после этого создаётся `v0.2.0`.',
    '- [x] `v0.2.0` создан на exact release commit после закрытия gate.',
)


def strip_first_heading(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith('# '):
        lines = lines[1:]
    return '\n'.join(lines).strip()


archive = (
    release.rstrip()
    + '\n\n---\n\n# 4. Owner smoke archive\n\n'
    + strip_first_heading(smoke)
    + '\n\n---\n\n# 5. Owner follow-ups archive\n\n'
    + strip_first_heading(followups)
    + '\n'
)
archive = clean_trailing_whitespace(archive)

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(archive, encoding='utf-8')

# Update project guidance so completed 0.2 is no longer presented as the active backlog.
prompt = start_prompt.read_text(encoding='utf-8')
prompt = prompt.replace(
    '2. активный release backlog, если он существует (для версии 0.2 — `docs/RELEASE_0_2.md`)',
    '2. активный release backlog, если он существует. Для новых версий используй один файл `docs/releases/<version>.md`; завершённые release-файлы в этой папке считаются историческим архивом, а не активным scope',
)
prompt = prompt.replace(
    '- Выполняй только одну task-card из активного release backlog за итерацию. Для версии 0.2 допустимы ID вида `R02-*` из `docs/RELEASE_0_2.md`.',
    '- Выполняй только одну task-card из активного release backlog за итерацию. Префикс ID должен соответствовать активной версии (`R03-*`, `R04-*` и т.д.); task-cards завершённых релизов не считай активным scope.',
)
prompt = prompt.replace(
    'Перед началом владелец должен явно назвать ID текущей задачи. Для активного release backlog это может быть, например, `R02-01`.',
    'Перед началом владелец должен явно назвать ID текущей задачи. Для активного release backlog это может быть, например, `R03-01`.',
)
start_prompt.write_text(clean_trailing_whitespace(prompt), encoding='utf-8')

# Replace stale links/references in remaining Markdown files.
replacements = {
    'docs/RELEASE_0_2.md': 'docs/releases/0.2.0.md',
    'docs/RELEASE_0_2_SMOKE_2026-08-11.md': 'docs/releases/0.2.0.md',
    'docs/RELEASE_0_2_FOLLOWUPS_2026-08-11.md': 'docs/releases/0.2.0.md',
}
for path in ROOT.rglob('*.md'):
    if path in {release_path, smoke_path, followups_path, out_path}:
        continue
    text = path.read_text(encoding='utf-8')
    updated = text
    for old, new in replacements.items():
        updated = updated.replace(old, new)
    if updated != text:
        path.write_text(clean_trailing_whitespace(updated), encoding='utf-8')

release_path.unlink()
smoke_path.unlink()
followups_path.unlink()
