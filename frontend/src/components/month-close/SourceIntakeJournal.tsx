import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BrokerMonthPreview,
  BrokerMonthReadback,
  InstrumentDecision,
} from "../../api/brokerMonths";
import { formatApiError } from "../../api/client";
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

/** Extends the existing identity queue; File and outbound consent remain memory-only. */
export function SourceIntakeJournal({
  monthId,
  closed,
  preview,
  disabled,
  receipts,
  onReview,
  onChanged,
}: {
  monthId: number;
  closed: boolean;
  preview: BrokerMonthPreview | null;
  disabled: boolean;
  receipts: BrokerMonthReadback[];
  onReview: (decisions: InstrumentDecision[]) => void;
  onChanged: () => void;
}) {
  const { original } = useBrokerOriginalSession();
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["source-intakes", monthId],
    queryFn: ({ signal }) => listSourceIntakes(monthId, signal),
  });
  const [selected, setSelected] = useState<SourceIntake | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [accountCurrency, setAccountCurrency] = useState("");
  const [defaultEnabled, setDefaultEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ack, setAck] = useState<IntakeAck | null>(null);
  const [reviewed, setReviewed] = useState<{ intent: IntakeIntent; digest: string } | null>(null);
  const requestId = useRef<string | null>(null);
  const epoch = useRef(0);
  const file = original.file;
  const accountId = original.accountId;
  const context = useRef({ monthId, fileEpoch: original.epoch });
  useEffect(() => {
    epoch.current++;
    setReviewed(null);
    setBusy(false);
    if (context.current.fileEpoch !== original.epoch) requestId.current = null;
    if (context.current.monthId !== monthId) {
      setSelected(null);
      setAck(null);
      setError(null);
      requestId.current = null;
    }
    context.current = { monthId, fileEpoch: original.epoch };
    return () => {
      epoch.current++;
    };
  }, [monthId, original.epoch]);

  const choose = useCallback((value: SourceIntake) => {
    epoch.current++;
    setSelected(value);
    setOverrides(value.state.overrides);
    setAccountCurrency(value.state.account_currency ?? "");
    setDefaultEnabled(value.state.default_enabled);
    setReviewed(null);
    setAck(null);
    setError(null);
    requestId.current = null;
  }, []);
  useEffect(() => {
    if (!selected && !ack && !busy && Array.isArray(list.data) && list.data.length === 1)
      choose(list.data[0]);
  }, [selected, ack, busy, list.data, choose]);
  async function readAck(value: IntakeAck, version: number) {
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
    setOverrides(current.state.overrides);
    setAccountCurrency(current.state.account_currency ?? "");
    setDefaultEnabled(current.state.default_enabled);
    setAck(null);
    setReviewed(null);
    requestId.current = null;
    await client.invalidateQueries({ queryKey: ["source-intakes", monthId] });
    // All old financial confirmations must be reviewed again after a journal command.
    onChanged();
    void client.invalidateQueries({
      predicate: (q) =>
        ["broker-months", "month-close-workflow", "dashboard"].includes(String(q.queryKey[0])),
    });
  }
  async function saveParsing() {
    if (!file || busy || ack || closed) return;
    setBusy(true);
    setError(null);
    const version = epoch.current;
    requestId.current ??= crypto.randomUUID();
    try {
      const saved = await saveSourceIntake(
        file,
        requestId.current,
        monthId,
        accountId ? Number(accountId) : null,
      );
      if (version !== epoch.current) return;
      setAck(saved);
      await readAck(saved, version);
    } catch (e) {
      if (epoch.current === version) setError(formatApiError(e));
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
    if (!selected || !file || busy || ack) return;
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
    if (!selected || !file || !reviewed || !requestId.current || busy || ack) return;
    const version = epoch.current;
    setBusy(true);
    setError(null);
    try {
      const saved = await confirmIntakeReview(
        selected.id,
        file,
        reviewed.intent,
        reviewed.digest,
        requestId.current,
        Boolean(reviewed.intent.finance_request_id),
      );
      if (epoch.current !== version) return;
      setAck(saved);
      await readAck(saved, version);
    } catch (e) {
      if (epoch.current === version) setError(formatApiError(e));
    } finally {
      if (epoch.current === version) setBusy(false);
    }
  }
  const blocked = disabled || busy || closed || Boolean(ack);
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
      {Array.isArray(list.data) && list.data.length > 0 && (
        <label className={styles.field}>
          Сохранённый разбор
          <select
            aria-label="Сохранённый разбор"
            value={selected?.id ?? ""}
            disabled={busy || Boolean(ack)}
            onChange={(e) => {
              const value = list.data?.find((v) => v.id === Number(e.target.value));
              if (value) choose(value);
            }}
          >
            <option value="">Выбери источник</option>
            {list.data.map((v) => (
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
      {ack && (
        <div role="status">
          <p>
            Сохранение подтверждено сервером. Заверши независимое чтение; новый POST не требуется.
          </p>
          <Button
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              const version = epoch.current;
              void readAck(ack, version)
                .catch((e) => setError(formatApiError(e)))
                .finally(() => setBusy(false));
            }}
          >
            Повторить чтение журнала
          </Button>
        </div>
      )}
      {data && (
        <BrokerProvisionalEstimate
          key={`provisional:${data.id}:${data.head_seq}:${data.manifest_digest}:${original.epoch}:${ack?.head_seq ?? 0}`}
          intake={data}
          file={file}
          disabled={busy || Boolean(ack)}
        />
      )}
      {error && (
        <p role="alert" className={styles.sourceName}>
          {error}
        </p>
      )}
      {queue && (
        <SourceIdentityInbox
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
