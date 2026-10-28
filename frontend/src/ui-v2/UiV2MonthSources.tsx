import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { formatApiError } from "../api/client";
import { listAllSourceIntakes, type SourceIntake } from "../api/sourceIntake";
import type { ReportingMonth } from "../api/types";
import { BrokerMonthReview } from "../components/month-close/BrokerMonthReview";
import { useBrokerOriginalSession } from "../components/month-close/brokerOriginalSession";
import { useSourceIntakeRecovery } from "../components/month-close/SourceIntakeJournal";
import { SourceIntakeUpload } from "../components/month-close/SourceIntakeUpload";
import { ConfirmDialog } from "../components/ui";
import { formatDate } from "../lib/format";
import { brokerSourceTitle } from "../lib/ownerCopy";
import { lastDayOfMonth } from "../lib/period";
import { monthWorkspacePath } from "./monthSelection";
import { SourceMonthReturn } from "./SourceMonthReturn";
import { UiV2MonthInstruments } from "./UiV2MonthInstruments";
import styles from "./UiV2MonthWorkspace.module.css";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

function sourceAccounts(intake: SourceIntake): string[] {
  return [
    ...new Set([intake.document.filename_account, ...(intake.document.source_accounts ?? [])]),
  ].filter((value) => typeof value === "string" && value.trim().length > 0);
}

export function UiV2MonthSources({
  month,
  onReview,
  canClose,
  onPendingChange,
  onDirtyChange,
}: {
  month: Pick<ReportingMonth, "id" | "year" | "month" | "status">;
  onReview?: (id: number) => void;
  canClose?: boolean;
  onPendingChange?: (value: boolean) => void;
  onDirtyChange?: (value: boolean) => void;
}) {
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const { session, original } = useBrokerOriginalSession();
  const [reviewExpanded, setReviewExpanded] = useState(Boolean(original.file));
  const savedFiles = useRef(new Map<number, File>());
  const savedSources = useRef(new Map<number, SourceIntake>());
  const sourceAfterNavigation = useRef<{ id: number; file?: File; account: string } | null>(null);
  const [nextSource, setNextSource] = useState<{ id: number; file?: File; account: string } | null>(
    null,
  );
  const [reviewError, setReviewError] = useState<{ message: string; monthId?: number } | null>(
    null,
  );
  const [nextAccount, setNextAccount] = useState<string | null>(null);
  const [uploadPending, setUploadPending] = useState(false);
  useEffect(() => {
    onPendingChange?.(uploadPending);
    return () => onPendingChange?.(false);
  }, [uploadPending, onPendingChange]);
  const [journalDirty, setJournalDirty] = useState(false);
  const reportDirty = useCallback(
    (dirty: boolean) => {
      setJournalDirty(dirty);
      onDirtyChange?.(dirty);
    },
    [onDirtyChange],
  );
  const reportUploadPending = useCallback((pending: boolean) => {
    setUploadPending(pending);
  }, []);
  const { command: journalCommand } = useSourceIntakeRecovery();
  // Raw URL values distinguish invalid/duplicate scopes, including A→invalid→A.
  const scope = JSON.stringify(params.getAll("source_account"));
  const [review, setReview] = useState(() => ({
    // A retained command owns its original scope even after SPA remount. A
    // retained File without a command must be reselected for an explicit filter.
    scope: journalCommand
      ? JSON.stringify(journalCommand.sourceAccount ? [journalCommand.sourceAccount] : [])
      : original.pending
        ? JSON.stringify([original.pending.preview.document.filename_account])
        : original.file && scope !== "[]"
          ? "[]"
          : scope,
    generation: 0,
    monthId: journalCommand?.monthId ?? month.id,
    selection: null as {
      id: number;
      file?: File;
      snapshot?: SourceIntake;
      preserveDraft?: boolean;
    } | null,
  }));
  const changingScope = scope !== review.scope || month.id !== review.monthId;
  const unresolved = Boolean(original.pending) || original.busy || Boolean(journalCommand);
  const uploadWouldDiscard =
    Boolean(original.file) && (journalDirty || original.decisions.length > 0);
  useLayoutEffect(() => {
    if (!changingScope || unresolved) return;
    // Never select/clear while a command's ACK or independent GET is unresolved.
    session.select(null, month.id, "");
    const target = sourceAfterNavigation.current;
    const selected =
      target && scope === JSON.stringify(target.account ? [target.account] : []) ? target : null;
    sourceAfterNavigation.current = null;
    setReview((previous) => ({
      scope,
      monthId: month.id,
      generation: previous.generation + 1,
      selection: selected ? { id: selected.id, file: selected.file } : null,
    }));
  }, [changingScope, unresolved, scope, month.id, session]);
  const list = useQuery({
    queryKey: ["source-intakes", month.id, "month-overview"],
    queryFn: ({ signal }) => listAllSourceIntakes(signal),
    refetchOnWindowFocus: true,
  });
  const period = `${month.year}-${String(month.month).padStart(2, "0")}`;
  // A journal can be unbound. Calendar overlap is a display filter, never financial binding.
  const sources = (list.data ?? []).filter(
    (item) =>
      item.state.reporting_month_id === month.id ||
      (item.state.reporting_month_id === null &&
        item.covered_from.slice(0, 7) <= period &&
        item.covered_to.slice(0, 7) >= period),
  );
  // Prior originals can supply a quantity scenario, never this month's closing EOD.
  const history = (list.data ?? []).filter((item) => item.covered_from.slice(0, 7) <= period);
  const accounts = [...new Set(history.flatMap(sourceAccounts))].sort();
  const accountValues = params.getAll("source_account");
  const account = accountValues[0] ?? "";
  const invalidAccount = accountValues.length > 1 || (!!account && !accounts.includes(account));
  const visible = invalidAccount
    ? []
    : sources.filter((item) => !account || sourceAccounts(item).includes(account));
  const closing = lastDayOfMonth(month.year, month.month);
  const fullMonthSources = visible.filter(
    (item) => item.covered_from === `${period}-01` && item.covered_to === closing,
  );
  const overlappingSources = visible.length - fullMonthSources.length;

  function selectAccount(value: string) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete("source_account");
      next.delete("instrument_isin");
      next.delete("payout_as_of");
      if (value) next.set("source_account", value);
      return next;
    });
  }
  function chooseSource(target: { id: number; file?: File; account: string }) {
    session.select(null, month.id, "");
    if (target.account !== account) {
      // Router navigation may commit later than local state. Attach the exact
      // File only after the URL has committed its new account scope.
      sourceAfterNavigation.current = target;
      selectAccount(target.account);
    } else {
      setReview((previous) => ({
        ...previous,
        monthId: month.id,
        generation: previous.generation + 1,
        selection: { id: target.id, file: target.file },
      }));
    }
    setReviewExpanded(true);
    setReviewError(null);
    onReview?.(target.id);
  }
  function openSource(id: number) {
    if (unresolved) return;
    const source = savedSources.current.get(id) ?? list.data?.find((item) => item.id === id);
    if (!source) {
      setReviewError({ message: "Источник ещё не подтверждён. Обнови список выписок." });
      return;
    }
    const boundMonth = source.state.reporting_month_id;
    if (boundMonth !== null && boundMonth !== month.id) {
      setReviewError({
        message: "Выписка привязана к другому месяцу. Открой исходный месяц для просмотра.",
        monthId: boundMonth,
      });
      return;
    }
    const sourceScope = sourceAccounts(source);
    const targetAccount =
      !account || sourceScope.includes(account)
        ? account
        : source.document.filename_account || (sourceScope.length === 1 ? sourceScope[0] : "");
    if (account && (!targetAccount || !accounts.includes(targetAccount))) {
      setReviewError({
        message:
          "Счёт загруженной выписки ещё не подтверждён в этом периоде. Обнови список и выбери счёт явно.",
      });
      return;
    }
    const selectedId = client.getQueryData<number>(["source-intake-selection", month.id, account]);
    if (selectedId === id && journalDirty && targetAccount === account) {
      setReviewExpanded(true);
      return;
    }
    const target = { id, file: savedFiles.current.get(id), account: targetAccount };
    if ((journalDirty || original.file) && (selectedId !== id || targetAccount !== account))
      setNextSource(target);
    else chooseSource(target);
  }
  const renderSources = (items: SourceIntake[], label: string) => (
    <ul className={styles.sources} aria-label={label}>
      {items.map((intake) => (
        <li key={intake.id} className={styles.source}>
          <div>
            <strong>
              Источник #{intake.id} · {sourceAccounts(intake).join(" / ") || "Счёт неизвестен"}
            </strong>
            <p>
              {formatDate(intake.covered_from)} — {formatDate(intake.covered_to)} · наблюдений:{" "}
              {intake.observations.length}
            </p>
            <p>
              {intake.covered_from === `${period}-01` && intake.covered_to === closing
                ? "Полный календарный период по датам; достаточность доказательств проверяется отдельно."
                : "Историческое или частичное пересечение; не полный месячный оригинал."}
            </p>
            <p>
              {intake.state.reporting_month_id === null
                ? "Без финансовой привязки"
                : "Привязан к месяцу"}{" "}
              · исключений: {intake.exceptions.length}.
            </p>
            {!!intake.exceptions.length && (
              <details>
                <summary>Что исправить</summary>
                <ul>
                  {[...new Set(intake.exceptions)].map((code) => (
                    <li key={code}>
                      {brokerSourceTitle(code) ?? "Нужно уточнить доказательства источника"}{" "}
                      <code>{code}</code>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
          <div className={styles.actions}>
            <button
              type="button"
              disabled={changingScope || unresolved}
              onClick={() => openSource(intake.id)}
            >
              {month.status === "closed" ? "Просмотреть разбор" : "Разобрать и исправить"} #
              {intake.id}
            </button>
            {sourceAccounts(intake)
              .filter((value) => !account || value === account)
              .map((value) => (
                <Link
                  key={value}
                  to={`/v2/capital/monthly-returns?${new URLSearchParams({ source_account: value, bond_period: `${period}-01` })}#bond-slice`}
                >
                  Облигации и доходность · {value}
                </Link>
              ))}
          </div>
        </li>
      ))}
    </ul>
  );

  return (
    <>
      <ConfirmDialog
        open={nextSource !== null}
        title="Открыть другую выписку?"
        description="Несохранённый разбор и предварительный результат будут сброшены. Сохранённые данные останутся."
        cancelLabel="Остаться"
        confirmLabel="Открыть выписку"
        onCancel={() => setNextSource(null)}
        onConfirm={() => {
          if (nextSource) chooseSource(nextSource);
          setNextSource(null);
        }}
      />
      {reviewError && (
        <p role="alert">
          {reviewError.message}{" "}
          {reviewError.monthId && (
            <Link to={monthWorkspacePath(reviewError.monthId, undefined, "panel=brokers")}>
              Открыть исходный месяц
            </Link>
          )}
        </p>
      )}
      <ConfirmDialog
        open={nextAccount !== null}
        title="Сменить счёт?"
        description="Несохранённый разбор и предварительный результат будут сброшены. Сохранённые выписки останутся."
        cancelLabel="Остаться"
        confirmLabel="Сменить счёт"
        onCancel={() => setNextAccount(null)}
        onConfirm={() => {
          if (nextAccount !== null) selectAccount(nextAccount);
          setNextAccount(null);
        }}
      />
      <UiV2Panel
        eyebrow="Выписки"
        title="Брокерские выписки"
        id="month-sources"
        testIdPrefix="month"
        wide
      >
        <div className={styles.stack}>
          <p>Загрузи выписки, выбери счёт и проверь распознанные бумаги.</p>
          <section aria-label="Состояние источников месяца">
            {list.isPending || list.isFetching ? (
              <p>Проверяем сохранённые выписки…</p>
            ) : list.isError ? (
              <p>Число сохранённых выписок не подтверждено.</p>
            ) : (
              <>
                <p>
                  {period} · счёт источника:{" "}
                  {invalidAccount ? "не подтверждён" : account || "выбери один счёт"}.
                  {invalidAccount
                    ? ""
                    : ` Полных месячных оригиналов: ${fullMonthSources.length}. Исторических или частичных пересечений: ${overlappingSources}.`}
                </p>
                {!invalidAccount && fullMonthSources.length === 0 && (
                  <p>
                    Нет полного месячного оригинала. Нужны остатки на {closing}; историческое
                    пересечение не доказывает конец месяца.
                  </p>
                )}
                <nav className={styles.sourceNav} aria-label="Действия с источниками месяца">
                  <a href="#month-source-list">Сохранённые выписки и исключения</a>
                  {!invalidAccount && account && (
                    <a href="#month-instruments">Инструменты, сделки и выплаты</a>
                  )}
                </nav>
              </>
            )}
            <details>
              <summary>Подробнее о данных и закрытии</summary>
              <p>
                {month.status === "closed"
                  ? "Финансовый месяц CLOSED · только чтение."
                  : canClose === true
                    ? "Финансовый DRAFT · серверная проверка допускает явное закрытие."
                    : "Финансовый DRAFT · готовность к закрытию проверяется отдельно."}{" "}
                Сохранение выписки и предварительная доходность не означают финансового принятия.{" "}
                <Link to={monthWorkspacePath(month.id, "final_review_close")}>
                  Проверка финансового месяца
                </Link>
              </p>
            </details>
          </section>
          {month.status === "closed" ? (
            <p>
              Месяц закрыт. Сохранённые источники доступны для чтения; для исправлений явно открой
              месяц заново.
            </p>
          ) : (
            <SourceIntakeUpload
              key={month.id}
              compact
              onPendingChange={reportUploadPending}
              reviewDisabled={unresolved}
              disabled={unresolved || uploadWouldDiscard}
              knownSources={list.data}
              onSaved={(file, intake) => {
                savedFiles.current.set(intake.id, file);
                savedSources.current.set(intake.id, intake);
                // Reselecting this exact original supplies bytes without replacing
                // the user's unsaved currency/identity form after Reload.
                const selectedId = client.getQueryData<number>([
                  "source-intake-selection",
                  month.id,
                  account,
                ]);
                if (selectedId === intake.id)
                  setReview((previous) => ({
                    ...previous,
                    selection: { id: intake.id, file, snapshot: intake, preserveDraft: true },
                  }));
              }}
              onReview={openSource}
            />
          )}
          {uploadWouldDiscard && month.status !== "closed" && (
            <p>Перед следующей загрузкой сохрани текущий разбор или явно выбери другую выписку.</p>
          )}
          <details>
            <summary>Подробнее об источниках</summary>{" "}
            <p className={styles.note}>
              Загрузка сохраняет наблюдения без привязки к финансовому месяцу или счёту Hermes.
              Неизвестный ISIN требует явного разбора. Оригиналы после Reload нужно выбрать заново.
              Другие периоды доступны в{" "}
              <Link to="/v2/data/source-intake">общем журнале источников</Link>.
            </p>
          </details>
          {list.isPending ? (
            <UiV2Loading label="Читаем источники месяца…" />
          ) : list.isError ? (
            <UiV2Notice title="Источники месяца не подтверждены" retry={() => void list.refetch()}>
              {formatApiError(list.error)}
            </UiV2Notice>
          ) : (
            <>
              <label className={styles.field} id="month-source-list">
                Счёт источника месяца
                <select
                  aria-label="Счёт источника месяца"
                  disabled={uploadPending}
                  value={account}
                  onChange={(event) => {
                    const value = event.target.value;
                    if ((journalDirty || original.file) && !unresolved) setNextAccount(value);
                    else selectAccount(value);
                  }}
                >
                  <option value="">Все счета</option>
                  {invalidAccount && (
                    <option value={account}>Недоступный счёт: {account || "пустой"}</option>
                  )}
                  {accounts.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              {invalidAccount ? (
                <p role="alert">
                  Выбранный счёт источника не подтверждён для этого месяца. Выбери счёт явно.
                </p>
              ) : !visible.length ? (
                <p>
                  Для выбранного счёта выписок этого периода нет. Нужен оригинал с границами
                  отчётного месяца; выписки других периодов не становятся его EOD.
                </p>
              ) : (
                <>
                  {fullMonthSources.length > 0 &&
                    renderSources(fullMonthSources, "Источники и исключения месяца")}
                  {overlappingSources > 0 && (
                    <details>
                      <summary>Исторические и частичные пересечения · {overlappingSources}</summary>
                      <p>
                        Эти источники пересекают выбранный месяц, но не заменяют полный месячный
                        оригинал.
                      </p>
                      {renderSources(
                        visible.filter((item) => !fullMonthSources.includes(item)),
                        "Исторические и частичные источники",
                      )}
                    </details>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </UiV2Panel>
      {!changingScope &&
      !list.isPending &&
      !list.isError &&
      !list.isFetching &&
      !invalidAccount &&
      account ? (
        <UiV2MonthInstruments
          key={`${month.id}:${account}`}
          monthId={month.id}
          year={month.year}
          month={month.month}
          account={account}
          sourceVersion={JSON.stringify(
            history.map((source) => [source.id, source.head_seq, source.manifest_digest]),
          )}
        />
      ) : !invalidAccount && !account && sources.length > 0 ? (
        <p>
          Выбери один счёт источника, чтобы открыть инструменты и предварительные выплаты этого
          месяца.
        </p>
      ) : null}
      <div id="month-source-review" tabIndex={-1}>
        <details open={reviewExpanded || unresolved || params.get("step") === "final_review_close"}>
          {/* biome-ignore lint/a11y/noStaticElementInteractions: native summary supports keyboard activation; controlled click avoids delayed toggle events hiding GET recovery. */}
          <summary
            onClick={(event) => {
              event.preventDefault();
              setReviewExpanded((value) => !value);
            }}
          >
            Исправления и сохранение месяца
          </summary>
          {changingScope && unresolved && (
            <p role="alert">
              Переключение счёта отложено. Разбор остаётся в прежнем контексте:{" "}
              {original.pending?.preview.document.filename_account ||
                JSON.parse(review.scope).join(" / ") ||
                "Все счета"}{" "}
              · месяц #{review.monthId}. Заверши чтение результата исходного запроса. Изменения
              заблокированы; новый POST не выполняется.
            </p>
          )}
          {(!changingScope || unresolved) && (
            <BrokerMonthReview
              key={review.generation}
              monthId={review.monthId}
              closed={month.status === "closed"}
              scopeBlocked={changingScope}
              sourceAccount={
                changingScope
                  ? (JSON.parse(review.scope)[0] ?? "")
                  : invalidAccount
                    ? null
                    : account
              }
              intakeSelection={review.selection}
              workspace
              onDirtyChange={reportDirty}
            />
          )}
        </details>
      </div>
      {!!account &&
        !invalidAccount &&
        !changingScope &&
        !list.isPending &&
        !list.isError &&
        !list.isFetching && (
          <SourceMonthReturn key={`${account}:${period}`} account={account} period={period} />
        )}
    </>
  );
}
