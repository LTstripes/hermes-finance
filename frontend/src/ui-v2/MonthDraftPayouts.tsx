import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router";
import { formatApiError } from "../api/client";
import {
  type DraftPayoutResult,
  getDraftPayoutContext,
  getPayoutRefreshStatus,
  listPayoutCalendar,
  refreshDraftPayouts,
} from "../api/payouts";
import { Button } from "../components/ui";
import { formatDate } from "../lib/format";
import { reasonCopy } from "../lib/reasonCopy";
import styles from "./UiV2MonthWorkspace.module.css";
import { UiV2Panel } from "./UiV2Panel";

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
  const sourceParams = new URLSearchParams(location.search);
  sourceParams.set("month", String(monthId));
  sourceParams.set("panel", "brokers");
  sourceParams.delete("section");
  sourceParams.delete("step");
  const context = useQuery({
    queryKey: ["draft-payouts", monthId, sourceVersion],
    queryFn: ({ signal }) => getDraftPayoutContext(monthId, signal),
    retry: false,
  });
  const refreshStatus = useQuery({
    queryKey: ["payout-refresh-status", monthId],
    queryFn: () => getPayoutRefreshStatus(monthId),
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
      refreshStatus.refetch(),
    ]);
  }

  async function recover() {
    const current = generation.current;
    try {
      await readSaved();
      if (current === generation.current) {
        setUnconfirmed(false);
        setNotice(null);
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
  const canResolveReason =
    !closed &&
    !disabled &&
    !busy &&
    !unconfirmed &&
    !reading &&
    !context.isError &&
    context.data?.status === "draft" &&
    context.data.reporting_month_id === monthId;
  const issues =
    result?.items.filter((item) => item.reason_codes.length) ??
    context.data?.items.filter((item) => item.reason_codes.length) ??
    [];
  return (
    <UiV2Panel
      id="month-draft-payouts"
      testIdPrefix="month"
      title="Будущие выплаты"
      eyebrow=""
      wide
    >
      <div className={styles.forecastContent}>
        <p>
          {refreshStatus.data?.forecast_as_of
            ? `Дата сохранённого прогноза: ${formatDate(refreshStatus.data.forecast_as_of.slice(0, 10))}`
            : "Дата сохранённого прогноза неизвестна."}
        </p>
        <div className={styles.forecastActions}>
          <Button variant="primary" type="button" disabled={!ready} onClick={() => void refresh()}>
            {busy ? "Обновляем прогноз…" : "Обновить прогноз Т-Инвест"}
          </Button>
          <Link to={`/v2/data/payouts?month=${monthId}`}>Календарь выплат</Link>
        </div>
        {unconfirmed && !busy && (
          <Button type="button" disabled={reading} onClick={() => void recover()}>
            Проверить сохранённые прогнозы
          </Button>
        )}
        {closed || context.data?.status === "closed" ? (
          <p>Месяц закрыт. Доступно чтение сохранённых прогнозов.</p>
        ) : context.data && !context.data.eligible_positions ? (
          <p>
            Сначала сохрани позиции из брокерских выписок:{" "}
            <Link to={`/v2/close?${sourceParams}#month-source-review`}>Брокерские выписки</Link>.
          </p>
        ) : null}
        {reading && <p role="status">Читаем сохранённые данные…</p>}
        {(context.isError || calendar.isError) && (
          <div role="alert">
            Не удалось прочитать сохранённые данные.
            <details>
              <summary>Подробнее об ошибке</summary>
              {formatApiError(context.error ?? calendar.error)}
            </details>
          </div>
        )}
        {notice && (
          <div role="alert">
            Не удалось подтвердить результат. Часть данных могла сохраниться.
            <details>
              <summary>Подробнее об ошибке</summary>
              {notice}
            </details>
          </div>
        )}
        {result && (
          <p role="status">{`Обновлено позиций: ${result.summary.updated}; без изменений: ${result.summary.unchanged}.`}</p>
        )}
        {!result &&
          refreshStatus.data?.automatic_refresh &&
          ["error", "partial", "needs_review"].includes(
            refreshStatus.data.automatic_refresh.status,
          ) && (
            <div role="alert">
              При автоматическом обновлении часть данных могла остаться прежней.
              <details>
                <summary>Подробнее об ошибке</summary>
                {refreshStatus.data.automatic_refresh.reason_codes.map((code) => (
                  <p key={code}>{reasonCopy(code, { surface: "draftPayouts", closed }).message}</p>
                ))}
              </details>
            </div>
          )}
        {[true, false].map((isError) => {
          const group = issues.filter(
            (item) => ("status" in item && item.status === "error") === isError,
          );
          return (
            group.length > 0 && (
              <div role="alert" key={String(isError)}>
                <p>
                  {isError
                    ? "Не удалось обновить часть данных; они могли остаться прежними."
                    : "Некоторые данные требуют проверки и могли остаться прежними."}
                </p>
                <details>
                  <summary>{isError ? "Подробнее об ошибке" : "Подробнее"}</summary>
                  <ul>
                    {group.map((item) => (
                      <li key={item.position_snapshot_id}>
                        {item.account_name} · {item.instrument_name} · {item.isin}:{" "}
                        {item.reason_codes.map((code) => {
                          const copy = reasonCopy(code, {
                            surface: "draftPayouts",
                            closed,
                            actions: {
                              instrumentMapping: {
                                available: canResolveReason,
                                href: "/v2/data/catalogs",
                              },
                              payouts: {
                                available: canResolveReason,
                                href: `/v2/data/payouts?month=${monthId}`,
                              },
                            },
                          });
                          return (
                            <p key={code}>
                              {copy.message}
                              {copy.action && (
                                <>
                                  {" "}
                                  <Link to={copy.action.href}>{copy.action.label}</Link>
                                </>
                              )}
                            </p>
                          );
                        })}
                        <details>
                          <summary>Подробности</summary>
                          <code>{item.reason_codes.join(", ")}</code>
                        </details>
                      </li>
                    ))}
                  </ul>
                </details>
              </div>
            )
          );
        })}
      </div>
    </UiV2Panel>
  );
}
