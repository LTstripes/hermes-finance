# Verification policy — пропорциональные проверки

Обязательный протокол. Проверяем изменённое поведение и реальные риски, а не повторяем одни и те же действия при каждой передаче задачи.

## 1. Общий принцип

Для обычной задачи нет обязательного локального full-suite перед каждым handoff.
Targeted evidence проверяет изменение; полный релевантный охват может обеспечить успешный CI точного кандидата.
Не дублируй этот охват локально только ради отчёта Worker, Reviewer или Integrator.
Явные task/ADR/release/Owner gates сохраняются. Противоречащее им сокращение сначала согласуется в авторитетной issue/note, а не скрывается в отчёте.

## 1.1. Semantic lanes и ownership

Добавляй регрессию существующему semantic owner; выбирай marker или конкретный test path.
Карта и команды находятся в [TEST_SUITE_GUIDE.md](TEST_SUITE_GUIDE.md); читай нужный участок, а не весь каталог.
Новый `test_rXX_*` файл нужен для отдельного release/version/compatibility или task-acceptance контракта, не просто для номера issue.
Markers не исключают тесты из полного suite; существующее покрытие и CI lanes эта политика не меняет.

## 1.2. UI-платформа и визуальная приёмка

**Owner decision 2026-10-09: desktop/laptop only.** Новый UI и Owner UAT проверяются в браузере на Windows-ноутбуке: стандартные рабочие ширины порядка 1280–1440 px, читаемость при обычном масштабе и поддерживаемом desktop zoom, отсутствие обрезания важных действий, клавиатура/focus/Back и надёжность текущих данных. Точная ширина теста выбирается по изменению/существующему acceptance contract, а не ритуально для каждого PR.

Мобильные раскладки, phone-only UX, 390 px, эмуляторы телефона, touch/mobile UAT **больше не являются продуктовым критерием или обязательным новым gate**. Не назначать Worker/Owner дополнительный мобильный прогон и не делать телефонный дизайн. Активное Playwright-покрытие использует desktop-размеры: дубли 390 px удалены в #747, уникальные финансовые, real-backend, lifecycle и keyboard-сценарии сохранены на desktop. Не возвращать телефонные варианты при интеграции старых веток. Mobile-only CSS можно убирать только отдельной узкой проверенной правкой, без ухудшения desktop-доступности или изменения финансовых контрактов.

## 2. Implementation loop

1. Для bugfix найди/добавь regression test; подтверди RED на старом поведении, когда это даёт полезное воспроизводимое доказательство.
2. Во время правок запускай affected tests и lint/format для затронутого кода. Сначала стабилизируй реализацию и форматирование.
3. При сбое сохрани ошибки, установи причину, затем проверь failed nodes и affected contracts. Не используй полный suite как следующую диагностическую команду по привычке.
4. При новом контрактном/integration риске останови расширение задачи и обратись к Integrator; не исправляй чужое поведение молча.

RED-first не обязателен для docs-only, форматирования и других изменений, где failing test не добавляет уверенности.
<a id="stabilize-before-a-full-gate"></a>
Для shared DB/session, serialization, restore и иных cross-cutting primitives сначала проверь direct consumers, failure/lifecycle boundaries и production entrypoints.
Один heavyweight local verification process одновременно, включая параллельные проекты. Не меняй source/config/dependencies во время его работы.
После выявленного инфраструктурного сбоя исправь temp/cache/toolchain условия и проверь малым запуском, прежде чем снова запускать дорогой suite.

<a id="3-финальный-local-verification-gate-по-типу-задачи"></a>
<a id="backenddomain-only"></a><a id="frontend-only"></a><a id="apishared-contract-change"></a>
<a id="migration--startup--backup--restore--filesystem--concurrency--security"></a>
<a id="docsprocess-only"></a><a id="cross-cutting-backend--frontend"></a>
## 3. Достаточный охват по типу задачи

| Изменение | Достаточное локальное evidence и дополнительный охват |
| --- | --- |
| Docs/process-only | Diff, ссылки/anchors, whitespace; privacy/tracked-files check при затрагивании путей/данных. Без backend/frontend full suite. |
| Backend под принятым контрактом | Targeted regressions + backend lint/format. Полный backend охват — CI либо один локальный full, если CI его не обеспечивает. |
| Frontend под принятым API | Targeted component/interaction tests + frontend lint/format; production build локально или в exact-candidate CI. Полный frontend охват — CI либо один локальный full при отсутствии такого CI. |
| API/shared contract или оба слоя | Targeted проверки обеих сторон и реальных consumers; lint/build затронутых слоёв. Полный релевантный охват — соответствующие CI lanes или недостающий локальный gate. |
| Financial semantics, migration, startup, backup/restore, filesystem/concurrency, security/runtime | Targeted boundary/failure regressions, полный релевантный охват и все task-specific probes. Нужны соответствующая среда, независимое ревью и применимый Owner UAT. Linux unit CI не заменяет Windows process/file-handle/path probe. |

Полный локальный запуск нужен, когда CI недоступен/не покрывает релевантный слой, есть воспроизводимый local-only риск, либо его прямо требует task/ADR gate.
Для high-risk задачи CI засчитывается только за реально выполненные проверки в подходящей среде; отсутствующие platform/integration/package probes выполняются отдельно.
Package/install smoke — финальная проверка при изменении упаковки/установки, а не причина повторять все suite перед каждым smoke.
Не запускай frontend full для чистого backend изменения и наоборот без изменённого consumer/shared contract или отдельного требования.
Push и PR можно создать для получения CI evidence; пока обязательные проверки идут, статус — pending, не done/accepted.

## 4. Когда полный suite надо повторить

Повторный полный запуск должен закрывать конкретную недостающую гарантию:
- семантическое изменение затронуло слой после предыдущего полного evidence;
- предыдущий нужный gate был прерван, невалиден или завершился ошибкой;
- новый установленный риск/обязательный gate не покрыт имеющимися результатами.

Сначала стабилизируй исправление на focused tests; затем получи полный нужный охват обновлённого кандидата, в том числе через CI.
Это не требование одновременно повторить и локальный full, и CI, и всё то же у Reviewer.
Смена роли/сессии, передача кандидата, потеря polling-сессии, новый SHA после docs/format-only правки и «для уверенности» сами по себе не основания для локального full.
После доказуемо non-semantic diff допускается переиспользовать применимое локальное evidence с указанием исходного SHA и проверенного отличия.
Нельзя приписывать старый PASS изменённому поведению, смешивать несовместимые запуски или выдавать failed-node rerun за пройденный полный gate.
Числового лимита, который отменял бы необходимую проверку, нет. Перед дорогим повтором достаточно коротко назвать изменение/ошибку и незакрытый риск; отдельный отчёт не нужен.

## 5. CI и exact HEAD

Успешный exact-candidate CI может быть полным verification gate без его локального дубля, только если проверены нужные jobs, охват и среда.
Skipped, pending, failed, чужой SHA или отфильтрованный нужный lane не являются этим доказательством.
Зелёный check `Documentation fast path` у pull request означает только доказанную классификацию обычной неисполняемой документации и успешные сохранённые проверки privacy/diff. Он не доказывает выполнение backend, frontend, browser или Windows product suites. Push в canonical `main` и release gates этот режим не использует: они остаются полными.
Проверки на новом executable/config/dependency состоянии должны соответствовать этому состоянию; отчёт явно связывает каждый результат с кандидатом/run.
Для интеграции обязательны зелёный PR CI принятого кандидата и зелёный canonical main push CI точного merge SHA. Ни одно не заменяет другое.
Эта задача не меняет workflow coverage, filters, assertions или release guards; не обходи существующие required jobs.
Reviewer/Integrator используют подтверждённое evidence кандидата. Независимость означает отдельную оценку diff/контракта, а не обязательный повтор всех тестов.
Reviewer запускает focused reproduction/probe, когда есть спорный вывод, пробел покрытия или другое конкретное основание; для локального запуска нужна изоляция.

## 6. Что писать в отчёте

Назови выполненные команды/CI jobs, результат и исходный SHA/run; отдельно обозначь material gaps и ожидаемые проверки.
Не называй targeted subset полным suite и не утверждай, что локально запускалось то, что выполнялось только в CI.
Не добавляй перечень оправданий за каждый несвязанный suite. Неисполненное явное требование задачи, напротив, нельзя умолчать.

## 6.1. Owner-данные, review и продолжение UAT

[Owner data workflow](OWNER_DATA_WORKFLOW.md) разделяет разрешённое чтение реальных
данных, изменение runtime и публичную публикацию. Offline-аудиту сохранённого клона
не нужен запущенный UI. Для runtime проверяй актуальную привязку процесса, кода и
профиля; сохраняй выполненные этапы и продолжай с первого незавершённого.
Preflight reviewer должен прочитать Git/source. Ошибка среды не отменяет полезные
выводы по исходникам, но и не превращает их в завершённое независимое review.

## 7. Примеры

- Docs-only: diff/link/whitespace/privacy review → обычный PR CI; локально продуктовые full suite не нужны.
- React leaf: targeted Vitest + frontend lint/format → exact-candidate frontend tests/build в CI; повтор full у Reviewer не нужен.
- Backend service: regression + targeted pytest + lint/format → полный backend CI; frontend добавляется только при реальном consumer/API влиянии.
- Windows restore: synthetic failure/concurrency regressions + нужный Windows probe + полный релевантный охват → independent review/UAT по контракту.
- После failed full: диагностика → failed nodes + affected tests → полный нужный gate на стабилизированном кандидате, не full после каждой правки.
