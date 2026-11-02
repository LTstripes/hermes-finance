import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { listAccounts } from "../../api/accounts";
import {
  type BrokerSource,
  type BrokerSources,
  brokerFileIdentity,
  readBrokerSources,
  uploadBrokerSources,
} from "../../api/brokerSources";
import { listInstruments } from "../../api/instruments";
import { readSourceIntake, type SourceIntake } from "../../api/sourceIntake";
import type { ReportingMonth } from "../../api/types";
import { brokerSourceTitle } from "../../lib/ownerCopy";
import { confirmStatementApply } from "../../ui-v2/UiV2StatementImportSection";
import { SavedInvestmentReports } from "../SavedInvestmentReports";
import { SourceReportPreviewPanel } from "../SourceReportPreviewPanel";
import { StatementImportPanel } from "../StatementImportPanel";
import { ConfirmDialog } from "../ui";
import { brokerIntakeCopy as copy } from "./ownerCopy";
import styles from "./SourceIntakeUpload.module.css";

type Original = { file: File; document_sha256: string; filename_digest: string };
type Attempt = { originals: Original[]; requestId: string };
const matches = (item: BrokerSource, original: Original) =>
  item.document_sha256 === original.document_sha256 &&
  item.filename_digest === original.filename_digest;

export function BrokerSourcesIntake({
  month,
  disabled = false,
  reportXmlFiles,
  onXmlFilesChange,
  onSaved,
  onReview,
  onPendingChange,
  onDirtyChange,
}: {
  month: Pick<ReportingMonth, "id" | "year" | "month" | "status">;
  disabled?: boolean;
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
    enabled: pdf !== null,
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
          ? failed.map((row) => row.error?.message ?? copy.readFailed)
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
  const confirmationCount = (query.data?.confirmation_count ?? 0) + (retry?.originals.length ?? 0);
  const blocked = disabled || busy || applying || proofPending || !!uncertain || !!pdf;
  const slotLabel = (item: BrokerSource) =>
    item.kind === "income_pdf"
      ? copy.pdfSlot
      : copy.statement + (item.source_accounts.join(" / ") || copy.unknownAccount);
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

  return (
    <section aria-label={copy.title}>
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
      {query.isPending || query.isFetching || busy || uncertain ? (
        <p role="status">{copy.loading}</p>
      ) : query.isError ? (
        <p role="status">{copy.readFailed}</p>
      ) : query.data?.status === "empty" && !confirmationCount ? (
        <p>{copy.empty}</p>
      ) : (
        <p
          role="status"
          className={confirmationCount ? "inline-alert inline-alert--warn" : undefined}
        >
          {confirmationCount ? copy.confirm + confirmationCount : copy.ok}
        </p>
      )}
      {items.length > 0 && (
        <ul aria-label={copy.savedFiles}>
          {items.map((item) => (
            <li key={item.document_sha256}>
              <span>
                {slotLabel(item)}.{" "}
                {item.state === "needs_decision"
                  ? item.kind === "income_pdf"
                    ? copy.pdfDecision
                    : (brokerSourceTitle(item.exceptions[0]) ?? copy.states.needs_decision)
                  : copy.states[item.state]}
              </span>{" "}
              {item.state === "needs_decision" && (
                <>
                  <button type="button" disabled={blocked} onClick={() => review(item)}>
                    {copy.confirmAction}
                  </button>{" "}
                  <button type="button" disabled={blocked} onClick={() => review(item)}>
                    {copy.correctAction}
                  </button>
                </>
              )}
              {item.state === "file_saved" && (
                <button type="button" disabled={blocked} onClick={() => review(item)}>
                  {copy.reviewAction}
                </button>
              )}
            </li>
          ))}
        </ul>
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
      <details>
        <summary>{copy.investmentDetails}</summary>
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
