import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { listAccounts } from "../api/accounts";
import { formatApiError } from "../api/client";
import { createExpectedFlow, deleteExpectedFlow, listExpectedFlows } from "../api/expectedFlows";
import {
  createInvestmentFlow,
  deleteInvestmentFlow,
  listInvestmentFlows,
  updateInvestmentFlow,
} from "../api/investmentFlows";
import { listInstruments } from "../api/instruments";
import type { Account, ExpectedFlow, Instrument, InvestmentFlow } from "../api/types";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  LoadingState,
  OverflowMenu,
  OverflowMenuItem,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import { formatDate, formatMoney } from "../lib/format";
import {
  isManuallyEditableInvestmentFlow,
  isPassiveExpectedFlowType,
  isPassiveInvestmentFlowType,
  isRedemptionFlowType,
} from "../lib/flowTypes";
import { FLOW_TYPE_LABELS, SOURCE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub, sumMoneyAmounts } from "../lib/money";
import type { MonthEditorContext } from "./UiV2MonthEditorPage";

type ActualDraft = {
  account_id: string;
  instrument_id: string;
  flow_type: string;
  event_date: string;
  gross: string;
  tax: string;
  commission: string;
  net: string;
  source: string;
};

type ExpectedDraft = {
  account_id: string;
  instrument_id: string;
  flow_type: string;
  expected_date: string;
  gross: string;
  tax: string;
  net: string;
  source: string;
  forecast_version: string;
};

function emptyActual(date: string): ActualDraft {
  return {
    account_id: "",
    instrument_id: "",
    flow_type: "coupon",
    event_date: date,
    gross: "",
    tax: "0.00",
    commission: "0.00",
    net: "",
    source: "manual",
  };
}

function emptyExpected(date: string): ExpectedDraft {
  return {
    account_id: "",
    instrument_id: "",
    flow_type: "coupon",
    expected_date: date,
    gross: "",
    tax: "",
    net: "",
    source: "manual",
    forecast_version: "v1",
  };
}

/** Sentinel for completions retired by a month switch/unmount: never rendered as an error. */
const STALE = Symbol("stale-operation");

type Operation = {
  month: number;
  gen: number;
};

/**
 * V2P-08 leaf: manual payout fact + manual forecast for the exact editor month.
 * Calendar, provider preview/apply and statement import live in #566/#567 and are
 * intentionally not implemented here.
 *
 * Lifetime rules (Integrator B1/B2):
 * - Drafts belong to the exact month and are never reset by reads or by the
 *   forecast-version filter. Only a month change resets them.
 * - Every mutation captures {month, gen}; gen is retired on month change and
 *   unmount. A retired completion publishes nothing: no rows, no notices, no
 *   draft resets, no error. The server-side outcome stands and appears on the
 *   next load of its own month.
 * - Expected rows are installed only for the currently viewed version; a write
 *   for another version never renders as the current view.
 * - A successful write clears only the draft revision it submitted; newer input
 *   typed while the request was in flight is preserved with an honest notice.
 */
export function UiV2MonthPayoutsSection({ context }: { context: MonthEditorContext }) {
  const { month, readOnly, setDirty } = context;
  const monthId = month.id;
  const defaultDate = month.snapshot_date;

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [actual, setActual] = useState<InvestmentFlow[]>([]);
  const [expected, setExpected] = useState<ExpectedFlow[]>([]);
  const [forecastVersion, setForecastVersion] = useState("v1");
  const [versionInput, setVersionInput] = useState("v1");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expectedRefreshing, setExpectedRefreshing] = useState(false);
  const [expectedError, setExpectedError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actualDraft, setActualDraft] = useState<ActualDraft>(() => emptyActual(defaultDate));
  const [expectedDraft, setExpectedDraft] = useState<ExpectedDraft>(() =>
    emptyExpected(defaultDate),
  );
  const [actualDraftTouched, setActualDraftTouched] = useState(false);
  const [expectedDraftTouched, setExpectedDraftTouched] = useState(false);
  const [pendingDeleteActual, setPendingDeleteActual] = useState<InvestmentFlow | null>(null);
  const [pendingDeleteExpected, setPendingDeleteExpected] = useState<ExpectedFlow | null>(null);
  const [editingActualId, setEditingActualId] = useState<number | null>(null);
  const [editActual, setEditActual] = useState<ActualDraft | null>(null);

  const liveRef = useRef({ monthId, gen: 0 });
  const versionRef = useRef(forecastVersion);
  const defaultDateRef = useRef(defaultDate);
  defaultDateRef.current = defaultDate;
  const loadedKeyRef = useRef("");
  const readAllSeq = useRef(0);
  const readExpSeq = useRef(0);
  const actualRev = useRef(0);
  const expectedRev = useRef(0);
  const editRev = useRef(0);
  const localDirty = actualDraftTouched || expectedDraftTouched || editingActualId !== null;

  function captureOp(): Operation {
    return { month: monthId, gen: liveRef.current.gen };
  }

  function opLive(op: Operation): boolean {
    const live = liveRef.current;
    return op.month === live.monthId && op.gen === live.gen;
  }

  function touchActualDraft(patch: Partial<ActualDraft>) {
    actualRev.current += 1;
    setActualDraft((prev) => ({ ...prev, ...patch }));
    setActualDraftTouched(true);
  }

  function touchExpectedDraft(patch: Partial<ExpectedDraft>) {
    expectedRev.current += 1;
    setExpectedDraft((prev) => ({ ...prev, ...patch }));
    setExpectedDraftTouched(true);
  }

  function touchEdit(patch: Partial<ActualDraft>) {
    if (!editActual) return;
    editRev.current += 1;
    setEditActual({ ...editActual, ...patch });
  }

  useEffect(() => {
    setDirty("payouts", localDirty);
  }, [localDirty, setDirty]);

  useEffect(
    () => () => {
      liveRef.current = { monthId: liveRef.current.monthId, gen: liveRef.current.gen + 1 };
      setDirty("payouts", false);
    },
    [setDirty],
  );

  const loadAll = useCallback(
    async (signal?: AbortSignal) => {
      const target = monthId;
      const version = versionRef.current;
      const asOf = defaultDateRef.current;
      const seq = ++readAllSeq.current;
      const alive = () => liveRef.current.monthId === target && readAllSeq.current === seq;
      setLoading(true);
      setError(null);
      try {
        const [accs, instrs, flows, exp] = await Promise.all([
          listAccounts(signal),
          listInstruments({ active: true }, signal),
          listInvestmentFlows(target, undefined, signal),
          listExpectedFlows(target, version, signal),
        ]);
        if (signal?.aborted || !alive()) return;
        setAccounts(accs);
        setInstruments(instrs);
        setActual(flows.filter((row) => row.reporting_month_id === target));
        if (versionRef.current === version) {
          setExpected(exp.filter((row) => row.reporting_month_id === target));
        }
        const firstAccount = accs.find((a) => a.status === "active");
        const firstInstrument = instrs[0];
        setActualDraft((prev) => ({
          ...prev,
          account_id: prev.account_id || (firstAccount ? String(firstAccount.id) : ""),
          event_date: prev.event_date || asOf,
        }));
        setExpectedDraft((prev) => ({
          ...prev,
          account_id: prev.account_id || (firstAccount ? String(firstAccount.id) : ""),
          instrument_id: prev.instrument_id || (firstInstrument ? String(firstInstrument.id) : ""),
          expected_date: prev.expected_date || asOf,
          forecast_version: prev.forecast_version || version,
        }));
      } catch (err) {
        if (!signal?.aborted && alive()) setError(formatApiError(err));
      } finally {
        if (!signal?.aborted && alive()) setLoading(false);
      }
    },
    [monthId],
  );

  const loadExpected = useCallback(
    async (signal?: AbortSignal) => {
      const target = monthId;
      const version = versionRef.current;
      const seq = ++readExpSeq.current;
      const alive = () =>
        liveRef.current.monthId === target &&
        readExpSeq.current === seq &&
        versionRef.current === version;
      setExpectedRefreshing(true);
      setExpectedError(null);
      try {
        const exp = await listExpectedFlows(target, version, signal);
        if (signal?.aborted || !alive()) return;
        setExpected(exp.filter((row) => row.reporting_month_id === target));
      } catch (err) {
        if (signal?.aborted || !alive()) return;
        setExpected([]);
        setExpectedError(formatApiError(err));
      } finally {
        if (liveRef.current.monthId === target && readExpSeq.current === seq) {
          setExpectedRefreshing(false);
        }
      }
    },
    [monthId],
  );

  useEffect(() => {
    liveRef.current = { monthId, gen: liveRef.current.gen + 1 };
    readAllSeq.current += 1;
    readExpSeq.current += 1;
    // Marker (not the snapshot itself, so this effect stays month-identity-only):
    // the snapshot effect below adopts the current key without a second reload.
    loadedKeyRef.current = `${monthId}|*reset*`;
    setForecastVersion("v1");
    versionRef.current = "v1";
    setVersionInput("v1");
    setActualDraft(emptyActual(defaultDateRef.current));
    setExpectedDraft(emptyExpected(defaultDateRef.current));
    setActualDraftTouched(false);
    setExpectedDraftTouched(false);
    setEditingActualId(null);
    setEditActual(null);
    setActionError(null);
    setActionNotice(null);
    setExpectedError(null);
    setBusy(false);
    setPendingDeleteActual(null);
    setPendingDeleteExpected(null);
    const controller = new AbortController();
    void loadAll(controller.signal);
    return () => controller.abort();
  }, [loadAll, monthId]);

  useEffect(() => {
    const key = `${monthId}|${month.snapshot_date}`;
    if (loadedKeyRef.current === key || loadedKeyRef.current === `${monthId}|*reset*`) {
      loadedKeyRef.current = key;
      return;
    }
    loadedKeyRef.current = key;
    const controller = new AbortController();
    void loadAll(controller.signal);
    return () => controller.abort();
  }, [loadAll, month.snapshot_date, monthId]);

  useEffect(() => {
    versionRef.current = forecastVersion;
    const controller = new AbortController();
    void loadExpected(controller.signal);
    return () => controller.abort();
  }, [forecastVersion, loadExpected]);

  function commitVersion() {
    const next = versionInput.trim() || "v1";
    setVersionInput(next);
    if (next !== forecastVersion) setForecastVersion(next);
  }

  const accountName = useMemo(() => {
    const map = new Map(accounts.map((a) => [a.id, a.name]));
    return (id: number) => map.get(id) ?? `#${id}`;
  }, [accounts]);

  const instrumentName = useMemo(() => {
    const map = new Map(
      instruments.map((i) => [i.id, i.ticker ? `${i.name} (${i.ticker})` : i.name]),
    );
    return (id: number | null) => (id == null ? "—" : (map.get(id) ?? `#${id}`));
  }, [instruments]);

  const sortedActual = useMemo(
    () => [...actual].sort((a, b) => a.event_date.localeCompare(b.event_date) || a.id - b.id),
    [actual],
  );
  const sortedExpected = useMemo(
    () =>
      [...expected].sort((a, b) => a.expected_date.localeCompare(b.expected_date) || a.id - b.id),
    [expected],
  );

  const passiveActualTotal = useMemo(
    () =>
      sumMoneyAmounts(
        sortedActual
          .filter((f) => isPassiveInvestmentFlowType(f.flow_type))
          .map((f) => moneyAmount(f.net_amount)),
      ),
    [sortedActual],
  );
  const redemptionActualTotal = useMemo(
    () =>
      sumMoneyAmounts(
        sortedActual
          .filter((f) => isRedemptionFlowType(f.flow_type))
          .map((f) => moneyAmount(f.net_amount)),
      ),
    [sortedActual],
  );
  const expectedPassiveTotal = useMemo(
    () =>
      sumMoneyAmounts(
        sortedExpected
          .filter((f) => isPassiveExpectedFlowType(f.flow_type))
          .map((f) => moneyAmount(f.expected_net_amount)),
      ),
    [sortedExpected],
  );

  /** Reload the currently viewed month+version. Throws STALE when retired. */
  async function reloadCurrentView(op: Operation) {
    const flows = await listInvestmentFlows(op.month);
    if (!opLive(op)) throw STALE;
    setActual(flows.filter((row) => row.reporting_month_id === op.month));
    const version = versionRef.current;
    const exp = await listExpectedFlows(op.month, version);
    if (!opLive(op) || versionRef.current !== version) {
      const current = versionRef.current;
      const retry = await listExpectedFlows(op.month, current);
      if (!opLive(op) || versionRef.current !== current) throw STALE;
      setExpected(retry.filter((row) => row.reporting_month_id === op.month));
      return;
    }
    setExpected(exp.filter((row) => row.reporting_month_id === op.month));
  }

  async function handleCreateActual(event: FormEvent) {
    event.preventDefault();
    if (readOnly || busy) return;
    const op = captureOp();
    const target = monthId;
    const submittedRev = actualRev.current;
    setBusy(true);
    setActionError(null);
    setActionNotice(null);
    try {
      if (!normalizeMoneyInput(actualDraft.gross) || !normalizeMoneyInput(actualDraft.net)) {
        throw new Error("Укажи gross и net");
      }
      const accountId = Number(actualDraft.account_id);
      if (!Number.isInteger(accountId) || accountId < 1) throw new Error("Выбери счёт");
      const instrumentId = actualDraft.instrument_id ? Number(actualDraft.instrument_id) : null;
      const created = await createInvestmentFlow({
        reporting_month_id: target,
        account_id: accountId,
        flow_type: actualDraft.flow_type,
        event_date: actualDraft.event_date,
        gross_amount: rub(actualDraft.gross),
        tax_amount: rub(actualDraft.tax.trim() === "" ? "0" : actualDraft.tax),
        commission_amount: rub(actualDraft.commission.trim() === "" ? "0" : actualDraft.commission),
        net_amount: rub(actualDraft.net),
        instrument_id: instrumentId && instrumentId > 0 ? instrumentId : null,
        source: actualDraft.source.trim() || "manual",
      });
      if (!opLive(op)) return;
      if (created.reporting_month_id !== target)
        throw new Error("Ответ сохранения не подтверждает выбранный месяц.");
      await reloadCurrentView(op);
      const fresh = await listInvestmentFlows(target);
      if (!opLive(op)) return;
      if (!fresh.some((row) => row.id === created.id && row.reporting_month_id === target))
        throw new Error("Сохранение не подтверждено повторной загрузкой.");
      if (!opLive(op)) return;
      if (actualRev.current !== submittedRev) {
        setActionNotice("Выплата сохранена. Есть новые несохранённые правки.");
      } else {
        setActualDraft((prev) => ({ ...emptyActual(defaultDate), account_id: prev.account_id }));
        setActualDraftTouched(false);
        setActionNotice("Выплата сохранена и подтверждена.");
      }
    } catch (err) {
      if (err === STALE || !opLive(op)) return;
      setActionError(formatApiError(err));
    } finally {
      if (opLive(op)) setBusy(false);
    }
  }

  async function handleCreateExpected(event: FormEvent) {
    event.preventDefault();
    if (readOnly || busy) return;
    const op = captureOp();
    const target = monthId;
    const submittedRev = expectedRev.current;
    setBusy(true);
    setActionError(null);
    setActionNotice(null);
    try {
      if (!normalizeMoneyInput(expectedDraft.gross)) throw new Error("Укажи expected gross");
      const accountId = Number(expectedDraft.account_id);
      const instrumentId = Number(expectedDraft.instrument_id);
      if (!Number.isInteger(accountId) || accountId < 1) throw new Error("Выбери счёт");
      if (!Number.isInteger(instrumentId) || instrumentId < 1)
        throw new Error("Выбери инструмент для ожидаемой выплаты");
      const rowVersion = expectedDraft.forecast_version.trim() || versionRef.current;
      const created = await createExpectedFlow({
        reporting_month_id: target,
        account_id: accountId,
        instrument_id: instrumentId,
        flow_type: expectedDraft.flow_type,
        expected_date: expectedDraft.expected_date,
        gross_amount: rub(expectedDraft.gross),
        source: expectedDraft.source.trim() || "manual",
        source_as_of_date: defaultDate,
        forecast_version: rowVersion,
        ...(expectedDraft.tax.trim() === "" ? {} : { expected_tax_amount: rub(expectedDraft.tax) }),
        ...(expectedDraft.net.trim() === "" ? {} : { expected_net_amount: rub(expectedDraft.net) }),
      });
      if (!opLive(op)) return;
      if (created.reporting_month_id !== target)
        throw new Error("Ответ сохранения не подтверждает выбранный месяц.");
      if (created.is_confirmed) throw new Error("Прогноз не должен подтверждаться автоматически.");
      await reloadCurrentView(op);
      if (!opLive(op)) return;
      const viewingVersion = versionRef.current;
      const hasNewerInput = expectedRev.current !== submittedRev;
      if (rowVersion === viewingVersion) {
        const fresh = await listExpectedFlows(target, rowVersion);
        if (!opLive(op) || versionRef.current !== rowVersion) return;
        if (!fresh.some((row) => row.id === created.id && row.reporting_month_id === target))
          throw new Error("Сохранение не подтверждено повторной загрузкой.");
        if (!opLive(op)) return;
      }
      if (hasNewerInput) {
        setActionNotice(
          rowVersion === viewingVersion
            ? "Ожидаемая выплата сохранена. Есть новые несохранённые правки."
            : `Ожидаемая выплата сохранена (версия «${rowVersion}»). Есть новые несохранённые правки.`,
        );
      } else {
        setExpectedDraft((prev) => ({
          ...emptyExpected(defaultDate),
          account_id: prev.account_id,
          instrument_id: prev.instrument_id,
          forecast_version: prev.forecast_version,
        }));
        setExpectedDraftTouched(false);
        setActionNotice(
          rowVersion === viewingVersion
            ? "Ожидаемая выплата сохранена и подтверждена."
            : `Ожидаемая выплата сохранена (версия «${rowVersion}»).`,
        );
      }
    } catch (err) {
      if (err === STALE || !opLive(op)) return;
      setActionError(formatApiError(err));
    } finally {
      if (opLive(op)) setBusy(false);
    }
  }

  function startActualEdit(row: InvestmentFlow) {
    if (!isManuallyEditableInvestmentFlow(row.source, row.statement_link)) return;
    setEditingActualId(row.id);
    editRev.current += 1;
    setEditActual({
      account_id: String(row.account_id),
      instrument_id: row.instrument_id == null ? "" : String(row.instrument_id),
      flow_type: row.flow_type,
      event_date: row.event_date,
      gross: moneyAmount(row.gross_amount),
      tax: moneyAmount(row.tax_amount),
      commission: moneyAmount(row.commission_amount),
      net: moneyAmount(row.net_amount),
      source: row.source,
    });
  }

  async function handleSaveActualEdit() {
    if (editingActualId == null || !editActual || readOnly || busy) return;
    const op = captureOp();
    const target = monthId;
    const submittedRev = editRev.current;
    const current = actual.find((row) => row.id === editingActualId);
    if (!current || !isManuallyEditableInvestmentFlow(current.source, current.statement_link))
      return;
    setBusy(true);
    setActionError(null);
    setActionNotice(null);
    try {
      if (!normalizeMoneyInput(editActual.gross) || !normalizeMoneyInput(editActual.net)) {
        throw new Error("Укажи gross и net");
      }
      const instrumentId = editActual.instrument_id ? Number(editActual.instrument_id) : null;
      const sentInstrumentId = instrumentId && instrumentId > 0 ? instrumentId : null;
      const submitted = {
        flow_type: editActual.flow_type,
        event_date: editActual.event_date,
        gross: rub(editActual.gross).amount,
        tax: rub(editActual.tax.trim() === "" ? "0" : editActual.tax).amount,
        commission: rub(editActual.commission.trim() === "" ? "0" : editActual.commission).amount,
        net: rub(editActual.net).amount,
        instrument_id: sentInstrumentId ?? current.instrument_id,
      };
      const saved = await updateInvestmentFlow(editingActualId, {
        flow_type: submitted.flow_type,
        event_date: submitted.event_date,
        gross_amount: rub(editActual.gross),
        tax_amount: rub(editActual.tax.trim() === "" ? "0" : editActual.tax),
        commission_amount: rub(editActual.commission.trim() === "" ? "0" : editActual.commission),
        net_amount: rub(editActual.net),
        ...(sentInstrumentId ? { instrument_id: sentInstrumentId } : {}),
      });
      if (!opLive(op)) return;
      if (saved.reporting_month_id !== target)
        throw new Error("Ответ сохранения не подтверждает выбранный месяц.");
      await reloadCurrentView(op);
      const fresh = await listInvestmentFlows(target);
      if (!opLive(op)) return;
      const confirmed = fresh.find(
        (row) => row.id === editingActualId && row.reporting_month_id === target,
      );
      if (
        !confirmed ||
        confirmed.flow_type !== submitted.flow_type ||
        confirmed.event_date !== submitted.event_date ||
        moneyAmount(confirmed.gross_amount) !== submitted.gross ||
        moneyAmount(confirmed.tax_amount) !== submitted.tax ||
        moneyAmount(confirmed.commission_amount) !== submitted.commission ||
        moneyAmount(confirmed.net_amount) !== submitted.net ||
        confirmed.instrument_id !== submitted.instrument_id
      ) {
        throw new Error("Изменение не подтверждено повторной загрузкой.");
      }
      if (!opLive(op) || editRev.current !== submittedRev) return;
      setEditingActualId(null);
      setEditActual(null);
      setActionNotice("Выплата обновлена и подтверждена.");
    } catch (err) {
      if (err === STALE || !opLive(op)) return;
      setActionError(formatApiError(err));
    } finally {
      if (opLive(op)) setBusy(false);
    }
  }

  async function confirmDeleteActual() {
    if (!pendingDeleteActual || readOnly || busy) return;
    const op = captureOp();
    const target = monthId;
    const deletedId = pendingDeleteActual.id;
    setBusy(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await deleteInvestmentFlow(deletedId);
      if (!opLive(op)) return;
      await reloadCurrentView(op);
      const fresh = await listInvestmentFlows(target);
      if (!opLive(op)) return;
      if (fresh.some((row) => row.id === deletedId))
        throw new Error("Удаление не подтверждено повторной загрузкой.");
      if (!opLive(op)) return;
      setPendingDeleteActual(null);
      setActionNotice("Выплата удалена и подтверждена.");
    } catch (err) {
      if (err === STALE || !opLive(op)) return;
      setActionError(formatApiError(err));
      setPendingDeleteActual(null);
    } finally {
      if (opLive(op)) setBusy(false);
    }
  }

  async function confirmDeleteExpected() {
    if (!pendingDeleteExpected || readOnly || busy) return;
    const op = captureOp();
    const target = monthId;
    const version = versionRef.current;
    const deletedId = pendingDeleteExpected.id;
    setBusy(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await deleteExpectedFlow(deletedId);
      if (!opLive(op)) return;
      await reloadCurrentView(op);
      const fresh = await listExpectedFlows(target, version);
      if (!opLive(op) || versionRef.current !== version) return;
      if (fresh.some((row) => row.id === deletedId))
        throw new Error("Удаление не подтверждено повторной загрузкой.");
      if (!opLive(op)) return;
      setPendingDeleteExpected(null);
      setActionNotice("Ожидаемая выплата удалена и подтверждена.");
    } catch (err) {
      if (err === STALE || !opLive(op)) return;
      setActionError(formatApiError(err));
      setPendingDeleteExpected(null);
    } finally {
      if (opLive(op)) setBusy(false);
    }
  }

  if (loading) return <LoadingState description="Загружаем выплаты…" inline />;
  if (error) return <EmptyState description={error} inline title="Не удалось загрузить выплаты" />;

  return (
    <div className="stack-18">
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}
      {actionNotice ? <p role="status">{actionNotice}</p> : null}

      <Panel
        action={
          <Badge tone="draft">пассивный доход, нетто {formatMoney(passiveActualTotal)}</Badge>
        }
        label="Выплаты"
        title="Фактические потоки"
      >
        {sortedActual.length === 0 ? (
          <EmptyState
            description="Фактических купонов, дивидендов и процентов ещё нет."
            inline
            title="Пусто"
          />
        ) : (
          <Table className="month-flows-table">
            <thead>
              <tr>
                <Th>Дата</Th>
                <Th>Тип</Th>
                <Th>Счёт / инструмент</Th>
                <Th numeric>Брутто</Th>
                <Th numeric>Налог</Th>
                <Th numeric>Комиссия</Th>
                <Th numeric>Нетто</Th>
                <Th className="month-flows-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {sortedActual.map((row) => {
                const editing = editingActualId === row.id && editActual;
                const redemption = isRedemptionFlowType(row.flow_type);
                const passive = isPassiveInvestmentFlowType(row.flow_type);
                const manual = isManuallyEditableInvestmentFlow(row.source, row.statement_link);
                const instrument =
                  row.instrument_id == null
                    ? null
                    : instruments.find((item) => item.id === row.instrument_id);
                const instrumentPrimary = instrument
                  ? instrument.ticker
                    ? `${instrument.name} (${instrument.ticker})`
                    : instrument.name
                  : accountName(row.account_id);
                return (
                  <tr
                    className={redemption ? "row--muted" : passive ? "row--income" : undefined}
                    key={row.id}
                  >
                    <Td className="month-flows-table__date">
                      {editing ? (
                        <Input
                          aria-label="Дата события"
                          disabled={busy}
                          onChange={(e) => touchEdit({ event_date: e.target.value })}
                          type="date"
                          value={editActual.event_date}
                        />
                      ) : (
                        formatDate(row.event_date)
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <Select
                          aria-label="Тип потока"
                          disabled={busy}
                          onChange={(e) => touchEdit({ flow_type: e.target.value })}
                          value={editActual.flow_type}
                        >
                          <option value="coupon">Купон</option>
                          <option value="dividend">Дивиденды</option>
                          <option value="interest">Проценты</option>
                          <option value="redemption">Погашение</option>
                          <option value="commission">Комиссия</option>
                          <option value="tax">Налог</option>
                          <option value="other">Прочее</option>
                        </Select>
                      ) : (
                        <>
                          <span
                            className={redemption ? "badge badge--closed" : "badge badge--draft"}
                          >
                            {labelOf(FLOW_TYPE_LABELS, row.flow_type)}
                          </span>
                          {redemption ? (
                            <div className="muted tiny">не доход (погашение)</div>
                          ) : null}
                          {passive ? <div className="muted tiny">пассивный доход</div> : null}
                          {!manual ? (
                            <div className="muted tiny">
                              {labelOf(SOURCE_LABELS, row.source)} · не редактируется
                            </div>
                          ) : null}
                        </>
                      )}
                    </Td>
                    <Td>
                      {editing ? (
                        <>
                          <div>{accountName(row.account_id)}</div>
                          <Select
                            aria-label="Инструмент выплаты"
                            disabled={busy}
                            onChange={(e) => touchEdit({ instrument_id: e.target.value })}
                            value={editActual.instrument_id}
                          >
                            <option value="">—</option>
                            {instruments.map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.name}
                                {item.ticker ? ` (${item.ticker})` : ""}
                              </option>
                            ))}
                          </Select>
                        </>
                      ) : (
                        <div className="month-flows-table__party">
                          <strong>{instrumentPrimary || "—"}</strong>
                          <div className="muted tiny">
                            {instrument ? accountName(row.account_id) : "—"}
                          </div>
                        </div>
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Брутто"
                          className="input--money"
                          disabled={busy}
                          onChange={(e) => touchEdit({ gross: e.target.value })}
                          value={editActual.gross}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.gross_amount))
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Налог"
                          className="input--money"
                          disabled={busy}
                          onChange={(e) => touchEdit({ tax: e.target.value })}
                          value={editActual.tax}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.tax_amount))
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Комиссия"
                          className="input--money"
                          disabled={busy}
                          onChange={(e) => touchEdit({ commission: e.target.value })}
                          value={editActual.commission}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.commission_amount))
                      )}
                    </Td>
                    <Td numeric>
                      {editing ? (
                        <Input
                          aria-label="Нетто"
                          className="input--money"
                          disabled={busy}
                          onChange={(e) => touchEdit({ net: e.target.value })}
                          value={editActual.net}
                        />
                      ) : (
                        formatMoney(moneyAmount(row.net_amount))
                      )}
                    </Td>
                    <Td className="month-flows-table__actions">
                      <div className="row-actions">
                        {editing ? (
                          <>
                            <Button
                              disabled={busy || readOnly}
                              onClick={() => void handleSaveActualEdit()}
                              size="sm"
                              type="button"
                              variant="primary"
                            >
                              OK
                            </Button>
                            <Button
                              disabled={busy}
                              onClick={() => {
                                setEditingActualId(null);
                                setEditActual(null);
                              }}
                              size="sm"
                              type="button"
                            >
                              Отмена
                            </Button>
                          </>
                        ) : manual ? (
                          <OverflowMenu
                            label={`Действия для выплаты «${labelOf(FLOW_TYPE_LABELS, row.flow_type)}» от ${row.event_date}`}
                          >
                            <OverflowMenuItem
                              disabled={busy || readOnly}
                              onClick={() => startActualEdit(row)}
                            >
                              Изменить
                            </OverflowMenuItem>
                            <OverflowMenuItem
                              danger
                              disabled={busy || readOnly}
                              onClick={() => setPendingDeleteActual(row)}
                            >
                              Удалить
                            </OverflowMenuItem>
                          </OverflowMenu>
                        ) : (
                          <span className="muted tiny">чтение</span>
                        )}
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}

        <div className="totals-bar">
          <span>
            Пассивный доход (нетто): <strong>{formatMoney(passiveActualTotal)}</strong>
          </span>
          <span>
            Погашение (не доход): <strong>{formatMoney(redemptionActualTotal)}</strong>
          </span>
        </div>
        <details className="field-details">
          <summary>О классификации выплат</summary>
          <p>
            Погашение — возврат номинала, а не доход. Фактический процент по депозиту вводится в
            разделе активов.
          </p>
        </details>

        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={handleCreateActual}>
            <p className="panel__label section-form-label">Новая фактическая выплата</p>
            <div className="editor-grid">
              <Field htmlFor="payout-act-type" label="Тип потока">
                <Select
                  id="payout-act-type"
                  onChange={(e) => touchActualDraft({ flow_type: e.target.value })}
                  value={actualDraft.flow_type}
                >
                  <option value="coupon">Купон</option>
                  <option value="dividend">Дивиденды</option>
                  <option value="interest">Проценты</option>
                  <option value="redemption">Погашение</option>
                  <option value="commission">Комиссия</option>
                  <option value="tax">Налог</option>
                  <option value="other">Прочее</option>
                </Select>
              </Field>
              <Field htmlFor="payout-act-date" label="Дата события">
                <Input
                  id="payout-act-date"
                  onChange={(e) => touchActualDraft({ event_date: e.target.value })}
                  required
                  type="date"
                  value={actualDraft.event_date}
                />
              </Field>
              <Field htmlFor="payout-act-account" label="Счёт фактической выплаты">
                <Select
                  id="payout-act-account"
                  onChange={(e) => touchActualDraft({ account_id: e.target.value })}
                  required
                  value={actualDraft.account_id}
                >
                  <option value="">—</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field htmlFor="payout-act-instr" label="Инструмент (необязательно)">
                <Select
                  id="payout-act-instr"
                  onChange={(e) => touchActualDraft({ instrument_id: e.target.value })}
                  value={actualDraft.instrument_id}
                >
                  <option value="">—</option>
                  {instruments.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name}
                      {i.ticker ? ` (${i.ticker})` : ""}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field htmlFor="payout-act-gross" label="Брутто">
                <Input
                  className="input--money"
                  id="payout-act-gross"
                  onChange={(e) => touchActualDraft({ gross: e.target.value })}
                  required
                  value={actualDraft.gross}
                />
              </Field>
              <Field htmlFor="payout-act-tax" label="Налог">
                <Input
                  className="input--money"
                  id="payout-act-tax"
                  onChange={(e) => touchActualDraft({ tax: e.target.value })}
                  value={actualDraft.tax}
                />
              </Field>
              <Field htmlFor="payout-act-comm" label="Комиссия">
                <Input
                  className="input--money"
                  id="payout-act-comm"
                  onChange={(e) => touchActualDraft({ commission: e.target.value })}
                  value={actualDraft.commission}
                />
              </Field>
              <Field htmlFor="payout-act-net" label="Нетто">
                <Input
                  className="input--money"
                  id="payout-act-net"
                  onChange={(e) => touchActualDraft({ net: e.target.value })}
                  required
                  value={actualDraft.net}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить выплату
            </Button>
          </form>
        ) : null}
      </Panel>

      <Panel
        action={<Badge>ручные ожидаемые: {formatMoney(expectedPassiveTotal)}</Badge>}
        label="Прогноз"
        title="Ручные ожидаемые выплаты"
      >
        <p className="muted">
          Ручные ожидаемые выплаты — только план для потоков без другого источника. Прогноз не
          подтверждается автоматически и не смешивается с фактом.
        </p>
        <div className="editor-grid filter-grid">
          <Field htmlFor="payout-exp-version" label="Версия прогноза">
            <Input
              id="payout-exp-version"
              onBlur={() => commitVersion()}
              onChange={(e) => setVersionInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitVersion();
                }
              }}
              value={versionInput}
            />
          </Field>
          <Button disabled={expectedRefreshing} onClick={() => commitVersion()} type="button">
            Показать
          </Button>
        </div>
        {expectedRefreshing ? <p role="status">Обновляем прогноз…</p> : null}
        {expectedError ? (
          <div className="inline-alert inline-alert--warn" role="alert">
            Прогноз временно недоступен: {expectedError}
          </div>
        ) : null}

        {sortedExpected.length === 0 && !expectedError ? (
          <EmptyState
            description={`Нет ожидаемых выплат для версии «${forecastVersion}».`}
            inline
            title="Пусто"
          />
        ) : null}
        {sortedExpected.length > 0 ? (
          <Table className="month-flows-table">
            <thead>
              <tr>
                <Th>Дата</Th>
                <Th>Тип</Th>
                <Th>Инструмент</Th>
                <Th numeric>Брутто</Th>
                <Th numeric>Прогноз налога</Th>
                <Th numeric>Прогноз нетто</Th>
                <Th>Статус</Th>
                <Th className="month-flows-table__actions">Действия</Th>
              </tr>
            </thead>
            <tbody>
              {sortedExpected.map((row) => {
                const redemption = isRedemptionFlowType(row.flow_type);
                return (
                  <tr className={redemption ? "row--muted" : "row--income"} key={row.id}>
                    <Td>{formatDate(row.expected_date)}</Td>
                    <Td>
                      <span className={redemption ? "badge badge--closed" : "badge badge--draft"}>
                        {labelOf(FLOW_TYPE_LABELS, row.flow_type)}
                      </span>
                      {redemption ? <div className="muted tiny">погашение ≠ доход</div> : null}
                    </Td>
                    <Td>{instrumentName(row.instrument_id)}</Td>
                    <Td numeric>{formatMoney(moneyAmount(row.gross_amount))}</Td>
                    <Td numeric>
                      {row.expected_tax_amount
                        ? formatMoney(moneyAmount(row.expected_tax_amount))
                        : "—"}
                    </Td>
                    <Td numeric>{formatMoney(moneyAmount(row.expected_net_amount))}</Td>
                    <Td>
                      <div className="muted tiny">
                        {row.is_confirmed ? "подтверждено" : "план"}
                        {row.is_approximate ? " · примерно" : ""}
                      </div>
                      <div className="muted tiny">{row.forecast_version}</div>
                    </Td>
                    <Td className="month-flows-table__actions">
                      <OverflowMenu
                        label={`Действия для ожидаемой выплаты «${labelOf(FLOW_TYPE_LABELS, row.flow_type)}» на ${row.expected_date}`}
                      >
                        <OverflowMenuItem
                          danger
                          disabled={busy || readOnly}
                          onClick={() => setPendingDeleteExpected(row)}
                        >
                          Удалить
                        </OverflowMenuItem>
                      </OverflowMenu>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        ) : null}

        <div className="totals-bar">
          <span>
            Ручные ожидаемые (нетто): <strong>{formatMoney(expectedPassiveTotal)}</strong>
          </span>
        </div>

        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={handleCreateExpected}>
            <p className="panel__label section-form-label">Новая ожидаемая выплата</p>
            <div className="editor-grid">
              <Field htmlFor="payout-exp-type" label="Тип выплаты">
                <Select
                  id="payout-exp-type"
                  onChange={(e) => touchExpectedDraft({ flow_type: e.target.value })}
                  value={expectedDraft.flow_type}
                >
                  <option value="coupon">Купон</option>
                  <option value="dividend">Дивиденды</option>
                  <option value="interest">Проценты</option>
                  <option value="redemption">Погашение</option>
                  <option value="other">Прочее</option>
                </Select>
              </Field>
              <Field htmlFor="payout-exp-date" label="Дата выплаты">
                <Input
                  id="payout-exp-date"
                  onChange={(e) => touchExpectedDraft({ expected_date: e.target.value })}
                  required
                  type="date"
                  value={expectedDraft.expected_date}
                />
              </Field>
              <Field htmlFor="payout-exp-account" label="Счёт выплаты">
                <Select
                  id="payout-exp-account"
                  onChange={(e) => touchExpectedDraft({ account_id: e.target.value })}
                  required
                  value={expectedDraft.account_id}
                >
                  <option value="">—</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field htmlFor="payout-exp-instr" label="Инструмент выплаты">
                <Select
                  id="payout-exp-instr"
                  onChange={(e) => touchExpectedDraft({ instrument_id: e.target.value })}
                  required
                  value={expectedDraft.instrument_id}
                >
                  <option value="">—</option>
                  {instruments.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name}
                      {i.ticker ? ` (${i.ticker})` : ""}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field htmlFor="payout-exp-gross" label="Прогноз брутто">
                <Input
                  className="input--money"
                  id="payout-exp-gross"
                  onChange={(e) => touchExpectedDraft({ gross: e.target.value })}
                  required
                  value={expectedDraft.gross}
                />
              </Field>
              <Field htmlFor="payout-exp-tax" label="Прогноз налога (необязательно)">
                <Input
                  className="input--money"
                  id="payout-exp-tax"
                  onChange={(e) => touchExpectedDraft({ tax: e.target.value })}
                  value={expectedDraft.tax}
                />
              </Field>
              <Field htmlFor="payout-exp-net" label="Прогноз нетто (необязательно)">
                <Input
                  className="input--money"
                  id="payout-exp-net"
                  onChange={(e) => touchExpectedDraft({ net: e.target.value })}
                  value={expectedDraft.net}
                />
              </Field>
              <Field htmlFor="payout-exp-ver" label="Версия">
                <Input
                  id="payout-exp-ver"
                  onChange={(e) => touchExpectedDraft({ forecast_version: e.target.value })}
                  value={expectedDraft.forecast_version}
                />
              </Field>
            </div>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить ожидаемую выплату
            </Button>
          </form>
        ) : null}
      </Panel>

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={
          pendingDeleteActual
            ? `Удалить выплату «${labelOf(FLOW_TYPE_LABELS, pendingDeleteActual.flow_type)}» от ${pendingDeleteActual.event_date}?`
            : ""
        }
        onCancel={() => setPendingDeleteActual(null)}
        onConfirm={() => void confirmDeleteActual()}
        open={pendingDeleteActual !== null}
        title="Удалить выплату?"
      />
      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={
          pendingDeleteExpected
            ? `Удалить ожидаемую выплату «${labelOf(FLOW_TYPE_LABELS, pendingDeleteExpected.flow_type)}» на ${pendingDeleteExpected.expected_date}?`
            : ""
        }
        onCancel={() => setPendingDeleteExpected(null)}
        onConfirm={() => void confirmDeleteExpected()}
        open={pendingDeleteExpected !== null}
        title="Удалить ожидаемую выплату?"
      />
    </div>
  );
}
