import { useEffect, useRef, useState } from "react";
import { ApiClientError, formatApiError } from "../api/client";
import {
  confirmInvestmentReport,
  getInvestmentProofRequest,
  getInvestmentReports,
  type InvestmentProofAck,
  previewSourceReports,
  type SourceReportPreview,
} from "../api/sourceReportPreview";
import { SourceReportResults } from "./SourceReportResults";
import { Button, Field } from "./ui";

const pendingKey = "hermes-investment-proof-pending-v1";
export function SourceReportPreviewPanel({
  xmlFiles,
  onPendingChange,
  onSaved,
}: {
  xmlFiles: File[];
  onPendingChange?: (pending: boolean) => void;
  onSaved?: () => void;
}) {
  const xml = xmlFiles;
  const [pdf, setPdf] = useState<File | null>(null);
  const [fromZero, setFromZero] = useState(false);
  const [result, setResult] = useState<SourceReportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ request_id: string; preview_digest: string } | null>(
    () => {
      try {
        return JSON.parse(sessionStorage.getItem(pendingKey) ?? "null");
      } catch {
        return null;
      }
    },
  );
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [saved, setSaved] = useState(false);
  const saving = useRef(false);
  useEffect(() => {
    onPendingChange?.(pending !== null);
  }, [pending, onPendingChange]);
  function hold(value: typeof pending) {
    if (value) sessionStorage.setItem(pendingKey, JSON.stringify(value));
    else sessionStorage.removeItem(pendingKey);
    setPending(value);
  }
  async function acknowledged(ack: InvestmentProofAck, intent: NonNullable<typeof pending>) {
    if (
      ack.request_id !== intent.request_id ||
      ack.preview_digest !== intent.preview_digest ||
      ack.financial_authority !== "none" ||
      !ack.proof_ids.length
    )
      throw new Error(
        "Сохранение требует проверки квитанции и актуальности. Повторите чтение статуса.",
      );
    const readback = await getInvestmentReports();
    if (!ack.current) {
      hold(null);
      setResult(null);
      setError(
        "Сохранение подтверждено, но свидетельство уже устарело или заменено. Числа скрыты; повторите Preview оригиналов.",
      );
      onSaved?.();
      return;
    }
    if (
      !ack.proof_ids.every((id) =>
        readback.reports.some(
          (p) => p.proof_id === id && p.status === "current" && p.interval !== null,
        ),
      )
    )
      throw new Error(
        "Сохранено, но повторное чтение не подтвердило результат. Повторите чтение статуса.",
      );
    hold(null);
    setSaved(true);
    setResult(null);
    onSaved?.();
  }
  async function recover(intent = pending) {
    if (!intent || saving.current) return;
    saving.current = true;
    setError(null);
    try {
      await acknowledged(await getInvestmentProofRequest(intent.request_id), intent);
    } catch (cause) {
      if (
        cause instanceof ApiClientError &&
        cause.status === 404 &&
        cause.code === "investment_proof_request_not_found"
      ) {
        hold(null);
        setResult(null);
        setReplaceExisting(false);
        setError(
          "При чтении сохранённой записи запроса не найдено. Старый Preview сброшен; выполните новую явную проверку оригиналов. Это не отмена ранее отправленного запроса.",
        );
      } else setError(formatApiError(cause));
    } finally {
      saving.current = false;
    }
  }
  const initialRecovery = useRef(false);
  useEffect(() => {
    if (pending && !initialRecovery.current) {
      initialRecovery.current = true;
      void recover(pending);
    }
  });
  async function save() {
    const p = result?.persistence;
    if (
      !p?.available ||
      !p.form_token ||
      !p.preview_digest ||
      pending ||
      saving.current ||
      (p.replacements.length > 0 && !replaceExisting)
    )
      return;
    const intent = {
      request_id: crypto.randomUUID().replaceAll("-", ""),
      preview_digest: p.preview_digest,
    };
    hold(intent);
    saving.current = true;
    setError(null);
    try {
      await acknowledged(
        await confirmInvestmentReport({
          ...intent,
          form_token: p.form_token,
          replace_existing: replaceExisting,
        }),
        intent,
      );
    } catch (cause) {
      setError(formatApiError(cause));
      if (
        cause instanceof ApiClientError &&
        cause.status === 409 &&
        /(?:form_expired|preview_changed|dependencies_changed|replacement_not_confirmed|classification_conflict)$/.test(
          cause.message,
        )
      ) {
        hold(null);
        setResult(null);
      }
    } finally {
      saving.current = false;
    }
  }
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      generation.current++;
      request.current?.abort();
    },
    [],
  );
  useEffect(() => {
    // The shared XML input may select A -> B -> A while an earlier request resolves.
    void xmlFiles;
    generation.current++;
    request.current?.abort();
    setBusy(false);
    setResult(null);
    setError(null);
    setReplaceExisting(false);
    setSaved(false);
  }, [xmlFiles]);

  function invalidate() {
    generation.current++;
    request.current?.abort();
    setBusy(false);
    setResult(null);
    setError(null);
    setReplaceExisting(false);
    setSaved(false);
  }
  async function inspect() {
    if (!pdf || !xml.length || busy || pending) return;
    invalidate();
    const current = generation.current;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    try {
      const next = await previewSourceReports(xml, pdf, fromZero, controller.signal);
      if (current === generation.current) setResult(next);
    } catch (cause) {
      if (current === generation.current) setError(formatApiError(cause));
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  return (
    <details>
      <summary>Расшифровка купонов и дивидендов — PDF Альфы</summary>
      <p>
        Выбери XML нужных счетов и один общий инвестиционный PDF. Для всей истории нужны длинные
        XML; для месяца — XML месяца и PDF с той же датой окончания. Остальные счета PDF
        пропускаются.
      </p>
      <p>
        Используются последние выбранные XML:{" "}
        {xml.map((file) => file.name).join(", ") || "выбери их выше"}.
      </p>
      <Field htmlFor="source-return-pdf" label="Загрузить PDF Альфы">
        <input
          id="source-return-pdf"
          type="file"
          accept=".pdf,application/pdf"
          disabled={pending !== null}
          onChange={(e) => {
            invalidate();
            setPdf(e.target.files?.[0] ?? null);
          }}
        />
      </Field>
      <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input
          type="checkbox"
          style={{ width: "auto", margin: 0 }}
          checked={fromZero}
          disabled={pending !== null}
          onChange={(e) => {
            invalidate();
            setFromZero(e.target.checked);
          }}
        />{" "}
        XML содержит всю историю счёта с нулевых остатков до первых операций
      </label>
      <p>
        Preview сравнит историю с сохранёнными источниками. Выплаты повторно не создаются, CLOSED не
        меняются; закрывать старые месяцы для проверки истории не требуется. Результат этой проверки
        пока не сохраняется в финансовые данные.
      </p>
      <Button
        disabled={!pdf || !xml.length || xml.length > 8 || busy || pending !== null}
        onClick={() => void inspect()}
      >
        {busy ? "Проверяем…" : "Проверить XML и PDF"}
      </Button>
      {error && <p role="alert">{error}</p>}
      {pending && (
        <p role="status">
          Сохранение ещё не подтверждено. Повторять отправку нельзя.{" "}
          <Button onClick={() => void recover()}>Проверить статус сохранения</Button>
        </p>
      )}
      {saved && (
        <p role="status">
          PDF-связи сохранены и перечитаны. Доходность доступна после Reload, без повторных выплат и
          изменения CLOSED.
        </p>
      )}
      {result && <SourceReportResults result={result} />}
      {result?.persistence && (
        <>
          {result.persistence.replacements.length > 0 && (
            <label>
              <input
                type="checkbox"
                checked={replaceExisting}
                disabled={pending !== null}
                onChange={(e) => setReplaceExisting(e.target.checked)}
              />
              Подтверждаю замену только source-proof для показанных счетов и периодов:{" "}
              {result.persistence.replacements
                .map(
                  (p) => `${p.source_account}: ${p.covered_from} — ${p.covered_to}, #${p.proof_id}`,
                )
                .join("; ")}
              . Предыдущая запись останется в истории.
            </label>
          )}
          {result.persistence.available ? (
            <Button
              disabled={
                pending !== null || (result.persistence.replacements.length > 0 && !replaceExisting)
              }
              onClick={() => void save()}
            >
              Сохранить PDF-связи
            </Button>
          ) : (
            <p>
              Сохранение: {result.persistence.reason_codes.join(", ")}. Если XML ещё не сохранён,
              используйте существующую загрузку выше и повторите Preview.
            </p>
          )}
        </>
      )}
    </details>
  );
}
