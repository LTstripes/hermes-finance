import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { listAccounts } from "../api/accounts";
import type { BrokerApplyResult } from "../api/brokerSnapshot";
import { formatApiError } from "../api/client";
import { listInstruments } from "../api/instruments";
import { getCloseReadiness, getMonth, listMonths } from "../api/months";
import { listPositions } from "../api/positions";
import type {
  Account,
  CloseReadiness,
  Instrument,
  PositionSnapshot,
  ReportingMonth,
} from "../api/types";
import { BrokerSnapshotPanel } from "../components/BrokerSnapshotPanel";
import {
  monthlyCloseReturnPath,
  parseMonthlyCloseReturnContext,
  withSelectedReturnMonth,
} from "../components/month-close/navigation";
import { formatMonth, formatQuantity } from "../lib/format";
import { queryKeys } from "../queryClient";
import { DataMonthContext, resolveDataMonth, UiV2DataFrame } from "./UiV2DataShell";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";
import styles from "./UiV2AlfaBaseline.module.css";

type View = {
  month: ReportingMonth;
  accounts: Account[];
  instruments: Instrument[];
  positions: PositionSnapshot[];
  readiness: CloseReadiness;
};

function BaselineTool({ monthId }: { monthId: number }) {
  const client = useQueryClient();
  const alive = useRef(true);
  const readGeneration = useRef(0);
  const location = useLocation();
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);

  const readView = useCallback(
    async (result?: BrokerApplyResult) => {
      const generation = ++readGeneration.current;
      setView(null);
      setError(null);
      try {
        const [month, accounts, instruments, positions, readiness] = await Promise.all([
          getMonth(monthId),
          listAccounts(),
          listInstruments(),
          listPositions(monthId),
          getCloseReadiness(monthId),
        ]);
        if (
          month.id !== monthId ||
          positions.some((row) => row.reporting_month_id !== monthId) ||
          readiness.year !== month.year ||
          readiness.month !== month.month ||
          readiness.snapshot_date !== month.snapshot_date ||
          readiness.status !== month.status
        ) {
          throw new Error(
            "Получен результат другого месяца или несогласованный статус. Обновите данные.",
          );
        }
        if (
          result &&
          (result.items.length !== result.selected_count ||
            result.items.some(
              (item) =>
                !positions.some(
                  (row) =>
                    row.id === item.position_snapshot_id &&
                    row.account_id === item.account_id &&
                    row.instrument_id === item.instrument_id,
                ),
            ))
        ) {
          throw new Error("Записанные позиции не подтверждены повторным чтением.");
        }
        if (alive.current && generation === readGeneration.current)
          setView({ month, accounts, instruments, positions, readiness });
      } catch (cause) {
        if (alive.current && generation === readGeneration.current) setError(formatApiError(cause));
        throw cause;
      }
    },
    [monthId],
  );

  useEffect(() => {
    alive.current = true;
    void readView().catch(() => {});
    return () => {
      alive.current = false;
      readGeneration.current += 1;
    };
  }, [readView]);

  // Keep the reusable panel mounted through post-apply readback. Its success
  // banner waits for this callback; stale canonical rows are hidden meanwhile.
  const [catalogs, setCatalogs] = useState<Pick<View, "accounts" | "instruments"> | null>(null);
  useEffect(() => {
    if (view) setCatalogs(view);
  }, [view]);

  async function applied(result: BrokerApplyResult, target: number) {
    if (target !== monthId) throw new Error("Месяц применения изменился.");
    await client.invalidateQueries({ refetchType: "none" });
    await readView(result);
  }

  return (
    <>
      {error ? (
        <UiV2Notice
          title="Актуальный результат не подтверждён"
          retry={() => void readView().catch(() => {})}
        >
          {error}
        </UiV2Notice>
      ) : null}
      {!view && !error ? <UiV2Loading label="Перечитываем месяц, позиции и готовность…" /> : null}
      {catalogs ? (
        <BrokerSnapshotPanel
          accounts={catalogs.accounts}
          instruments={catalogs.instruments}
          initialMonthId={monthId}
          monthlyClose
          onApplied={applied}
          onInstrumentCreated={async () => {
            const instruments = await listInstruments();
            if (alive.current)
              setCatalogs((current) => (current ? { ...current, instruments } : current));
          }}
        />
      ) : null}
      {view ? (
        <section className={styles.readback} aria-label="Актуальные позиции месяца">
          <DataMonthContext month={view.month} automatic={false} />
          <h2>Позиции после последнего чтения</h2>
          <ul>
            {view.positions.map((row) => (
              <li key={row.id}>
                {view.accounts.find((account) => account.id === row.account_id)?.name ??
                  `Счёт ${row.account_id}`}{" "}
                ·{" "}
                {view.instruments.find((instrument) => instrument.id === row.instrument_id)?.name ??
                  `Инструмент ${row.instrument_id}`}{" "}
                · {formatQuantity(row.quantity)}
              </li>
            ))}
          </ul>
          {view.positions.length === 0 ? <p>В этом месяце пока нет позиций.</p> : null}
          <p>
            Готовность к закрытию: {view.readiness.can_close ? "можно закрыть" : "есть ограничения"}
            .
          </p>
          <p>Базовый срез не подтверждает полноту истории Performance.</p>
          <Link
            to={`/v2/data/months/${monthId}?${new URLSearchParams([...new URLSearchParams(location.search).entries()].filter(([key]) => key !== "section")).toString()}&section=positions${location.hash}`}
          >
            Открыть позиции месяца
          </Link>
        </section>
      ) : null}
    </>
  );
}

export default function UiV2AlfaBaselinePage() {
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const months = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
  });
  const resolution = resolveDataMonth(
    params.getAll("month"),
    months.data ?? [],
    isQueryReady(months),
  );
  const month = resolution.kind === "ready" ? resolution.month : null;
  const close = parseMonthlyCloseReturnContext(params);
  const returnPath = close && close.monthId === month?.id ? monthlyCloseReturnPath(close) : null;
  return (
    <UiV2DataFrame
      active="alfa-baseline"
      title="Alfa baseline"
      subtitle="Предпросмотр и явное применение текущего базового среза Alfa PRO."
      monthId={month?.id}
      v1ReturnPath="/accounts"
    >
      <div className={styles.context}>
        <label htmlFor="alfa-month">Месяц базового среза</label>
        <select
          id="alfa-month"
          value={month?.id ?? ""}
          onChange={(event) =>
            navigate(
              `${location.pathname}?${withSelectedReturnMonth(params, Number(event.target.value))}${location.hash}`,
            )
          }
        >
          <option value="" disabled>
            Выбери месяц
          </option>
          {(months.data ?? []).map((row) => (
            <option key={row.id} value={row.id}>
              {formatMonth(row.year, row.month)}
            </option>
          ))}
        </select>
        {returnPath ? <Link to={returnPath}>Вернуться к закрытию</Link> : null}
      </div>
      {months.isError ? (
        <UiV2Notice title="Не удалось загрузить месяцы" retry={() => void months.refetch()}>
          Попробуй перечитать список.
        </UiV2Notice>
      ) : resolution.kind === "loading" ? (
        <UiV2Loading label="Загружаем месяцы…" />
      ) : !month ? (
        <UiV2Notice title="Месяц не выбран">
          Явный месяц отсутствует или некорректен. Выбери доступный месяц.
        </UiV2Notice>
      ) : (
        <BaselineTool key={`${month.id}:${location.search}`} monthId={month.id} />
      )}
    </UiV2DataFrame>
  );
}
