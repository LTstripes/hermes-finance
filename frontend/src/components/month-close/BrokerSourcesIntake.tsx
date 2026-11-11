import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { listAccounts } from "../../api/accounts";
import {
  type BrokerSource,
  type BrokerSourceIssue,
  type BrokerSources,
  brokerFileIdentity,
  readBrokerSources,
  uploadBrokerSources,
} from "../../api/brokerSources";
import { listInstruments } from "../../api/instruments";
import type { MonthChecklistStep } from "../../api/monthCloseWorkflow";
import { readSourceIntake, type SourceIntake } from "../../api/sourceIntake";
import type { CloseReadinessItem, ReportingMonth } from "../../api/types";
import { formatDate, formatMoney } from "../../lib/format";
import { brokerSourceTitle } from "../../lib/ownerCopy";
import { UNAVAILABLE_REASON } from "../../lib/reasonCopy";
import { MonthPanelTotal } from "../../ui-v2/MonthPanelTotal";
import workspaceStyles from "../../ui-v2/UiV2MonthWorkspace.module.css";
import { confirmStatementApply } from "../../ui-v2/UiV2StatementImportSection";
import { SavedInvestmentReports } from "../SavedInvestmentReports";
import { SourceReportPreviewPanel } from "../SourceReportPreviewPanel";
import { StatementImportPanel } from "../StatementImportPanel";
import { ConfirmDialog } from "../ui";
import { closedFindingCopy, brokerIntakeCopy as copy } from "./ownerCopy";
import styles from "./SourceIntakeUpload.module.css";

type Original = { file: File; document_sha256: string; filename_digest: string };
type Attempt = { originals: Original[]; requestId: string };
const matches = (item: BrokerSource, original: Original) =>
  item.document_sha256 === original.document_sha256 &&
  item.filename_digest === original.filename_digest;

function countText(count: number, forms: [string, string, string]): string {
  const form = new Intl.PluralRules("ru").select(count);
  return `${count} ${forms[form === "one" ? 0 : form === "few" ? 1 : 2]}`;
}

function Issue({ issue }: { issue: BrokerSourceIssue }) {
  const message = brokerSourceTitle(issue.code);
  return (
    <li>
      {(issue.name || issue.isin) && <strong>{issue.name || issue.isin}. </strong>}
      {issue.source_account && `Счёт ${issue.source_account}. `}
      {issue.date && `${formatDate(issue.date.slice(0, 10))}. `}
      {issue.section === "money"
        ? "Денежная операция. "
        : issue.section === "trades"
          ? "Сделка. "
          : ""}
      {issue.quantity != null && `Количество: ${issue.quantity}. `}
      {issue.amount != null &&
        `Сумма: ${formatMoney(issue.amount, { currency: issue.currency ?? "валюта неизвестна" })}. `}
      {issue.code === "source_intake_receipt_authority_changed"
        ? "Сохранённое решение больше не соответствует данным. Сверь изменения перед новым подтверждением."
        : issue.code === "5_UFSR_unsupported"
          ? "Служебный раздел выписки не удалось разобрать. Сверь исходный файл."
          : message === UNAVAILABLE_REASON
            ? "Не удалось однозначно разобрать данные. Открой их и сверь с выпиской."
            : message}
    </li>
  );
}

export function BrokerSourcesIntake({
  month,
  disabled = false,
  step,
  accountByIntake,
  children,
  detailsOpen = false,
  readinessRemarks = [],
  reportXmlFiles,
  onXmlFilesChange,
  onSaved,
  onReview,
  onPendingChange,
  onDirtyChange,
}: {
  month: Pick<ReportingMonth, "id" | "year" | "month" | "status">;
  disabled?: boolean;
  step?: MonthChecklistStep;
  accountByIntake?: Record<number, number | null>;
  children?: ReactNode;
  detailsOpen?: boolean;
  readinessRemarks?: CloseReadinessItem[];
  reportXmlFiles?: File[];
  onXmlFilesChange?: (files: File[]) => void;
  onSaved: (file: File, intake: SourceIntake) => void;
  onReview: (id: number) => void;
  onPendingChange?: (pending: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const client = useQueryClient();
  const mounted = useRef(true);
  const running = useRef(false);
  const [showAllIssues, setShowAllIssues] = useState(false);
  const [busy, setBusy] = useState(false);
  const [proofPending, setProofPending] = useState(false);
  const [xmlFiles, setXmlFiles] = useState<File[]>([]);
  const [applying, setApplying] = useState(false);
  const [uncertain, setUncertain] = useState<Attempt | null>(null);
  const [retry, setRetry] = useState<Attempt | null>(null);
  const [messages, setMessages] = useState<string[]>([]);
  const [finishPdf, setFinishPdf] = useState(false);
  const [pdf, setPdf] = useState<{ file: File; key: number } | null>(null);
  const originals = useRef<Original[]>([]);
  const query = useQuery({
    queryKey: ["broker-sources", month.id],
    queryFn: async ({ signal }) => {
      const result = await readBrokerSources(month.id, signal);
      if (result.reporting_month_id !== month.id || !Array.isArray(result.items))
        throw new Error(copy.readFailed);
      return result;
    },
  });
  const accounts = useQuery({
    queryKey: ["broker-source-pdf-accounts", month.id],
    queryFn: ({ signal }) => listAccounts(signal),
    enabled: true,
  });
  const instruments = useQuery({
    queryKey: ["broker-source-pdf-instruments", month.id],
    queryFn: ({ signal }) => listInstruments({ active: true }, signal),
    enabled: pdf !== null,
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    onPendingChange?.(busy || applying || proofPending || uncertain !== null);
    return () => onPendingChange?.(false);
  }, [busy, applying, proofPending, uncertain, onPendingChange]);
  useEffect(() => {
    onDirtyChange?.(pdf !== null);
    return () => onDirtyChange?.(false);
  }, [pdf, onDirtyChange]);

  async function retain(result: BrokerSources, attempt: Attempt) {
    if (result.reporting_month_id !== month.id) throw new Error(copy.readFailed);
    for (const original of attempt.originals) {
      const item = result.items.find((value) => matches(value, original));
      if (!item) continue;
      if (item.intake_id !== null) {
        const intake = await readSourceIntake(item.intake_id);
        if (intake.document_sha256 !== item.document_sha256 || intake.head_seq < item.head_seq)
          throw new Error(copy.readFailed);
        if (!mounted.current) return;
        onSaved(original.file, intake);
      }
      originals.current = [
        ...originals.current.filter((value) => value.document_sha256 !== original.document_sha256),
        original,
      ];
    }
    if (!mounted.current) return;
    const savedXml = attempt.originals
      .filter((original) =>
        result.items.some((item) => item.kind === "mybroker_xml" && matches(item, original)),
      )
      .map((original) => original.file);
    if (savedXml.length) {
      setXmlFiles(savedXml);
      onXmlFilesChange?.(savedXml);
    }
    client.setQueryData(["broker-sources", month.id], result);
    await client.invalidateQueries({ queryKey: ["source-intakes"] });
  }
  async function submit(attempt: Attempt) {
    if (running.current || disabled || proofPending || month.status === "closed" || pdf) return;
    running.current = true;
    setBusy(true);
    setMessages([]);
    try {
      const ack = await uploadBrokerSources(
        month.id,
        attempt.originals.map((value) => value.file),
        attempt.requestId,
      );
      if (ack.reporting_month_id !== month.id || ack.results.length !== attempt.originals.length)
        throw new Error(copy.readFailed);
      const result = await readBrokerSources(month.id);
      for (const row of ack.results) {
        const original = attempt.originals[row.index];
        if (!original || (row.item && !result.items.some((value) => matches(value, original))))
          throw new Error(copy.readFailed);
      }
      await retain(result, attempt);
      if (!mounted.current) return;
      const failed = ack.results.filter((row) => row.error);
      setRetry(
        failed.length
          ? { ...attempt, originals: failed.map((row) => attempt.originals[row.index]) }
          : null,
      );
      setMessages(
        failed.length
          ? failed.map(
              (row) =>
                `${attempt.originals[row.index].file.name}: ${row.error?.message ?? copy.readFailed}`,
            )
          : [ack.results.some((row) => row.duplicate) ? copy.duplicate : copy.saved],
      );
      setUncertain(null);
    } catch {
      if (mounted.current) {
        setUncertain(attempt);
        setMessages([copy.uncertain]);
      }
    } finally {
      running.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function recover() {
    if (!uncertain || running.current) return;
    running.current = true;
    setBusy(true);
    try {
      const result = await readBrokerSources(month.id);
      await retain(result, uncertain);
      if (!mounted.current) return;
      const missing = uncertain.originals.filter(
        (original) => !result.items.some((item) => matches(item, original)),
      );
      setRetry(missing.length ? { ...uncertain, originals: missing } : null);
      setUncertain(null);
      setMessages([missing.length ? copy.missing : copy.recovered]);
    } catch {
      if (mounted.current) setMessages([copy.readFailed]);
    } finally {
      running.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function choose(files: File[]) {
    if (
      !files.length ||
      running.current ||
      disabled ||
      proofPending ||
      uncertain ||
      pdf ||
      month.status === "closed"
    )
      return;
    // Digesting is included in the pending lifetime; a second drop cannot race it.
    running.current = true;
    setBusy(true);
    try {
      const selected = await Promise.all(
        files.map(async (file) => ({ file, ...(await brokerFileIdentity(file)) })),
      );
      if (!mounted.current) return;
      running.current = false;
      await submit({ originals: selected, requestId: crypto.randomUUID() });
    } catch {
      if (mounted.current) setMessages([copy.fileReadFailed]);
    } finally {
      running.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  const items = !query.isError && !query.isFetching ? (query.data?.items ?? []) : [];
  const confirmationCount = query.data?.confirmation_count ?? 0;
  const blocked = disabled || busy || applying || proofPending || !!uncertain || !!pdf;
  const slotLabel = (item: BrokerSource) =>
    item.kind === "income_pdf"
      ? copy.pdfSlot
      : ((item.intake_id == null
          ? undefined
          : accounts.data?.find((account) => account.id === accountByIntake?.[item.intake_id ?? -1])
              ?.name) ?? "Счёт не сопоставлен");
  function review(item: BrokerSource) {
    if (blocked) return;
    if (item.intake_id !== null) {
      onReview(item.intake_id);
      return;
    }
    const original = originals.current.find((value) => matches(item, value));
    if (!original) {
      setMessages([copy.reselectPdf]);
      return;
    }
    setPdf({ file: original.file, key: Date.now() });
  }

  const fileIssues = items.flatMap((item) =>
    (item.review_issues ?? item.exceptions.map((code) => ({ code }))).map((issue, index) => ({
      issue,
      key: `${item.document_sha256}:${index}`,
      label: slotLabel(item),
    })),
  );
  const accountCount = new Set(items.flatMap((item) => item.source_accounts)).size;
  const remarkRows = [
    ...fileIssues.map(({ issue, key, label }) => (
      <Issue
        key={key}
        issue={{ ...issue, source_account: label === "Счёт не сопоставлен" ? null : label }}
      />
    )),
    ...readinessRemarks.map((item) => {
      const reason = brokerSourceTitle(item.code);
      // This is the existing account-prefixed broker-readiness message, not a
      // new account resolver or readiness decision. Keep unknown copy intact.
      const account =
        /^(.*): .*\. Проверь подробности в разделе «Месяц → Брокерские выписки»\.$/.exec(
          item.message,
        )?.[1];
      const message =
        account && reason !== UNAVAILABLE_REASON
          ? `${account}: ${reason}`
          : closedFindingCopy(item.message) || reason;
      return (
        <li key={`readiness:${item.code}:${item.message}:${JSON.stringify(item.context)}`}>
          {message}
        </li>
      );
    }),
  ];
  return (
    <section aria-label={copy.title}>
      <MonthPanelTotal
        value={
          query.isPending || query.isFetching || query.isError
            ? "—"
            : `${countText(accountCount, ["счёт", "счёта", "счетов"])} · ${countText(items.length, ["файл", "файла", "файлов"])}`
        }
      />
      {month.status !== "closed" && (
        <fieldset
          disabled={blocked}
          className={styles.upload}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            if (!blocked) void choose(Array.from(event.dataTransfer.files));
          }}
        >
          <legend>{copy.drop}</legend>
          <label>
            {copy.choose}
            <input
              type="file"
              multiple
              accept=".xml,.pdf,application/xml,application/pdf"
              aria-label={copy.choose}
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                event.target.value = "";
                void choose(files);
              }}
            />
          </label>
          <ul aria-label={copy.slots}>
            <li>{copy.xmlSlot1}</li>
            <li>{copy.xmlSlot2}</li>
            <li>{copy.pdfSlot}</li>
          </ul>
        </fieldset>
      )}
      {(step?.attention_count ?? 0) > 0 || step?.state === "attention" ? (
        <p role="status" className="inline-alert inline-alert--warn">
          Есть замечания{step?.attention_count ? `: ${step.attention_count}` : ""}
        </p>
      ) : null}
      {query.isPending || query.isFetching || busy || uncertain ? (
        <p role="status">{copy.loading}</p>
      ) : query.isError ? (
        <p role="status">{copy.readFailed}</p>
      ) : (step?.attention_count ?? 0) > 0 || step?.state === "attention" ? null : query.data
          ?.status === "empty" &&
        !confirmationCount &&
        !retry ? (
        <p>{copy.empty}</p>
      ) : (
        <p
          role="status"
          className={confirmationCount || retry ? "inline-alert inline-alert--warn" : undefined}
        >
          {confirmationCount
            ? copy.confirm + confirmationCount
            : retry
              ? copy.partialUpload
              : copy.ok}
        </p>
      )}
      {confirmationCount > 0 && <p>{copy.partial}</p>}
      {items.length > 0 && (
        <ul aria-label={copy.savedFiles} className={workspaceStyles.statementFiles}>
          {items.map((item) => (
            <li key={item.document_sha256}>
              <div className={workspaceStyles.statementIdentity}>
                <strong>{slotLabel(item)}</strong>
                {item.kind !== "income_pdf" ? (
                  <small className={styles.contractNumber}>
                    Договор: {item.source_accounts.join(" / ") || copy.unknownAccount}
                  </small>
                ) : null}
              </div>
              <span>
                {formatDate(item.covered_from)} — {formatDate(item.covered_to)}
              </span>
              <span>
                {item.state === "file_saved"
                  ? "Файл сохранён"
                  : item.state === "needs_decision"
                    ? "Нужна проверка"
                    : "Данные приняты"}
              </span>
              {item.state === "needs_decision" && (
                <>
                  {item.kind === "income_pdf" ? <p>{copy.pdfDecision}</p> : null}
                  <button type="button" disabled={blocked} onClick={() => review(item)}>
                    {copy.reviewAction}
                  </button>
                </>
              )}
              <details>
                <summary>Подробнее о файле</summary>
                <p>
                  {formatDate(item.covered_from)} — {formatDate(item.covered_to)}
                </p>
                {!!item.information_codes?.length && <p>{copy.structureInfo}</p>}
                {item.state !== "needs_decision" && item.kind === "mybroker_xml" && (
                  <button type="button" disabled={blocked} onClick={() => review(item)}>
                    Просмотреть данные
                  </button>
                )}
                {!!item.exceptions.length && (
                  <details>
                    <summary>Диагностика файла</summary>
                    <code>{item.exceptions.join(", ")}</code>
                  </details>
                )}
              </details>
            </li>
          ))}
        </ul>
      )}
      {remarkRows.length > 0 && (
        <section aria-label="Замечания к выпискам">
          <h3>Замечания к выпискам: {remarkRows.length}</h3>
          <ul>{showAllIssues ? remarkRows : remarkRows.slice(0, 5)}</ul>
          {remarkRows.length > 5 && (
            <button type="button" onClick={() => setShowAllIssues((value) => !value)}>
              {showAllIssues ? "Свернуть замечания" : `Показать все ${remarkRows.length}`}
            </button>
          )}
        </section>
      )}
      {[...new Set(messages)].map((message) => (
        <p role="status" key={message}>
          {message}
        </p>
      ))}
      {uncertain && (
        <button type="button" disabled={busy} onClick={() => void recover()}>
          {copy.recover}
        </button>
      )}
      {retry && !uncertain && (
        <button type="button" disabled={blocked} onClick={() => void submit(retry)}>
          {copy.retry}
        </button>
      )}
      {query.isError && (
        <button type="button" onClick={() => void query.refetch()}>
          {copy.refresh}
        </button>
      )}
      <details open={detailsOpen || undefined}>
        <summary>Подробнее о разборе файлов</summary>
        <h3>{copy.investmentDetails}</h3>
        {month.status !== "closed" && (
          <fieldset disabled={busy || applying || disabled || !!pdf || !!uncertain}>
            <legend>{copy.investmentReport}</legend>
            <SourceReportPreviewPanel
              xmlFiles={reportXmlFiles ?? xmlFiles}
              onPendingChange={setProofPending}
              onSaved={() => {
                void client.invalidateQueries({ queryKey: ["source-returns"] });
                void client.invalidateQueries({ queryKey: ["returns"] });
              }}
            />
          </fieldset>
        )}
        <SavedInvestmentReports
          period={`${String(month.year)}-${String(month.month).padStart(2, "0")}`}
        />
        {children}
      </details>
      <ConfirmDialog
        open={finishPdf}
        title={copy.finishReview}
        description={copy.discardPdf}
        confirmLabel={copy.finishReview}
        cancelLabel={copy.stay}
        onCancel={() => setFinishPdf(false)}
        onConfirm={() => {
          setPdf(null);
          setFinishPdf(false);
        }}
      />
      {pdf && (
        <details open>
          <summary>{copy.pdfReview}</summary>
          <button type="button" disabled={applying} onClick={() => setFinishPdf(true)}>
            {copy.finishReview}
          </button>
          {accounts.isPending || instruments.isPending ? (
            <p>{copy.loading}</p>
          ) : accounts.isError || instruments.isError ? (
            <p role="status">{copy.readFailed}</p>
          ) : (
            <StatementImportPanel
              key={pdf.key}
              initialFile={pdf.file}
              accounts={accounts.data ?? []}
              instruments={instruments.data ?? []}
              readOnly={month.status === "closed"}
              targetPeriod={{ year: month.year, month: month.month }}
              onApplyingChange={setApplying}
              verifyApplied={(verification) => confirmStatementApply(month.id, verification)}
              onApplied={async () => {
                await client.invalidateQueries({ queryKey: ["broker-sources", month.id] });
              }}
            />
          )}
        </details>
      )}
    </section>
  );
}
