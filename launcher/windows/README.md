# Hermes Finance Windows launcher — owner-first entry point

`HermesFinance.Launcher.exe` — каноническая owner-точка входа ( ADR 0014, R09-LAUNCH03 #279 ). Никаких логов, PowerShell, Git и ручного JSON для обычного запуска. Launcher показывает **только** локально настроенные runtime-профили ( не список Git-веток ). Git-мутация возможна только после явного owner-действия: `Обновить Preview` до `origin/main` или `Обновить Stable до vX.Y.Z` после доказательства опубликованного immutable release.

**Что видит владелец без логов:**

- **Stable** — зелёная карточка `STABLE · PRODUCTION` с pinned production identity: `Release v0.8.1` + короткий SHA + `Canonical production data` + `production` data boundary. Может открыть только canonical production DB.
- Если `Обновить проверку` явно обнаружила новый опубликованный release, Stable показывает current → target identity и кнопку `Обновить Stable до vX.Y.Z`. Само `Обновить проверку` остаётся read-only: оно не делает backup, fetch, switch, config write или start.
- **Preview** — фиолетовая `PREVIEW · ISOLATED` с `main / UNRELEASED` + `Isolated UAT / synthetic data`, строка `main <current> → <target> · UNRELEASED` + короткий SHA. Никогда не смешивает данные со Stable.
- **Ровно одна primary CTA** подсвечена по состоянию: `Обновить Preview` / `Подготовить` / `Исправить` / `Запустить` / `Открыть Hermes` / `Остановить` — остальные вторичны или отключены.
- **4 проверки человеческим языком** (кратко, без путей): Code identity, Data boundary, Locked dependencies, Loopback service + Alembic. Raw-диагностика — вторичный скрытый слой.

## Build/package

Install the .NET 8 SDK, then run from this directory:

```powershell
.\package.ps1
```

The script runs the automated safety harness (59 checks including #279 identity/CTA/config/setup and #298 Stable upgrade regressions) and publishes a self-contained single-file `win-x64` executable to `artifacts\win-x64\HermesFinance.Launcher.exe`. Build artifacts are ignored and must not be committed.

For an owner-facing install, run from this directory:

```powershell
.\install.ps1
```

This packages the launcher, copies it and its bundled helpers (`launcher-schema-check.py`, `launcher-production-backup.py`, `prepare-runtime-dependencies.ps1`, `config.example.json`) to `%LOCALAPPDATA%\HermesFinance\launcher`, and creates/updates `Hermes Finance.lnk` on the Desktop and in the Start menu. The backup and dependency helpers are invoked only by explicit owner actions; the schema helper is read-only. The shortcuts never target a checkout, worktree or task artifact directory. Use `-SkipStartMenuShortcut` when only the Desktop shortcut is wanted. Release and synthetic tests may pass `-PackageDirectory` to install an already-built package and `-ShortcutDirectory` to keep the shortcut outside the real Desktop.

## Owner configuration — launcher-owned, без ручного JSON в норме

`%LOCALAPPDATA%\HermesFinance\launcher\config.json` — launcher-first, без placeholder-файлов:

- если файла нет — launcher **не создаёт** placeholder из `config.example.json` (там `<absolute-...>` заглушки). Вместо этого fail closed с actionable guidance: run `install.ps1`, откройте launcher, нажмите «Обновить проверку». Авто-создание срабатывает только если bundled шаблон сам concrete (абсолютные пути, валидная shape) — shipped `config.example.json` таковым не является;
- если Stable ещё указывает на старый `v0.6.3`/`v0.7.0`/`v0.8.0` — миграция на `v0.8.1` только при доказанной безопасности (Stable checkout существует, чист, HEAD == `v0.8.1^{commit}`); иначе config **не меняется**, preflight покажет recovery-only guidance;
- если есть неизвестные поля — schema-aware strip (top-level / canonical / profile allowlists); что не чинится — fail closed без изменения файла.

Обычный workflow **не требует** ручного редактирования `config.json`. Первый запуск без конфига — не тупик: launcher показывает «Нужна настройка» и кнопку **«Настроить…»** — явный owner-facing setup (выбор Stable/Preview checkout и data-каталогов с доказательством identity теми же preflight-инвариантами: Stable чист и `HEAD == refs/tags/v0.8.1`, Preview чист, на `refs/remotes/origin/main` и независим от Stable; без fetch/сети). `config.json` записывается только после валидных concrete values. Ручное редактирование — recovery-only, когда launcher показал blocker и подсказал корректное действие.

The config may contain no secrets. Each profile names an independent checkout, data directory and database. `Stable` must exactly match `canonical_production`; Preview and Experiment must match none of it. Preview/Experiment databases that already exist require a matching `.hermes-data-identity.json` sidecar. For a fresh safe profile, the launcher writes the minimal sidecar only after the guarded startup reports health ready.

For an owner UAT copy, follow ADR 0014 §7: create/select a production backup by the existing backup mechanism, copy it only into the stopped Preview runtime, then write a `kind=preview` sidecar. This executable never copies Preview data back to Stable and never refreshes it implicitly.

## Normal owner use — launcher-first

1. Откройте **Hermes Finance** (Desktop/Start menu). Выберите карту — Stable (зелёная) или Preview (фиолетовая, `UNRELEASED`).

2. Нажмите **Обновить проверку** — launcher прогонит read-only preflight и покажет одну primary CTA. Для Stable это единственное действие, которое явно запускает read-only release discovery (`gh api` + `git ls-remote`); оно не мутирует checkout, production data, backup или config:

 - `Подготовить` — если locked зависимости missing/stale (offline проверка, сеть только по явному нажатию);
 - `Исправить` — принудительно восстанавливает обе среды (даже если сейчас ready);
 - `Запустить` — только когда всё готово (Stable Ready; Preview current + deps ready), обычный старт без скрытых download/install и без release discovery (`UV_OFFLINE=1`);
 - `Обновить Stable до vX.Y.Z` — только если найден опубликованный non-prerelease с точным immutable annotated `refs/tags/vX.Y.Z`, remote tag доказан и target SHA новее текущего. Эта кнопка — единственный Stable upgrade CTA;
 - `Обновить Preview` — Preview behind `origin/main` + deps ready (primary; `Запустить` не предлагается пока висит подготовленное обновление);
 - `Обновить и запустить` — Preview behind + deps missing: единственная primary CTA безопасной цепочки (обновление → подготовка locked-зависимостей → запуск); `Подготовить`/`Запустить` не конкурируют;
 - `Обновить Preview` / `Обновить и запустить` — только для Preview, `fetch origin/main` + `ff-only` с проверкой чистоты/identity, показывает target SHA.

3. Identity mismatch — не тупиковый блокер: launcher объясняет причину человеческим языком и включает **правильную** кнопку ( например, Preview `identity does not match` → primary `Обновить Preview`, а не dead-end ).

4. После `Запустить` launcher ждёт health probes (`Hermes Finance is ready: http://127.0.0.1:8000`), ставит sidecar где нужно, показывает `127.0.0.1:8000` только тогда. `Открыть Hermes` — только после готовности, `Остановить` — останавливает процесс и его дерево.

Preview development больше не требует терминала для `origin/main` пути. Перевод Preview на другую ветку/коммит — вне launcher, делает интегратор.

The primary view never displays raw filesystem paths or process diagnostics. `Диагностика и логи` opens a separate technical layer for troubleshooting; it is opt-in, hidden by default and does not change preflight or startup behavior.

## Preconditions and failure handling — human summaries + actionable CTA

The launcher requires Git, `gh`, `uv`, Node.js/npm at the relevant action (build time only for self-contained exe). It carries its bundled schema, backup and dependency helpers, so an older checkout need not contain them. Read-only probes use offline mode (`uv --offline --dry-run`, `npm ls --json`); read-only Stable release discovery uses only explicit `Обновить проверку` (`gh api` and `git ls-remote`). Network-capable `uv sync --locked`, `npm ci`, Preview `git fetch` and Stable tag `git fetch` occur only after explicit owner action.

Before PowerShell, it fail-closes with **человеческой сводкой** и подсвечивает **правильную primary CTA** вместо тупика:

- `Stable`/`Preview` dirty worktree → `Заблокировано: checkout изменён — сделайте чистым и Обновить проверку`;
- `identity does not match` на Preview → `Обновить Preview`; на Stable → recovery-only `Обновить проверку` (launcher обновляет Stable только по отдельному доказанному release target, не по mismatch);
- грязный/конфликтный или unexpected Stable checkout → `Обновить проверку`; upgrade и backup до очистки не запускаются;
- отсутствующий/черновой/prerelease release, lightweight tag, несоответствие tag/commit/version или недоступный GitHub → Stable upgrade остаётся заблокированным;
- `sidecar`/`unstamped data` → `Обновить проверку` после исправления sidecar;
- `schema`/`alembic` → `Обновить проверку` (схема несовместима);
- `port 8000` занят внешним процессом → launcher **не** предлагает ложный `Остановить` (чужие процессы не останавливает); primary — `Обновить проверку` после ручной остановки;
- `dependency`/`npm`/`uv` — `Подготовить`/`Исправить`.
- `Остановить` — только для launcher-owned running процесса (Running).

Raw-детали — только в `Диагностика и логи`.

After a successful preflight it invokes only the selected checkout's existing guarded `scripts/start-local.ps1` with `HERMES_FINANCE_DATABASE_PATH` set to the validated profile DB (takes precedence over `.env`). The script remains responsible for frontend build, migrations, loopback bind and its three health probes. The window streams logs, keeps the last launch status visible, and opens `http://127.0.0.1:8000` only after readiness.

## Explicit Stable upgrade lifecycle

Stable release discovery and upgrade are separate owner actions:

1. After Hermes is stopped, the owner presses `Обновить проверку`. The launcher validates the current Stable checkout, then reads the published GitHub releases and `origin` tag refs without fetching, switching, creating a backup or writing config. It accepts only a strict published, non-draft, non-prerelease `vX.Y.Z` whose remote tag is annotated and peels to one exact commit. Stable is never resolved to `main`.
2. If a newer target is proven, the launcher shows `Обновить Stable до vX.Y.Z`. Pressing it re-reads publication metadata and tag proof immediately before mutation, then creates one verified SQLite online backup in the existing `data/backups/` contract before any Git/config mutation.
3. It fetches only the proven tag ref, verifies the annotated tag object, peeled commit and target `hermes_finance.__version__`, detaches only the configured Stable checkout at that tag, and re-checks cleanliness and identity. It writes the Stable `expected_ref` only after those proofs succeed. A dirty, unexpected, changed or unproven checkout fails closed.
4. If the new release needs dependencies, the launcher invokes the existing locked preparation mechanism (`uv sync --locked` and `npm ci`) as part of this explicit upgrade action. It never starts Hermes automatically; the owner gets a fresh `Запустить` CTA after preflight. Runtime/backend `/api/health` version must match the launcher release identity before `Running` is shown.

The canonical production `data_dir` and database path stay unchanged, and the production DB/identity sidecar are checked for concurrent mutation around the upgrade. Preview checkout, Preview data and Preview identity are never read or copied by this lifecycle. `Обновить проверку` is always a check, never a disguised upgrade.

## Synthetic UI smoke

The safety harness includes a synthetic-only visual mode. It loads no checkout, database, `.env`, sidecar or owner data:

```powershell
dotnet run --project .\HermesFinance.Launcher.SafetyTests\HermesFinance.Launcher.SafetyTests.csproj --configuration Release -- --synthetic-ui-smoke
```

Use it to inspect the Stable-ready ( `Release v0.8.1 · production` ), Preview-UNRELEASED and opt-in diagnostics states on Windows, then close the window normally.
