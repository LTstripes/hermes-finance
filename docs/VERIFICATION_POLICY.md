# Verification policy — пропорциональные проверки

> **Статус:** обязательный проектный протокол для Hermes/agent implementation.  
> Цель — сохранять надёжность, но не тратить время на повторный запуск несвязанных или полных suite после каждого маленького изменения.

## 1. Общий принцип

Проверки должны быть **пропорциональны риску и изменённым слоям**.

Во время implementation loop используй самые узкие проверки, которые быстро подтверждают текущую гипотезу. Полные suite запускаются на финальном локальном gate, когда реализация уже стабилизировалась, а не после каждой правки.

Явные требования task-card, ADR, release gate или владельца имеют приоритет над этой политикой и могут требовать более строгих проверок.

## 2. Implementation loop

1. Для bugfix/regression-задачи сначала добавь или найди targeted regression test и, когда это практически осмысленно, подтверди RED на старом поведении.
2. Во время разработки повторно запускай только affected/targeted tests и относящиеся к изменённым файлам lint/format checks.
3. Не запускай full backend/frontend suite после каждой небольшой правки.
4. Если targeted test падает вне заявленного scope, остановись и разберись с причиной; не расширяй scope автоматически.
5. После стабилизации implementation переходи к финальному local verification gate ниже.

RED-first не обязателен для docs-only, механического formatting/refactor без изменения поведения и задач, где воспроизводимый failing test не даёт дополнительной уверенности.

## 3. Финальный local verification gate по типу задачи

### Backend/domain-only

Обычно перед commit/push достаточно:

- targeted tests для изменённого поведения;
- backend lint + format-check;
- **full backend suite один раз** после стабилизации implementation.

Не запускай локально full frontend suite/build только потому, что он существует.

Frontend проверки добавляются, если изменён публичный API/DTO, которым реально пользуется frontend, shared generated/static contract, scripts/build integration или task-card явно требует frontend verification.

### Frontend-only

Обычно перед commit/push достаточно:

- targeted component/integration tests;
- frontend lint + format-check;
- **full frontend test suite один раз** после стабилизации implementation;
- production frontend build один раз.

Не запускай локально full backend suite, если backend/API contract не изменялся и task-card этого не требует.

### API/shared-contract change

Если меняется backend API/DTO, который потребляет frontend:

- targeted backend tests;
- full backend suite один раз;
- targeted frontend contract/component tests для затронутого API;
- frontend lint/format/build;
- full frontend suite — когда изменение затрагивает shared API types/client behavior или task-card это требует.

### Migration / startup / backup / restore / filesystem / concurrency / security

Это high-verification задачи. Обычно требуются:

- targeted regression tests;
- full backend suite один раз;
- lint/format;
- task-specific integration/probe;
- Windows-specific probe, если поведение зависит от Windows process/file-handle/path semantics;
- exact-HEAD CI после push, если commit/push входит в iteration contract.

Не сокращай task-specific probe ради скорости.

### Docs/process-only

Обычно достаточно:

- review фактического diff;
- `git diff --check` или эквивалентной проверки whitespace/format, если доступно;
- privacy/tracked-files check, если документ касается путей/seed/private data или это дешёвая каноническая проверка.

Локальные full backend/frontend suite для docs-only не нужны. Если repository CI автоматически запускает их на PR — дождись CI, но не дублируй их локально без причины.

### Cross-cutting backend + frontend

Если задача действительно изменяет оба слоя, выполни соответствующие targeted checks и по одному финальному full suite каждого затронутого слоя плюс production build frontend.

## 4. Когда полный suite надо повторить

После уже прошедшего full suite повтори его, если затем было сделано **семантическое изменение кода** в этом же слое.

Если после full suite были только formatting, комментарии, docs или иная доказуемо non-semantic правка, локально повторять несвязанный full suite не обязательно; exact-HEAD CI остаётся финальной проверкой, если он предусмотрен iteration contract.

## 5. CI и exact HEAD

GitHub Actions может канонически запускать больше jobs, чем нужно локально. Это нормально.

- Не дублируй локально unrelated suite только ради совпадения со всеми CI jobs.
- Если task-card/iteration contract требует commit + push + exact-HEAD CI, задача не считается завершённой до зелёного CI точного финального SHA.
- После CI не вноси semantic changes без повторной релевантной локальной проверки и нового exact-HEAD CI.

## 6. Что писать в отчёте

В секции `Проверки` перечисли фактически выполненные команды и результаты. Для пропущенных несвязанных suite не нужно оправдание по умолчанию; если task-card ожидала необычную проверку и она не выполнялась, явно объясни почему.

Не заявляй `full suite`, если запускалась только targeted subset.

## 7. Примеры

- Исправление чисто backend service: targeted pytest в цикле → backend lint/format → full backend pytest один раз → push/CI. Frontend локально не гоняется, если API contract не менялся.
- React-страница поверх существующего API: targeted Vitest → frontend lint/format → full Vitest один раз → Vite build → push/CI. Backend full pytest локально не нужен.
- Windows restore serialization: RED regression → targeted restore tests → implementation → targeted green → full backend → Windows file-handle/concurrency probe → push → exact-HEAD CI.
- Docs-only ADR: diff/format/privacy checks → PR CI; без локального backend/frontend full suite.
