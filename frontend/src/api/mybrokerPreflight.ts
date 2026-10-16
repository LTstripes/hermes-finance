import { apiMultipart } from "./client";

export type OriginalContext = {
  coveredFrom: string;
  coveredTo: string;
  accountId: number | null;
};
const record = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const strings = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((s) => typeof s === "string" && s.trim().length > 0);
const positiveId = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const isoDate = (v: unknown): v is string =>
  typeof v === "string" &&
  /^\d{4}-\d{2}-\d{2}$/.test(v) &&
  !Number.isNaN(Date.parse(v)) &&
  new Date(v).toISOString().slice(0, 10) === v;

// Validate only the discovery boundary. Aggregate financial/instrument readiness
// is deliberately not an eligibility gate for the ordinary month Preview.
export function originalContext(value: unknown, filename: string): OriginalContext {
  const invalid = () =>
    new Error("Ответ проверки оригинала не подтверждён. Выбери счёт вручную и повтори Preview.");
  if (
    !record(value) ||
    value.contract !== "mybroker-batch-preflight-v1" ||
    value.kind !== "preflight" ||
    !Array.isArray(value.documents) ||
    value.documents.length !== 1
  )
    throw invalid();
  const entry: unknown = value.documents[0];
  if (
    !record(entry) ||
    entry.filename !== filename ||
    entry.upload_count !== 1 ||
    !record(entry.document) ||
    !record(entry.mappings) ||
    !strings(entry.binder_blockers) ||
    !strings(entry.mappings.conflicts) ||
    !Array.isArray(entry.mappings.accounts)
  )
    throw invalid();
  const doc = entry.document;
  if (
    !isoDate(doc.covered_from) ||
    !isoDate(doc.covered_to) ||
    doc.covered_from > doc.covered_to ||
    typeof doc.filename_account !== "string" ||
    !doc.filename_account.trim() ||
    !strings(doc.source_accounts) ||
    !doc.source_accounts.length ||
    new Set(doc.source_accounts).size !== doc.source_accounts.length ||
    !doc.source_accounts.includes(doc.filename_account)
  )
    throw invalid();
  const sourceAccounts = doc.source_accounts;
  const aliases = entry.mappings.accounts;
  if (
    aliases.length !== doc.source_accounts.length ||
    aliases.some(
      (a: unknown) =>
        !record(a) || typeof a.identity !== "string" || !sourceAccounts.includes(a.identity),
    ) ||
    new Set(aliases.map((a) => a.identity)).size !== aliases.length
  )
    throw invalid();
  const conflict =
    entry.binder_blockers.length > 0 ||
    entry.mappings.conflicts.some((c) =>
      /^(account_|source_account_|revoked_account_|duplicate_account_)/.test(c),
    );
  const known =
    !conflict &&
    aliases.every(
      (a) =>
        a.action === "reuse" &&
        a.state === "ready" &&
        positiveId(a.mapping_id) &&
        positiveId(a.hermes_id),
    ) &&
    new Set(aliases.map((a) => a.hermes_id)).size === 1;
  return {
    coveredFrom: doc.covered_from,
    coveredTo: doc.covered_to,
    accountId: known ? (aliases[0].hermes_id as number) : null,
  };
}

export async function previewOriginalContext(file: File, signal?: AbortSignal) {
  const form = new FormData();
  form.append("files", file, file.name);
  return originalContext(
    await apiMultipart<unknown>("/api/mybroker-preflight/preview", form, signal),
    file.name,
  );
}
