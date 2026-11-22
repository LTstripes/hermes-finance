import { useEffect, useId, useRef, useState } from "react";
import {
  type AlfaDepositPreview,
  type AlfaDepositRequest,
  type AlfaDepositRow,
  previewAlfaDeposits,
} from "../api/alfaDeposits";
import { formatApiError } from "../api/client";
import { Button, Field, Input, Select, Table, Td, Th } from "../components/ui";
import { formatDate, formatMoney, formatPercent } from "../lib/format";
import styles from "./UiV2MonthAssets.module.css";

type Props = {
  monthId: number;
  monthLabel: string;
  disabled: boolean;
  onConfirm: (request: AlfaDepositRequest, row: AlfaDepositRow) => Promise<void>;
};

const fields = [
  ["balance", "Остаток на конец месяца"],
  ["actual_interest_received", "Полученные проценты"],
  ["annual_rate", "Ставка годовых"],
] as const;

export function AlfaDepositImport(props: Props) {
  const [open, setOpen] = useState(false);
  return (
    <div className="form-stack">
      <Button
        type="button"
        aria-expanded={open}
        disabled={props.disabled}
        onClick={() => setOpen(!open)}
      >
        Заполнить депозиты из выписки
      </Button>
      {open && <AlfaDepositForm {...props} />}
    </div>
  );
}

function AlfaDepositForm({ monthId, monthLabel, disabled, onConfirm }: Props) {
  const [request, setRequest] = useState<AlfaDepositRequest | null>(null);
  const [result, setResult] = useState<{
    request: AlfaDepositRequest;
    data: AlfaDepositPreview;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [reading, setReading] = useState(false);
  const formId = useId();
  const fileChoice = useRef(0);
  const submitting = useRef(false);
  const data = result?.request === request ? result?.data : undefined;

  useEffect(() => {
    if (!request) return;
    const controller = new AbortController();
    previewAlfaDeposits(request, controller.signal)
      .then((view) => {
        if (controller.signal.aborted) return;
        if (view.month_id !== monthId) throw new Error("Предпросмотр относится к другому месяцу.");
        setResult({ request, data: view });
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(formatApiError(cause));
      });
    return () => controller.abort();
  }, [request, monthId]);

  async function selectFile(file?: File) {
    const choice = ++fileChoice.current;
    setResult(null);
    setRequest(null);
    setNotice(null);
    setError(null);
    setReading(Boolean(file));
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) {
      setError("Файл больше 8 МБ. Выберите выписку за один месяц.");
      setReading(false);
      return;
    }
    try {
      const csv = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (choice === fileChoice.current)
        setRequest({ month_id: monthId, csv, full_month: false, bindings: {} });
    } catch {
      if (choice === fileChoice.current)
        setError("Не удалось прочитать файл. Выберите CSV Альфы в кодировке UTF-8.");
    } finally {
      if (choice === fileChoice.current) setReading(false);
    }
  }

  function change(next: AlfaDepositRequest) {
    setError(null);
    setNotice(null);
    setRequest(next);
  }

  async function confirm(row: AlfaDepositRow) {
    if (!request || !row.token || submitting.current || disabled) return;
    submitting.current = true;
    setApplying(true);
    setError(null);
    setNotice(null);
    try {
      await onConfirm(request, row);
      setNotice(`Сохранено и проверено: ${row.label}.`);
      setRequest({ ...request });
    } catch (cause) {
      setResult(null);
      setError(formatApiError(cause));
    } finally {
      submitting.current = false;
      setApplying(false);
    }
  }

  return (
    <fieldset disabled={disabled || applying} className={styles.alfaImport}>
      <legend>Выписка за {monthLabel}</legend>
      <Field label="Выписка Альфы (CSV)" htmlFor={formId}>
        <Input
          className={styles.alfaFile}
          id={formId}
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => void selectFile(e.currentTarget.files?.[0])}
        />
      </Field>
      {reading && <p role="status">Читаем файл…</p>}
      {request && (
        <label className={styles.alfaCoverage}>
          <input
            type="checkbox"
            checked={request.full_month}
            onChange={(e) => change({ ...request, full_month: e.target.checked })}
          />{" "}
          Выписка охватывает весь месяц
        </label>
      )}
      {error && (
        <div role="alert" className="inline-alert inline-alert--error">
          {error}{" "}
          {request && (
            <Button type="button" onClick={() => change({ ...request })}>
              Перечитать предложение
            </Button>
          )}
        </div>
      )}
      {notice && (
        <p role="status" className="inline-alert inline-alert--ok">
          {notice}
        </p>
      )}
      {request && !data && !error && <p role="status">Сверяем выписку с депозитами…</p>}
      {data && request && (
        <>
          <p className={styles.hint}>
            Остаток рассчитывается от прошлого месяца по движениям выписки. Выберите счёт и
            подтвердите его отдельно.
          </p>
          {data.rows.length === 0 && <p>В выписке нет подходящих операций за этот месяц.</p>}
          {data.rows.map((row) => (
            <section key={row.source_key} className={styles.alfaRow} aria-label={row.label}>
              <h4>{row.label}</h4>
              <small>
                Операций: {row.count}
                {row.first_date && row.last_date && (
                  <>
                    {" "}
                    · {formatDate(row.first_date)} — {formatDate(row.last_date)}
                  </>
                )}
              </small>
              <Field label="Счёт в Finance" htmlFor={formId + row.source_key}>
                <Select
                  disabled={row.mapped}
                  id={formId + row.source_key}
                  value={row.account_id ?? ""}
                  onChange={(e) => {
                    const bindings = { ...request.bindings };
                    if (e.target.value) bindings[row.source_key] = Number(e.target.value);
                    else delete bindings[row.source_key];
                    change({ ...request, bindings });
                  }}
                >
                  <option value="">Выберите накопительный счёт</option>
                  {data.accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              {row.account_id !== null && (
                <Table aria-label="Сравнение значений">
                  <thead>
                    <tr>
                      <Th>Показатель</Th>
                      <Th numeric>В месяце</Th>
                      <Th numeric>Предложение</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {fields.map(([key, label]) => {
                      const display = (value: string | null) =>
                        key === "annual_rate"
                          ? formatPercent(value, { digits: 2 })
                          : formatMoney(value);
                      return (
                        <tr key={key}>
                          <Td>{label}</Td>
                          <Td numeric>{display(row.current[key])}</Td>
                          <Td numeric>
                            {row.proposed[key] === null
                              ? "Без изменения"
                              : display(row.proposed[key])}
                          </Td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
              )}
              {row.difference !== null && (
                <p className={styles.alfaDifference}>
                  Разница с текущим остатком{" "}
                  <strong className="num">{formatMoney(row.difference)}</strong>
                </p>
              )}
              {row.messages.map((message) => (
                <p className={styles.hint} key={message}>
                  {message}
                </p>
              ))}
              {row.account_id !== null && (
                <Button
                  type="button"
                  variant={data.rows.length === 1 && row.token ? "primary" : "secondary"}
                  disabled={!row.token}
                  onClick={() => void confirm(row)}
                >
                  Подтвердить по счёту
                </Button>
              )}
            </section>
          ))}
        </>
      )}
    </fieldset>
  );
}
