import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type {
  BrokerMonthPreview,
  BrokerMonthReadback,
  InstrumentDecision,
} from "../../api/brokerMonths";
import { ApiClientError, formatApiError } from "../../api/client";
import {
  confirmIntakeReview,
  type IntakeAck,
  type IntakeIntent,
  listSourceIntakes,
  previewIntakeReview,
  readSourceIntake,
  type SourceIntake,
  saveSourceIntake,
} from "../../api/sourceIntake";
import { brokerSourceTitle } from "../../lib/ownerCopy";
import { Button } from "../ui";
import styles from "./BrokerMonthReview.module.css";
import { BrokerProvisionalEstimate } from "./BrokerProvisionalEstimate";
import { useBrokerOriginalSession } from "./brokerOriginalSession";
import { SourceIdentityInbox } from "./SourceIdentityInbox";
import { SourceIntakeInstrumentResult } from "./SourceIntakeInstrumentResult";

type PendingCommand = {
  id: string;
  intakeId: number | null;
  monthId: number;
  sourceAccount: string;
  file: File;
  accountId: number | null;
  intent: IntakeIntent | null;
  digest: string | null;
  ack: IntakeAck | null;
};
// Like BrokerOriginalSession, uncertain journal commands belong to the app's
// QueryClient lifetime, not a mounted form. Neither bytes nor intents enter
// browser storage/query data; SPA Back cannot erase the original recovery key.
function recoveryStore() {
  let value: PendingCommand | null = null;
  const listeners = new Set<() => void>();
  return {
    snapshot: () => value,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    update: (
      next: PendingCommand | null | ((previous: PendingCommand | null) => PendingCommand | null),
    ) => {
      value = typeof next === "function" ? next(value) : next;
      for (const listener of listeners) listener();
    },
  };
}
const recoveries = new WeakMap<QueryClient, ReturnType<typeof recoveryStore>>();
export function useSourceIntakeRecovery() {
  const client = useQueryClient();
  let store = recoveries.get(client);
  if (!store) {
    store = recoveryStore();
    recoveries.set(client, store);
  }
  return {
    command: useSyncExternalStore(store.subscribe, store.snapshot),
    update: store.update,
    snapshot: store.snapshot,
  };
}

/** Extends the existing identity queue; File and outbound consent remain memory-only. */
export function SourceIntakeJournal({
  monthId,
  closed,
  preview,
  disabled,
  receipts,
  onReview,
  onChanged,
  intakeSelection,
  sourceAccount,
  onDirtyChange,
}: {
  monthId: number;
  closed: boolean;
  preview: BrokerMonthPreview | null;
  disabled: boolean;
  receipts: BrokerMonthReadback[];
  onReview: (decisions: InstrumentDecision[]) => void;
  onChanged: () => void;
  intakeSelection?: {
    id: number;
    file?: File;
    snapshot?: SourceIntake;
    preserveDraft?: boolean;
  } | null;
  sourceAccount?: string | null;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const { session, original } = useBrokerOriginalSession();
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["source-intakes", monthId],
    queryFn: ({ signal }) => listSourceIntakes(monthId, signal),
  });
  const [selected, setSelected] = useState<SourceIntake | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [accountCurrency, setAccountCurrency] = useState("");
  const [defaultEnabled, setDefaultEnabled] = useState(true);
  const [identityDirty, setIdentityDirty] = useState(false);
  const dirty = Boolean(
    identityDirty ||
      (selected &&
        (accountCurrency !== (selected.state.account_currency ?? "") ||
          defaultEnabled !== selected.state.default_enabled ||
          JSON.stringify(Object.entries(overrides).sort()) !==
            JSON.stringify(Object.entries(selected.state.overrides).sort()))),
  );
  useEffect(() => {
    onDirtyChange?.(dirty);
    return () => onDirtyChange?.(false);
  }, [dirty, onDirtyChange]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const {
    command: pendingCommand,
    update: pending,
    snapshot: pendingSnapshot,
  } = useSourceIntakeRecovery();
  const ack = pendingCommand?.ack ?? null;
  function setAck(value: IntakeAck) {
    pending((previous) =>
      previous?.id === value.request_id ? { ...previous, ack: value } : previous,
    );
  }
  function settle(id: string) {
    pending((previous) => (previous?.id === id ? null : previous));
  }
  const [reviewed, setReviewed] = useState<{ intent: IntakeIntent; digest: string } | null>(null);
  const requestId = useRef<string | null>(null);
  const epoch = useRef(0);
  const file = original.file;
  const accountId = original.accountId;
  const sources = (list.data ?? []).filter(
    (item) =>
      sourceAccount !== null &&
      (!sourceAccount ||
        [item.document.filename_account, ...(item.document.source_accounts ?? [])].includes(
          sourceAccount,
        )),
  );
  const context = useRef({ monthId, fileEpoch: original.epoch });
  useEffect(() => {
    epoch.current++;
    setReviewed(null);
    setBusy(false);
    if (context.current.fileEpoch !== original.epoch) requestId.current = null;
    if (context.current.monthId !== monthId) {
      setSelected(null);
      setError(null);
      requestId.current = null;
    }
    context.current = { monthId, fileEpoch: original.epoch };
    return () => {
      epoch.current++;
    };
  }, [monthId, original.epoch]);

  const choose = useCallback(
    (value: SourceIntake) => {
      epoch.current++;
      // Keep only the selected ID across workflow readback/remount. The row must
      // still be read from this account's current source list; no intent is cached.
      client.setQueryData(["source-intake-selection", monthId, sourceAccount], value.id);
      setSelected(value);
      setOverrides(value.state.overrides);
      setAccountCurrency(value.state.account_currency ?? "");
      setDefaultEnabled(value.state.default_enabled);
      setReviewed(null);
      setError(null);
      requestId.current = null;
    },
    [client, monthId, sourceAccount],
  );
  const openedIntake = useRef<typeof intakeSelection>(null);
  useEffect(() => {
    if (
      !intakeSelection ||
      openedIntake.current === intakeSelection ||
      busy ||
      pendingCommand ||
      disabled
    )
      return;
    const snapshot = intakeSelection.snapshot;
    const listed = list.data?.find((item) => item.id === intakeSelection.id);
    // A delayed explicit selection must not replace a newer confirmed GET.
    // Upload readback may itself be newer than a list still being refreshed.
    const value = listed && (!snapshot || listed.head_seq >= snapshot.head_seq) ? listed : snapshot;
    if (
      value &&
      (value.id !== intakeSelection.id ||
        (value.state.reporting_month_id !== null && value.state.reporting_month_id !== monthId) ||
        (sourceAccount &&
          ![value.document.filename_account, ...(value.document.source_accounts ?? [])].includes(
            sourceAccount,
          )))
    ) {
      openedIntake.current = intakeSelection;
      setError("Сохранённый источник не подтвердил текущий месяц и счёт. Выбери разбор явно.");
      return;
    }
    if (value) {
      openedIntake.current = intakeSelection;
      if (
        intakeSelection.preserveDraft &&
        selected?.id === value.id &&
        (identityDirty || original.decisions.length > 0)
      ) {
        setError(
          "Сначала сохрани решения по бумагам или явно выбери разбор заново. Твой выбор сохранён в форме.",
        );
        return;
      }
      if (intakeSelection.preserveDraft && selected?.id === value.id && dirty) {
        if (JSON.stringify(selected.state) !== JSON.stringify(value.state)) {
          setError(
            "Сохранённая версия разбора изменилась. Сверь её перед сохранением; твой ввод сохранён в форме.",
          );
          return;
        }
        setSelected(value);
        setReviewed(null);
        requestId.current = null;
        session.select(intakeSelection.file ?? null, monthId, original.accountId);
        return;
      }
      // An explicit saved-source selection retires another original's Preview,
      // decisions and public-search consent, after any pending result is resolved.
      session.select(intakeSelection.file ?? null, monthId, "");
      choose(value);
    }
  }, [
    intakeSelection,
    list.data,
    busy,
    pendingCommand,
    disabled,
    session,
    monthId,
    choose,
    sourceAccount,
    selected,
    dirty,
    identityDirty,
    original.decisions.length,
    original.accountId,
  ]);
  useEffect(() => {
    if (selected || pendingCommand || busy || list.isFetching || list.isError) return;
    const id = client.getQueryData<number>(["source-intake-selection", monthId, sourceAccount]);
    const value =
      id !== undefined
        ? sources.find((item) => item.id === id)
        : sources.length === 1
          ? sources[0]
          : null;
    if (value) choose(value);
  }, [
    selected,
    pendingCommand,
    busy,
    sources,
    choose,
    client,
    monthId,
    sourceAccount,
    list.isFetching,
    list.isError,
  ]);
  async function readAck(value: IntakeAck, version: number) {
    const command = pendingSnapshot();
    if (
      !command ||
      value.request_id !== command.id ||
      (command.intakeId !== null && command.intakeId !== value.intake_id)
    )
      throw new Error(
        "Ответ журнала не соответствует исходному запросу. Требуется чтение прежнего intent.",
      );
    const current = await readSourceIntake(value.intake_id);
    if (epoch.current !== version) return;
    if (
      current.contract_version !== "source_intake_v1" ||
      current.id !== value.intake_id ||
      current.head_seq < value.head_seq ||
      !current.history.some((h) => h.seq === value.head_seq && h.request_id === value.request_id)
    )
      throw new Error("Текущая версия разбора изменилась. Обнови очередь.");
    setSelected(current);
    client.setQueryData(["source-intake-selection", monthId, sourceAccount], current.id);
    setOverrides(current.state.overrides);
    setAccountCurrency(current.state.account_currency ?? "");
    setDefaultEnabled(current.state.default_enabled);
    setReviewed(null);
    requestId.current = null;
    await client.invalidateQueries({ queryKey: ["source-intakes", monthId] });
    // All old financial confirmations must be reviewed again after a journal command.
    if (epoch.current === version) onChanged();
    void client.invalidateQueries({
      predicate: (q) =>
        ["broker-months", "month-close-workflow", "dashboard"].includes(String(q.queryKey[0])),
    });
    settle(command.id);
  }
  async function recover() {
    if (!pendingCommand || busy) return;
    const version = epoch.current;
    setBusy(true);
    setError(null);
    try {
      if (ack) await readAck(ack, version);
      else {
        // A lost ACK is neither success nor failure. Find the original immutable
        // request in server history; never reconstruct or replay its POST.
        const candidates =
          pendingCommand.intakeId === null
            ? await listSourceIntakes(pendingCommand.monthId)
            : [await readSourceIntake(pendingCommand.intakeId)];
        if (epoch.current !== version) return;
        const matches = candidates.flatMap((item) =>
          item.history
            .filter((entry) => entry.request_id === pendingCommand.id)
            .map((entry) => ({
              intake_id: item.id,
              request_id: entry.request_id,
              head_seq: entry.seq,
              duplicate: false,
            })),
        );
        if (matches.length !== 1)
          throw new Error(
            "Результат исходного запроса пока не подтверждён. Повтори чтение журнала; intent сохранён.",
          );
        setAck(matches[0]);
        await readAck(matches[0], version);
      }
    } catch (e) {
      if (epoch.current === version) setError(formatApiError(e));
    } finally {
      if (epoch.current === version) setBusy(false);
    }
  }
  async function saveParsing() {
    if (!file || busy || pendingSnapshot() || closed || disabled) return;
    setBusy(true);
    setError(null);
    const version = epoch.current;
    requestId.current ??= crypto.randomUUID();
    const commandId = requestId.current;
    // Existing source-only observations retain their original binding. Choosing
    // a strict financial target is not permission to rebind the source journal.
    const sourceAccountId = selected
      ? selected.state.account_id
      : accountId
        ? Number(accountId)
        : null;
    pending({
      id: commandId,
      intakeId: null,
      monthId,
      sourceAccount: sourceAccount ?? "",
      file,
      accountId: sourceAccountId,
      intent: null,
      digest: null,
      ack: null,
    });
    let acknowledged = false;
    try {
      const saved = await saveSourceIntake(file, commandId, monthId, sourceAccountId);
      if (version !== epoch.current) return;
      acknowledged = true;
      setAck(saved);
      await readAck(saved, version);
    } catch (e) {
      // Settlement belongs to the command, even if its form unmounted. Match
      // the key so a late refusal cannot retire a newer pending command.
      if (!acknowledged && e instanceof ApiClientError && e.status >= 400 && e.status < 500)
        settle(commandId);
      if (epoch.current === version) {
        // A confirmed command refusal is not an unknown outcome. A failed GET
        // after ACK, including 404, must retain the original recovery intent.
        setError(formatApiError(e));
      }
    } finally {
      if (epoch.current === version) setBusy(false);
    }
  }
  function intent(link?: string): IntakeIntent {
    if (!selected) throw new Error("Выбери сохранённый разбор.");
    return {
      expected_head_seq: selected.head_seq,
      account_id: selected.state.account_id ?? (accountId ? Number(accountId) : null),
      reporting_month_id: selected.state.reporting_month_id ?? (accountId ? monthId : null),
      default_enabled: defaultEnabled,
      account_currency: accountCurrency || null,
      overrides: Object.entries(overrides).map(([isin, currency]) => ({
        isin,
        currency: currency || null,
      })),
      instrument_decisions: original.decisions.length
        ? original.decisions
        : selected.state.instrument_decisions,
      deferred_isins: selected.state.deferred_isins,
      ...(link ? { finance_request_id: link } : {}),
    };
  }
  async function inspectChanges(link?: string) {
    if (!selected || !file || busy || pendingCommand || closed || disabled) return;
    const version = epoch.current;
    setBusy(true);
    setError(null);
    setReviewed(null);
    try {
      const proposed = intent(link);
      const result = await previewIntakeReview(selected.id, file, proposed);
      if (epoch.current !== version) return;
      if (result.financial_effects !== 0)
        throw new Error("Ответ журнала не подтверждает отсутствие финансовых изменений.");
      setReviewed({ intent: proposed, digest: result.confirmation_digest });
      requestId.current = crypto.randomUUID();
    } catch (e) {
      if (epoch.current === version) setError(formatApiError(e));
    } finally {
      if (epoch.current === version) setBusy(false);
    }
  }
  async function confirm() {
    if (
      !selected ||
      !file ||
      !reviewed ||
      !requestId.current ||
      busy ||
      pendingSnapshot() ||
      closed ||
      disabled
    )
      return;
    const version = epoch.current;
    const commandId = requestId.current;
    setBusy(true);
    setError(null);
    pending({
      id: commandId,
      intakeId: selected.id,
      monthId,
      sourceAccount: sourceAccount ?? selected.document.filename_account,
      file,
      accountId: reviewed.intent.account_id,
      intent: reviewed.intent,
      digest: reviewed.digest,
      ack: null,
    });
    let acknowledged = false;
    try {
      const saved = await confirmIntakeReview(
        selected.id,
        file,
        reviewed.intent,
        reviewed.digest,
        commandId,
        Boolean(reviewed.intent.finance_request_id),
      );
      if (epoch.current !== version) return;
      acknowledged = true;
      setAck(saved);
      await readAck(saved, version);
    } catch (e) {
      const refused =
        !acknowledged && e instanceof ApiClientError && e.status >= 400 && e.status < 500;
      if (refused) settle(commandId);
      if (epoch.current === version) {
        if (refused) {
          setReviewed(null);
          requestId.current = null;
        }
        setError(formatApiError(e));
      }
    } finally {
      if (epoch.current === version) setBusy(false);
    }
  }
  const blocked = disabled || busy || closed || Boolean(pendingCommand);
  const data = selected;
  const queue =
    preview ??
    (data
      ? {
          identity: {
            can_stage: false,
            conflicts: [],
            evidence_gaps: [],
            instruments: data.proposals,
          },
          exceptions: data.exceptions,
          instrument_decisions: data.state.instrument_decisions,
        }
      : null);
  const matchingReceipt =
    data &&
    receipts.find(
      (r) =>
        r.account_id === data.state.account_id &&
        r.accepted.document?.document_sha256 === data.document_sha256,
    );
  function changed() {
    epoch.current++;
    setReviewed(null);
    requestId.current = null;
  }
  return (
    <section className={styles.stack} aria-label="Долговечный разбор источника">
      <h3>Разбор и оставшиеся исключения</h3>
      <p>
        Наблюдения и решения сохраняются локально. Оригинал остаётся у тебя: после перезагрузки
        выбери тот же XML. Сохранённый разбор ещё не финансовый DRAFT.
      </p>
      {!closed && (
        <Button type="button" disabled={blocked || !file} onClick={() => void saveParsing()}>
          Сохранить разбор
        </Button>
      )}
      {list.error && <p role="alert">Не удалось прочитать очередь: {formatApiError(list.error)}</p>}
      {sources.length > 0 && (
        <label className={styles.field}>
          Сохранённый разбор
          <select
            aria-label="Сохранённый разбор"
            value={selected?.id ?? ""}
            disabled={blocked || dirty}
            onChange={(e) => {
              const value = sources.find((v) => v.id === Number(e.target.value));
              if (value) choose(value);
            }}
          >
            <option value="">Выбери источник</option>
            {sources.map((v) => (
              <option key={v.id} value={v.id}>
                {v.covered_from} — {v.covered_to} · #{v.id} · {v.observations.length} наблюдений ·{" "}
                {v.exceptions.length} причин
              </option>
            ))}
          </select>
        </label>
      )}
      {data && (
        <>
          <p role="status">
            Сохранено наблюдений: {data.observations.length}. Версия: {data.head_seq}.{" "}
            {data.finance_link
              ? "Есть проверенная ссылка на строгий DRAFT."
              : "Финансовое принятие не подтверждено."}
          </p>
          <label className={styles.review}>
            <input
              type="checkbox"
              checked={defaultEnabled}
              disabled={blocked}
              onChange={(e) => {
                setDefaultEnabled(e.target.checked);
                changed();
              }}
            />
            RUB по умолчанию — допущение Owner, не доказательство валюты бумаги
          </label>
          <label className={styles.field}>
            Явная валюта предложения для счёта (необязательно)
            <input
              aria-label="Валюта предложения счёта"
              value={accountCurrency}
              maxLength={3}
              pattern="[A-Z]{3}"
              disabled={blocked}
              onChange={(e) => {
                setAccountCurrency(e.target.value.toUpperCase());
                changed();
              }}
            />
          </label>
          {!closed && (
            <Button type="button" disabled={blocked || !file} onClick={() => void inspectChanges()}>
              Проверить изменения разбора
            </Button>
          )}
          {matchingReceipt && !closed && (
            <Button
              type="button"
              disabled={blocked || !file}
              onClick={() => void inspectChanges(matchingReceipt.request_id)}
            >
              Проверить связь с принятым DRAFT
            </Button>
          )}
          {reviewed && (
            <div role="status">
              <p>
                Preview: финансовых изменений — 0.{" "}
                {reviewed.intent.finance_request_id
                  ? "Ссылка проверяется по принятому строгому DRAFT; его исключения сохраняются."
                  : "Сохраняются только предложения и provenance; Close не разрешается этим решением."}
              </p>
              <Button type="button" disabled={blocked || !file} onClick={() => void confirm()}>
                Подтвердить сохранение разбора
              </Button>
            </div>
          )}
          <details>
            <summary>Причины и исходные наблюдения</summary>
            <ul className={styles.sourceName}>
              {data.exceptions.map((c) => (
                <li key={c}>
                  {brokerSourceTitle(c) ?? "Доказательства требуют уточнения"} · {c}
                </li>
              ))}
            </ul>
            <p>
              Позиции: {data.document.positions.length}, сделки: {data.document.trades.length},
              Money: {data.document.money.length}. Неизвестные поля сохранены как наблюдения; их
              финансовый смысл не установлен.
            </p>
          </details>
        </>
      )}
      {data && <SourceIntakeInstrumentResult key={`${data.id}:${data.head_seq}`} intake={data} />}
      {pendingCommand && (
        <div role="status">
          <p>
            {ack
              ? "Сохранение подтверждено сервером. Заверши независимое чтение; новый POST не требуется."
              : "Ответ сохранения не подтверждён. Сначала проверь результат исходного запроса; intent сохранён."}
          </p>
          <Button type="button" disabled={busy} onClick={() => void recover()}>
            Повторить чтение журнала
          </Button>
        </div>
      )}
      {data && (
        <BrokerProvisionalEstimate
          key={`provisional:${data.id}:${data.head_seq}:${data.manifest_digest}:${original.epoch}:${ack?.head_seq ?? 0}`}
          intake={data}
          file={file}
          disabled={blocked}
        />
      )}
      {error && (
        <p role="alert" className={styles.sourceName}>
          {error}
        </p>
      )}
      {queue && (
        <SourceIdentityInbox
          onDirtyChange={setIdentityDirty}
          key={`${data?.id ?? "session"}:${data?.head_seq ?? 0}:${original.epoch}`}
          preview={queue}
          disabled={blocked || !file}
          onReview={(decisions) => {
            setReviewed(null);
            onReview(decisions);
          }}
          assessments={data?.proposals}
          overrides={overrides}
          onCurrency={
            data
              ? (isin, currency) => {
                  setOverrides((old) => ({ ...old, [isin]: currency }));
                  changed();
                }
              : undefined
          }
        />
      )}
    </section>
  );
}
