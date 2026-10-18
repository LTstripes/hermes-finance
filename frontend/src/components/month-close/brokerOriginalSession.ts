import type { QueryClient } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useLayoutEffect, useSyncExternalStore } from "react";
import { ApiClientError, formatApiError } from "../../api/client";
import {
  applyBrokerMonth,
  readBrokerMonth,
  type BrokerMonthPreview,
  type BrokerMonthReadback,
  type InstrumentDecision,
  type PublicIdentityResult,
} from "../../api/brokerMonths";

// JSON object key order is not evidence. Preserve array order, exact strings,
// nulls and numbers while comparing the accepted payload independently.
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, canonical(item)]),
    );
  return value;
}
function sameEvidence(left: unknown, right: unknown) {
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

type Pending = {
  id: string;
  preview: BrokerMonthPreview;
  committed: BrokerMonthReadback | null;
  replayAllowed: boolean;
};
type Snapshot = {
  lookupConsent: boolean;
  publicResults: PublicIdentityResult[];
  decisions: InstrumentDecision[];
  epoch: number;
  monthId: number | null;
  accountId: string;
  file: File | null;
  pending: Pending | null;
  confirmed: BrokerMonthReadback | null;
  busy: boolean;
  error: string | null;
};

// One in-memory original per app/QueryClient lifetime. Raw bytes never enter the
// query cache, browser storage, or a reconstructed File from normalized JSON.
const sessions = new WeakMap<QueryClient, BrokerOriginalSession>();
export function brokerOriginalSession(client: QueryClient) {
  let session = sessions.get(client);
  if (!session) {
    session = new BrokerOriginalSession(client);
    sessions.set(client, session);
  }
  return session;
}

export function useBrokerOriginalSession() {
  const session = brokerOriginalSession(useQueryClient());
  return { session, original: useSyncExternalStore(session.subscribe, session.snapshot) };
}

// Call at the close page boundary too: a month can change while its source panel
// is absent/loading. A→B→A must still end the previous session.
export function useBrokerOriginalContext(monthId: number | null, closed: boolean) {
  const { session } = useBrokerOriginalSession();
  useLayoutEffect(() => session.context(monthId, closed), [session, monthId, closed]);
}

export class BrokerOriginalSession {
  private state: Snapshot = {
    lookupConsent: false,
    publicResults: [],
    decisions: [],
    epoch: 0,
    monthId: null,
    accountId: "",
    file: null,
    pending: null,
    confirmed: null,
    busy: false,
    error: null,
  };
  private listeners = new Set<() => void>();
  private refreshing = false;
  constructor(private client: QueryClient) {
    const dependencyKeys = ["accounts", "instruments", "broker-identity-mappings"];
    const fingerprints = new Map<string, string | undefined>(
      client
        .getQueryCache()
        .getAll()
        .filter((query) => dependencyKeys.includes(String(query.queryKey[0])))
        .map((query) => [query.queryHash, JSON.stringify(query.state.data)]),
    );
    client.getQueryCache().subscribe((event) => {
      const key = String(event.query.queryKey[0]);
      if (event.type === "removed" && key === "months") this.clear();
      // Observer notifications precede the success event. Only successful query
      // updates may advance the fingerprint used to detect dependency changes.
      if (event.type !== "updated") return;
      const previous = fingerprints.get(event.query.queryHash);
      const fingerprint = dependencyKeys.includes(key)
        ? JSON.stringify(event.query.state.data)
        : undefined;
      if (dependencyKeys.includes(key) && event.action.type === "success")
        fingerprints.set(event.query.queryHash, fingerprint);
      if (this.refreshing) return;
      if (
        dependencyKeys.includes(key) &&
        (event.action.type === "invalidate" ||
          (event.action.type === "success" &&
            (event.action.manual || (previous !== undefined && previous !== fingerprint))))
      )
        this.invalidate();
      if (event.action.type !== "success") return;
      const data = event.query.state.data;
      if (key === "months" && Array.isArray(data) && this.state.monthId != null) {
        const month = data.find((row) => row.id === this.state.monthId);
        if (month?.status !== "draft") this.clear();
      }
      if (key === "month-close-workflow" && data && typeof data === "object" && "month" in data) {
        const month = data.month as { id: number; status: string };
        if (month.id === this.state.monthId && month.status !== "draft") this.clear();
      }
      if (key === "broker-months" && Array.isArray(data) && this.state.confirmed) {
        const receipt = data.find((row) => row.request_id === this.state.confirmed?.request_id);
        if (!receipt || !this.matches(receipt, this.state.confirmed)) this.clear();
      }
    });
  }
  snapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  private update(patch: Partial<Snapshot>) {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }
  clear() {
    this.update({
      epoch: this.state.epoch + 1,
      lookupConsent: false,
      publicResults: [],
      decisions: [],
      file: null,
      accountId: "",
      pending: null,
      confirmed: null,
      busy: false,
      error: null,
    });
  }
  context(monthId: number | null, closed: boolean) {
    if (monthId !== this.state.monthId || closed) {
      this.clear();
      this.update({ monthId });
    }
  }
  select(file: File | null, monthId: number, accountId: string) {
    this.clear();
    this.update({ file, monthId, accountId });
  }
  consent(enabled: boolean) {
    this.update({ lookupConsent: enabled });
  }
  refreshPublic() {
    this.invalidate();
    this.update({ publicResults: [] });
  }
  publicMetadata(results: PublicIdentityResult[]) {
    const merged = new Map(this.state.publicResults.map((r) => [r.isin, r]));
    for (const result of results) merged.set(result.isin, result);
    this.update({ publicResults: [...merged.values()] });
  }
  decide(decisions: InstrumentDecision[]) {
    this.update({ decisions });
  }
  identify(accountId: string) {
    this.update({ accountId });
  }
  invalidate() {
    if (!this.state.file && !this.state.pending && !this.state.confirmed) return;
    this.update({
      epoch: this.state.epoch + 1,
      decisions: [],
      pending: null,
      confirmed: null,
      busy: false,
      error: "Источник или привязки изменились. Повтори Preview и заново проверь сводку.",
    });
  }
  private matches(value: BrokerMonthReadback, expected: BrokerMonthReadback) {
    return (
      value.contract_version === "broker_month_v1" &&
      value.status === "draft" &&
      value.request_id === expected.request_id &&
      value.reporting_month_id === expected.reporting_month_id &&
      value.account_id === expected.account_id &&
      value.confirmation_digest === expected.confirmation_digest &&
      Array.isArray(value.exceptions) &&
      value.accepted?.document != null &&
      sameEvidence(value.accepted, expected.accepted) &&
      // New blockers mean accepted authority changed. Existing incomplete-source
      // exceptions are allowed; aggregate readiness never becomes a Save gate.
      value.exceptions.every((code) => expected.exceptions.includes(code))
    );
  }
  private valid(value: BrokerMonthReadback, pending: Pending) {
    const plan = pending.preview;
    return (
      value.contract_version === "broker_month_v1" &&
      value.status === "draft" &&
      value.request_id === pending.id &&
      value.reporting_month_id === plan.reporting_month_id &&
      value.account_id === plan.account_id &&
      value.confirmation_digest === plan.confirmation_digest &&
      Array.isArray(value.exceptions) &&
      value.accepted?.document != null &&
      sameEvidence(value.accepted.document, plan.document)
    );
  }
  start(preview: BrokerMonthPreview, id: string) {
    if (
      this.state.busy ||
      this.state.pending ||
      !this.state.file ||
      !preview.can_apply ||
      preview.reporting_month_id !== this.state.monthId ||
      String(preview.account_id) !== this.state.accountId
    )
      return;
    this.update({
      pending: { id, preview, committed: null, replayAllowed: false },
      confirmed: null,
      error: null,
    });
    return this.send();
  }
  private async read(pending: Pending, epoch: number) {
    let persisted: BrokerMonthReadback;
    try {
      persisted = await readBrokerMonth(pending.id);
    } catch (e) {
      if (this.state.epoch === epoch && !pending.committed)
        this.update({
          pending: { ...pending, replayAllowed: e instanceof ApiClientError && e.status === 404 },
        });
      throw e;
    }
    if (this.state.epoch !== epoch) return;
    const invalidated =
      /^(source_projection_changed|source_authority_changed|accepted_mapping_changed|source_disposition_changed|instrument_metadata_changed|account_binding_changed|canonical_trade_projection_changed|broker_month_receipt_invalid)$/;
    if (persisted.status === "closed") {
      this.clear();
      await this.client.invalidateQueries();
      return;
    }
    const expectedExceptions = pending.committed?.exceptions ?? pending.preview.exceptions;
    if (
      persisted.exceptions?.some(
        (code) => invalidated.test(code) || !expectedExceptions.includes(code),
      )
    ) {
      this.invalidate();
      await this.client.invalidateQueries({
        predicate: (query) =>
          !["accounts", "instruments", "broker-identity-mappings"].includes(
            String(query.queryKey[0]),
          ),
      });
      return;
    }
    if (!pending.committed) this.update({ pending: { ...pending, replayAllowed: false } });
    if (
      !this.valid(persisted, pending) ||
      (pending.committed && !this.matches(persisted, pending.committed))
    )
      throw new Error("Независимое чтение не подтвердило сохранённый результат.");
    // Invalidation is synchronous; later refetches are independent current reads.
    this.refreshing = true;
    const catalogueKeys = ["accounts", "instruments", "broker-identity-mappings"];
    // Catalogue entries are stale after source Apply, but refetch on navigation;
    // do not confuse our own new aliases/instruments with an external edit.
    void this.client.invalidateQueries({
      predicate: (query) => catalogueKeys.includes(String(query.queryKey[0])),
      refetchType: "none",
    });
    const refresh = this.client.invalidateQueries({
      predicate: (query) => !catalogueKeys.includes(String(query.queryKey[0])),
    });
    this.refreshing = false;
    this.update({ confirmed: persisted, pending: null, error: null });
    await refresh;
  }
  async retryRead() {
    const { pending, epoch, busy } = this.state;
    if (!pending || busy) return;
    this.update({ busy: true, error: null });
    try {
      await this.read(pending, epoch);
    } catch (e) {
      if (this.state.epoch === epoch) this.update({ error: formatApiError(e) });
    } finally {
      if (this.state.epoch === epoch) this.update({ busy: false });
    }
  }
  post() {
    if (this.state.pending?.replayAllowed) return this.send();
  }
  private async send() {
    const { pending, file, epoch, busy } = this.state;
    if (!pending || pending.committed || !file || busy) return;
    this.update({ busy: true, error: null });
    try {
      let acknowledged = pending;
      try {
        const plan = pending.preview;
        const committed = await applyBrokerMonth(
          file,
          {
            reporting_month_id: plan.reporting_month_id,
            account_id: plan.account_id,
            ...(plan.instrument_decisions?.length
              ? { instrument_decisions: plan.instrument_decisions }
              : {}),
          },
          plan.confirmation_digest,
          pending.id,
          plan.account_bindings,
        );
        if (this.state.epoch !== epoch) return;
        if (!this.valid(committed, pending))
          throw new Error("Ответ сохранения не соответствует исходному запросу.");
        acknowledged = { ...pending, committed };
        this.update({ pending: acknowledged });
      } catch (e) {
        if (this.state.epoch !== epoch) return;
        if (
          (e instanceof ApiClientError && e.status >= 400 && e.status < 500) ||
          (e instanceof Error &&
            /^broker_month_(preview_stale|reconciliation_required|account_bindings_unconfirmed)$/.test(
              e.message,
            ))
        ) {
          this.invalidate();
          return;
        }
        // Unknown POST outcome: query the original key before offering an exact
        // same-key replay. Never claim server acknowledgement on this branch.
      }
      await this.read(acknowledged, epoch);
    } catch (e) {
      if (this.state.epoch === epoch) this.update({ error: formatApiError(e) });
    } finally {
      if (this.state.epoch === epoch) this.update({ busy: false });
    }
  }
  candidate(receipt: BrokerMonthReadback) {
    const { confirmed, file } = this.state;
    return confirmed && file && this.matches(receipt, confirmed) ? file : undefined;
  }
}
