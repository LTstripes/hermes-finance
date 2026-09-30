# Performance UI v2 — план и маршрутизация работ

Parent: [#528](https://github.com/LTstripes/hermes-finance/issues/528). Обновлено: 2026-09-27.

**Статус:** implementation ещё не поставлен. #529 имеет docs-only candidate, который требует независимого review. Остальные задачи запускаются по своим gates, не автоматически. [UX/data contract candidate](PERFORMANCE_UI_V2_CONTRACT.md) не считается принятым только из-за появления этого файла.

## 1. Актуальная база и изоляция

- Canonical main, проверенный при старте: `988090419b6edfbfa5f6ef5c0a02064fedb07fb2`.
- Exact-main push CI: `36307812833` — SUCCESS.
- Staging: `integration/performance-ui-v2`, обновлённый checkpoint `3254f0dd413118cf6b88032346c5434330bf280a`.
- Refresh — механический two-parent merge старого staging `435eac2979555a3574bafd8cbf1e7a6a00e5d640` и exact main. До refresh: 1 planning-only commit ahead / 87 behind. Все продуктовые файлы после refresh совпадают с exact main; исходный план сохранён, история не переписана.
- Исторический split: `f328c82b6c7c3af0f6cd436c7e1d408bb54a8885`; это больше не baseline для новых Workers.
- Worker #529: ChatGPT/Lera, GitHub-native branch `task/529-performance-ui-contract` от `3254f0d…`. Это авторство, не независимое принятие собственного результата.
- Каждый локальный Worker/Reviewer получает отдельный физический workspace и точный SHA при запуске. Абсолютные пути — только в owner-local assignment, не в tracked docs. Не переключать/сбрасывать занятые или грязные рабочие деревья.
- Child PR идут в staging. Main/Stable/Preview/private DB/.env/backups/exports не затрагиваются. Никакого force-push, автономной очереди или релиза этой постановкой не разрешено.

## 2. Что уже завершено вне нашего потока

По [CURRENT_STATUS](../CURRENT_STATUS.md) и [audit closeout](../DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md), #484–#498 и #536–#539 завершены, aggregate #509 интегрирован в main. Эти работы **включены в нашу обновлённую базу**, не ждут реализации повторно.

- #494 / PR #526: material-signature binding уже включён. Актуальная миграция — `0044_observed_valuation_material_signature`, не прежний номер 0042 из промежуточного кандидата.
- #498: контракт known subtotal / portfolio-source coverage и его распространение реализованы. Performance cash-history/in-kind/membership gates остаются отдельными утверждениями.
- #509: coherent reads, write/close/correction serialization и invalidation переиспользуются. Не копировать старые варианты из прежней integration ветки.
- #476 / PR #548: real-backend G04 gate уже в canonical CI; для #541 переиспользовать текущую инфраструктуру, не создавать второй проект её восстановления.

Завершение audit hardening не означает готовность новых UI/actions: historical membership write path и публичный PRE/POST capture adapter требуют своих контрактных границ. Не смешивать завершённый bugfix и ещё не реализованную возможность.

## 3. Продуктовая структура

Один вход **Капитал → Доходность**. Уже существующий `UiV2CapitalPage::PerformanceBlock` становится компактным summary. Подробности вынесены в локальный detail, без нового глобального меню/Home-карточек.

```text
Капитал → Доходность
Период / фактические даты / валюта / состав расчёта

TWRR: … % за период       XIRR: … % годовых
Одна понятная строка состояния → Проверить данные

По счетам | По классам (только после Phase B)
Название / TWRR / XIRR / состояние
Подробности строки — по запросу
```

Новые целевые маршруты #529: `/v2/capital/performance` и `/v2/capital/performance/data`. Это proposal до acceptance/implementation, не существующие на baseline страницы.

Принцип действия: **что не подтверждено → где → что действительно можно сделать → свежая проверка результата**. Не обещать ввод/исправление, пока capability не реализована. Пустой ledger не означает complete; успешное сохранение не означает готовую доходность. XIRR может быть доступен при недоступном TWRR.

Периоды используют реальные snapshot dates, не название отчётного месяца. Нет подмены отсутствующей границы соседней датой/коротким успешным окном. Исторический scope не выводится из текущих account flags. Rates не суммируются и не усредняются. Bridge остаётся вторичным изменением стоимости, не «прибылью».

По классам сначала #534 data/capability contract, затем принятый backend и UI. Инструменты — только возможный будущий drill-down, не массовая таблица и не реализация этого milestone.

## 4. Кто делает задачи

Это per-task рекомендации для текущего запуска, не глобальный рейтинг моделей. Конкретный provider/model/variant/effort фиксируется из фактического клиента, не из догадки по названию. Owner сейчас тестирует Muse Spark 1.3 и MiMo V2.6 Flash в OpenCode; неизвестные варианты reasoning не назначаются как будто проверенные.

| Задача | Где и кем | Текущий gate / результат |
| --- | --- | --- |
| [#529](https://github.com/LTstripes/hermes-finance/issues/529) UX/evidence contract | Авторство здесь в ChatGPT; независимый senior review в отдельной сессии | Candidate. Muse может дать узкий read-only UX/copy report, не финансовый ACCEPT. |
| [#530](https://github.com/LTstripes/hermes-finance/issues/530) Readiness projection | Локальный сильный backend Worker; контракт/интеграция здесь | После принятия #529. Старый #509 уже не blocker. Нужны реальные backend/API checks. |
| [#531](https://github.com/LTstripes/hermes-finance/issues/531) Portfolio/account UI | Кандидат для Muse в OpenCode после заморозки API; local frontend harness | После #529/#530. Один writer страницы и serial navigation slot. |
| [#532](https://github.com/LTstripes/hermes-finance/issues/532) Owner data actions | Локальный сильный cross-layer Worker; write-contract decisions здесь | После #529/#530. Historical membership writer требует отдельного bounded contract, не direct ORM/backfill. |
| [#533](https://github.com/LTstripes/hermes-finance/issues/533) PRE/POST capture | Локальный сильный Worker + независимый review | #494 уже включён; capture DTO/UI ещё нет. Подпись берётся при начале формы, не заново только при POST. |
| [#534](https://github.com/LTstripes/hermes-finance/issues/534) Class-return contract | Синтез и решение здесь; MiMo в OpenCode — отдельный read-only source inventory | Inventory можно начать параллельно #529. Он не authorizes class calculations или GO. |
| [#535](https://github.com/LTstripes/hermes-finance/issues/535) Class backend | Локальный сильный numerical/data Worker | BLOCKED ON accepted #534 и его prerequisites. Audit completion этот gate не отменяет. |
| [#540](https://github.com/LTstripes/hermes-finance/issues/540) Class UI | Кандидат для Muse; MiMo — только отдельно назначенный ограниченный helper/test slice | После #531/#534/#535. Без двух writers в одних файлах. |
| [#541](https://github.com/LTstripes/hermes-finance/issues/541) E2E / UAT | Здесь runbook и reconciliation; runtime/browser проверки локально; private UAT — Owner | Отдельные exact aggregate checkpoints A/B. Старый #358 не переоткрывается. |

Не выдавать незнакомой модели financial writes только ради эксперимента. Сначала отдельные ограниченные read-only задания ниже; успешный отчёт не заменяет независимое review implementation.

## 5. Первые параллельные задания

**A — Muse, внутри #529:** прочитать exact contract candidate и актуальный Capital UI; дать максимум 5–7 конкретных UX-проблем и короткие альтернативные тексты состояния/действия. Проверить минимализм, понятность XIRR/TWRR, доступные versus неподдержанные действия, возврат в тот же период. Не менять код/документ и не утверждать финансовый ACCEPT. Результат — отчёт в чате исполнителя.

**B — MiMo, внутри #534:** на том же exact code baseline составить source inventory по депозитам/облигациям/акциям/золоту: какие исторические valuations/flows/classification существуют, какие поля/сервисы их подтверждают, чего не хватает. Нужны пути и строки, не домыслы о возможностях. Отдельно заметить sold holdings, account-versus-class scope и новые write paths. Без новых формул/GO/изменений/провайдеров; результат — отчёт в чате исполнителя для дальнейшего synthesis.

**C — независимый senior reviewer #529:** отдельный контекст, exact candidate/PR; проверка contract/source consistency и ложных обещаний action paths. Это отдельное review от Muse UX-отчёта. Автор #529 не выдаёт себе independent ACCEPT.

Exact SHA, ограниченное разрешение создать конкретный отсутствующий workspace и имя выбранной модели находятся в актуальном launch-note/Owner prompt. Указание workspace не означает, что он уже существует или подготовлен. Provider credentials и любые приватные данные не входят в эти задания.

## 6. Параллельный UI parity и последовательность

#554/#570 и [#575](https://github.com/LTstripes/hermes-finance/issues/575) продолжаются отдельно. #575 владеет денежным результатом `/v2/capital/monthly-result`; Performance — процентной доходностью за интервал. Не реализовывать #575 повторно и не называть его unrealized snapshot «прибылью за месяц».

`frontend/src/app/App.tsx`, UiV2Entry, Capital/Reports links и общий shell согласуются в одном Integrator-owned serial slot совместно с #555/#569/#575. Остальные Workers держат изменения в leaf files. Наличие отдельной ветки не устраняет будущие конфликты общей навигации.

Фаза A: #529 → review → #530 → #531/#532 → #533 → #541 A.

Фаза B: #534 inventory/synthesis → independent contract acceptance → необходимые bounded prerequisites → #535 → #540 → #541 B.

B не задерживает полезную поставку A. BLOCK/unsupported классов не считается реализованной разбивкой. Смена main не повод ежедневно перестраивать кандидатов: refresh только при доказанной необходимости и отдельном assignment.

## 7. Проверки и завершение

Docs candidate требует проверки источников/diff/privacy и независимого review. Здесь не заявляются backend/frontend suites, Windows runtime или Owner UAT. Product Worker следует [VERIFICATION_POLICY](../VERIFICATION_POLICY.md), риски/review — [MODEL_ROUTING](../MODEL_ROUTING.md).

Для реализации нужен synthetic journey, а не только три текста unavailable: понятная причина → просмотр данных → поддержанное явное действие → fresh read → XIRR/TWRR либо честный оставшийся blocker. Coverage cash/in-kind независимы; missing historical membership не лечится текущим флагом; PRE/POST не синтезируются. Zero/loss, ошибки, stale reads, corrected evidence, CLOSED guards и narrow/keyboard/deep links остаются acceptance gates.

Final project acceptance/merge — после required reviews и exact aggregate evidence/Owner UAT. Release и Stable promotion отдельны. Исторический план 2026-09-25 сохранён в Git; этот документ и актуальные Integrator notes заменяют его прежние статусы зависимостей, не финансовые определения.
