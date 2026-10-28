import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router";
import { formatApiError } from "../api/client";
import {
  type DraftPayoutResult,
  getDraftPayoutContext,
  listPayoutCalendar,
  refreshDraftPayouts,
} from "../api/payouts";
import { Button, Table, Td, Th } from "../components/ui";
import { formatDate, formatMoney } from "../lib/format";
import { brokerSourceTitle } from "../lib/ownerCopy";
import styles from "./UiV2MonthWorkspace.module.css";
import { UiV2Panel } from "./UiV2Panel";

const REASONS: Record<string, string> = {
  financial_draft_required: "Сначала сохрани финансовый DRAFT из проверенной выписки.",
  closed_month: "Месяц закрыт; обновление доступно после явного открытия заново.",
  draft_changed: "DRAFT или сопоставление изменились. Обнови чтение и проверь данные.",
  preview_changed: "Данные изменились во время запроса. Обнови чтение.",
  source_projection_changed:
    "Количество или стоимость отличаются от принятой выписки; нужна сверка DRAFT.",
  mapping_ambiguous: "Найдено несколько UID. Выбери точное сопоставление в справочнике бумаг.",
  mapping_unavailable:
    "UID не найден или провайдер недоступен; проверь сопоставление и настройки Т-Инвест.",
  mapping_excluded: "Бумага исключена из обновления; проверь её сопоставление в справочнике.",
  saved_provider_identity_changed:
    "Сохранённые прогнозы используют другой UID. Сначала проверь прежние события в календаре выплат.",
  mapping_exact_identity_required:
    "Провайдер не подтвердил точные ISIN, тип и валюту; нужна ручная проверка.",
  actual_payout_review_required:
    "Есть связь с фактической выплатой. Проверь существующую сверку выплат.",
  payout_identity_review_required:
    "Возможный дубликат или отменённая выплата. Нужна ручная проверка.",
  provider_error:
    "Провайдер не вернул подтверждённый ответ. Сохранённые прогнозы остаются доступны.",
  provider_empty:
    "Провайдер не вернул событий. Это не подтверждает отсутствие будущих выплат; сохранённые прогнозы остаются доступны.",
  refresh_unconfirmed: "Результат запроса не подтверждён. Обнови чтение сохранённых прогнозов.",
  readback_unconfirmed: "Запись отправлена, но её чтение не подтверждено. Обнови чтение.",
  position_not_positive: "Положительная позиция в принятом DRAFT отсутствует.",
};

export function MonthDraftPayouts({
  monthId,
  closed,
  disabled = false,
  sourceVersion,
  onPendingChange,
}: {
  monthId: number;
  closed: boolean;
  disabled?: boolean;
  sourceVersion?: string;
  onPendingChange?: (pending: boolean) => void;
}) {
  const client = useQueryClient();
  const location = useLocation();
  const context = useQuery({
    queryKey: ["draft-payouts", monthId, sourceVersion],
    queryFn: ({ signal }) => getDraftPayoutContext(monthId, signal),
    retry: false,
  });
  const calendar = useQuery({
    queryKey: ["draft-payout-calendar", monthId],
    queryFn: async ({ signal }) => {
      const value = await listPayoutCalendar(monthId, "v1", signal);
      if (!Array.isArray(value) || value.some((month) => !Array.isArray(month.items)))
        throw new Error("Сохранённый календарь не подтверждён.");
      return value;
    },
    retry: false,
  });
  const [busy, setBusy] = useState(false);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const [result, setResult] = useState<DraftPayoutResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const generation = useRef(0);
  const inFlight = useRef(false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: a changed month invalidates pending callbacks even when React reuses this instance.
  useLayoutEffect(() => {
    generation.current++;
    return () => {
      generation.current++;
    };
  }, [monthId]);
  useEffect(() => {
    onPendingChange?.(busy || unconfirmed);
    return () => onPendingChange?.(false);
  }, [busy, unconfirmed, onPendingChange]);
  useEffect(() => {
    const dependencies = [
      "broker-months",
      "source-intakes",
      "instruments",
      "positions",
      "instrument-market-mapping",
    ];
    const fingerprints = new Map(
      client
        .getQueryCache()
        .getAll()
        .filter((query) => dependencies.includes(String(query.queryKey[0])))
        .map((query) => [query.queryHash, JSON.stringify(query.state.data)]),
    );
    let active = true;
    let queued = false;
    let dependencyEpoch = 0;
    const readEpochs = new Map<string, number>();
    const invalidate = () => {
      if (queued) return;
      queued = true;
      // One global invalidation emits several dependency events and already
      // refetches this panel. Do not cancel/restart that read for every event.
      queueMicrotask(() => {
        queued = false;
        if (!active) return;
        void client.invalidateQueries({
          predicate: (query) =>
            ["draft-payouts", "draft-payout-calendar"].includes(String(query.queryKey[0])) &&
            query.queryKey[1] === monthId &&
            (readEpochs.get(query.queryHash) ?? 0) < dependencyEpoch,
        });
      });
    };
    const unsubscribe = client.getQueryCache().subscribe((event) => {
      if (event.type !== "updated") return;
      if (
        ["draft-payouts", "draft-payout-calendar"].includes(String(event.query.queryKey[0])) &&
        event.query.queryKey[1] === monthId
      ) {
        if (event.action.type === "fetch") readEpochs.set(event.query.queryHash, dependencyEpoch);
        // An initial GET without cached data may finish despite invalidation.
        // Its old snapshot must be followed by a read covering the later edit.
        if (
          event.action.type === "success" &&
          (readEpochs.get(event.query.queryHash) ?? 0) < dependencyEpoch
        )
          invalidate();
        return;
      }
      if (!dependencies.includes(String(event.query.queryKey[0]))) return;
      if (event.action.type === "invalidate") {
        dependencyEpoch++;
        invalidate();
        return;
      }
      if (event.action.type !== "success") return;
      const before = fingerprints.get(event.query.queryHash);
      const after = JSON.stringify(event.query.state.data);
      fingerprints.set(event.query.queryHash, after);
      if (event.action.manual || (before !== undefined && before !== after)) {
        dependencyEpoch++;
        invalidate();
      }
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [client, monthId]);

  async function readSaved() {
    await Promise.all([
      context.refetch({ throwOnError: true }),
      calendar.refetch({ throwOnError: true }),
    ]);
  }

  async function recover() {
    const current = generation.current;
    try {
      await readSaved();
      if (current === generation.current) {
        setUnconfirmed(false);
        setNotice(
          "Сохранённые прогнозы перечитаны. Незавершённый пакет не считается полностью успешным; новый запрос выполняется только по кнопке.",
        );
      }
    } catch (error) {
      if (current === generation.current) setNotice(formatApiError(error));
    }
  }

  async function refresh() {
    if (inFlight.current || !ready || !context.data) return;
    if (
      (window.history.state?.key ?? "default") !== location.key ||
      window.location.pathname !== location.pathname ||
      window.location.search !== location.search ||
      window.location.hash !== location.hash
    )
      return;
    const current = generation.current;
    inFlight.current = true;
    setBusy(true);
    setResult(null);
    setNotice(null);
    setUnconfirmed(true);
    try {
      const saved = await refreshDraftPayouts(monthId, context.data.context_digest);
      await readSaved();
      if (current === generation.current) {
        setResult(saved);
        setUnconfirmed(false);
      }
    } catch (error) {
      if (current === generation.current) {
        setNotice(
          `Результат всего запроса не подтверждён. Часть прогнозов могла сохраниться. ${formatApiError(error)}`,
        );
      }
    } finally {
      inFlight.current = false;
      if (current === generation.current) setBusy(false);
    }
  }

  const reading = context.isFetching || calendar.isFetching;
  const ready =
    !closed &&
    !disabled &&
    !busy &&
    !unconfirmed &&
    !reading &&
    !context.isError &&
    !calendar.isError &&
    context.data?.status === "draft" &&
    context.data.eligible_positions > 0;
  const rows =
    calendar.data
      ?.flatMap((month) => month.items)
      .filter((item) => item.source_kind === "provider") ?? [];
  const issues =
    result?.items.filter((item) => item.reason_codes.length) ??
    context.data?.items.filter((item) => item.reason_codes.length) ??
    [];
  return (
    <UiV2Panel
      id="month-draft-payouts"
      testIdPrefix="month"
      title="Сохранённые прогнозы Т-Инвест"
      eyebrow="После финансового DRAFT"
      wide
    >
      <div className={styles.forecastContent}>
        <p>
          Все подходящие позиции всех принятых брокерских счетов и ИИС этого месяца. Количество
          берётся из сохранённого финансового DRAFT; фильтр источников его не меняет.
        </p>
        <div className={styles.forecastActions}>
          <Button variant="primary" type="button" disabled={!ready} onClick={() => void refresh()}>
            {busy ? "Получаем и сохраняем прогнозы…" : "Получить и сохранить прогнозы Т-Инвест"}
          </Button>
          <Button type="button" disabled={busy || reading} onClick={() => void recover()}>
            Обновить чтение сохранённых прогнозов
          </Button>
        </div>
        {closed || context.data?.status === "closed" ? (
          <p>Месяц закрыт. Доступно чтение сохранённых прогнозов.</p>
        ) : !context.data?.eligible_positions && !context.isPending ? (
          <p>
            Сначала исправь исключения и сохрани финансовый DRAFT в разделе «Исправления и
            сохранение месяца». Одной загрузки XML недостаточно.
          </p>
        ) : null}
        {reading && <p role="status">Читаем финансовый DRAFT и сохранённый календарь…</p>}
        {(context.isError || calendar.isError) && (
          <p role="alert">
            Чтение не подтверждено: {formatApiError(context.error ?? calendar.error)}
          </p>
        )}
        {notice && <p role="alert">{notice}</p>}
        {result && (
          <p role="status">{`Позиций обновлено: ${result.summary.updated}; без изменений: ${result.summary.unchanged}; не поддержано: ${result.summary.unsupported}; требуют проверки: ${result.summary.needs_review}; ошибок: ${result.summary.error}.`}</p>
        )}
        {issues.length > 0 && (
          <details open>
            <summary>Что требует проверки ({issues.length})</summary>
            <ul>
              {issues.map((item) => (
                <li key={item.position_snapshot_id}>
                  {item.account_name} · {item.instrument_name} · {item.isin}:{" "}
                  {item.reason_codes.map((code) => (
                    <span key={code}>
                      {REASONS[code] ??
                        brokerSourceTitle(code) ??
                        "Проверь бумагу и ответ провайдера."}{" "}
                      <code>{code}</code>{" "}
                    </span>
                  ))}
                </li>
              ))}
            </ul>
          </details>
        )}
        <p>
          <Link to="/v2/data/catalogs">Справочник и сопоставления бумаг</Link>
          {" · "}
          <Link to={`/v2/data/payouts?month=${monthId}`}>Проверка сохранённых выплат</Link>
        </p>
        <p>
          Объявлено/прогноз (налог неизвестен). Это не подтверждённая сумма после личного налога и
          не факт получения выплаты.
        </p>
        {calendar.data?.some((month) => month.actual_attribution_coverage === "unknown") && (
          <p role="alert">
            Часть событий требует сверки с фактическими выплатами. Здесь показана только
            подтверждённая часть будущего календаря.
          </p>
        )}
        {!calendar.isError &&
          !calendar.isPending &&
          [false, true].map((principal) => (
            <div
              key={String(principal)}
              className={`${styles.instrumentTable} ${styles.forecastContent}`}
            >
              <h3>
                {principal
                  ? "Возврат номинала · отдельно от дохода"
                  : "Ожидаемые купоны и дивиденды"}
              </h3>
              <Table
                aria-label={
                  principal
                    ? "Возврат номинала · отдельно от дохода"
                    : "Ожидаемые купоны и дивиденды"
                }
              >
                <thead>
                  <tr>
                    <Th>Счёт / бумага</Th>
                    <Th>Дата</Th>
                    <Th>Выплата</Th>
                    <Th numeric>Объявлено/прогноз</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows
                    .filter((item) => (item.flow_type === "redemption") === principal)
                    .map((item) => (
                      <tr key={item.source_id}>
                        <Td>
                          {item.account_name} · {item.instrument_name}
                        </Td>
                        <Td>{formatDate(item.expected_date)}</Td>
                        <Td>
                          {item.flow_type === "coupon"
                            ? "Купон"
                            : item.flow_type === "dividend"
                              ? "Дивиденд"
                              : "Номинал"}
                        </Td>
                        <Td numeric>{formatMoney(item.expected_net_amount.amount)}</Td>
                      </tr>
                    ))}
                </tbody>
              </Table>
            </div>
          ))}
        {!calendar.isError && !calendar.isPending && !rows.length && (
          <p>Сохранённых будущих событий нет. Это не обещание нулевых выплат.</p>
        )}
      </div>
    </UiV2Panel>
  );
}
