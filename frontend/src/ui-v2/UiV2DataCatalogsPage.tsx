import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import {
  type AccountCreatePayload,
  type AccountUpdatePayload,
  createAccount,
  deleteAccount,
  listAccounts,
  updateAccount,
} from "../api/accounts";
import { formatApiError } from "../api/client";
import {
  deleteInstrumentMapping,
  deleteInstrumentMappingExclusion,
  discoverInstrumentMapping,
  getInstrumentMapping,
  putInstrumentMapping,
  putInstrumentMappingExclusion,
} from "../api/instrumentMappings";
import {
  createInstrument,
  deleteInstrument,
  getInstrumentCleanup,
  type InstrumentCreatePayload,
  type InstrumentUpdatePayload,
  listInstruments,
  updateInstrument,
} from "../api/instruments";
import { listMonths } from "../api/months";
import type {
  Account,
  Instrument,
  InstrumentCleanup,
  InstrumentMarketMapping,
  MarketDiscoverResult,
  MarketIdentityWrite,
} from "../api/types";
import { AccountFormDialog } from "../components/AccountFormDialog";
import { BrokerIdentityMappingsPanel } from "../components/BrokerIdentityMappingsPanel";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { Button } from "../components/ui/Button";
import { InstrumentFormDialog } from "../components/InstrumentFormDialog";
import { InstrumentMappingDialog } from "../components/InstrumentMappingDialog";
import { formatMoney } from "../lib/format";
import { ACCOUNT_TYPE_LABELS, INSTRUMENT_TYPE_LABELS, labelOf } from "../lib/labels";
import { formatMarketIdentity, MAPPING_STATE_LABELS, mappingStateTone } from "../lib/marketData";
import { queryKeys } from "../queryClient";
import { DataMonthContext, resolveDataMonth, UiV2DataFrame } from "./UiV2DataShell";
import { isQueryReady, UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";
import { sortReportingMonths } from "./monthSelection";
import dataStyles from "./UiV2Data.module.css";
import styles from "./UiV2Catalogs.module.css";

type CatalogTab = "accounts" | "instruments" | "mappings";
type PendingDelete =
  | { kind: "account"; item: Account }
  | { kind: "instrument"; item: Instrument }
  | null;

const ACCOUNT_STATUS_LABELS: Record<string, string> = {
  active: "Активен",
  frozen: "Заморожен",
  closed: "Закрыт",
  hidden: "Скрыт",
};

function accountStatusTone(status: string): string {
  if (status === "active") return "ok";
  if (status === "frozen") return "stale";
  if (status === "closed") return "missing";
  if (status === "hidden") return "info";
  return "neutral";
}

function StatusPill({ label, tone }: { label: string; tone: string }) {
  return (
    <span className={dataStyles.statusBadge} data-tone={tone}>
      {label}
    </span>
  );
}

function BooleanPill({ value }: { value: boolean }) {
  return <StatusPill label={value ? "Да" : "Нет"} tone={value ? "ok" : "neutral"} />;
}

function accountCodeLabel(code: string): string {
  return code.startsWith("legacy:") ? "Импортирован из прежней версии" : `Код: ${code}`;
}

function TabButton({
  active,
  count,
  label,
  onClick,
}: {
  active: boolean;
  count?: number;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-selected={active}
      className={`${styles.catalogTab} ${active ? styles.catalogTabActive : ""}`}
      onClick={onClick}
      role="tab"
      type="button"
    >
      {label}
      {count == null ? "" : ` (${count})`}
    </button>
  );
}

export default function UiV2DataCatalogsPage() {
  const [params, setParams] = useSearchParams();
  const monthsQuery = useQuery({
    queryKey: queryKeys.months,
    queryFn: ({ signal }) => listMonths(signal),
  });
  const months = useMemo(() => sortReportingMonths(monthsQuery.data ?? []), [monthsQuery.data]);
  const monthsReady = isQueryReady(monthsQuery);
  const resolution = resolveDataMonth(params.getAll("month"), months, monthsReady);
  const monthId = resolution.kind === "ready" ? resolution.month.id : undefined;

  const requestedTabs = params.getAll("tab");
  const tab: CatalogTab =
    requestedTabs.length === 1 &&
    (requestedTabs[0] === "accounts" ||
      requestedTabs[0] === "instruments" ||
      requestedTabs[0] === "mappings")
      ? requestedTabs[0]
      : "accounts";
  function selectTab(nextTab: CatalogTab) {
    const next = new URLSearchParams(params);
    if (nextTab === "accounts") next.delete("tab");
    else next.set("tab", nextTab);
    setParams(next);
  }
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [instrumentsLoading, setInstrumentsLoading] = useState(true);
  const [accountsError, setAccountsError] = useState<string | null>(null);
  const [instrumentsError, setInstrumentsError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [accountDialogOpen, setAccountDialogOpen] = useState(false);
  const [instrumentDialogOpen, setInstrumentDialogOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [editingInstrument, setEditingInstrument] = useState<Instrument | null>(null);
  const [mappingInstrument, setMappingInstrument] = useState<Instrument | null>(null);
  const [mappings, setMappings] = useState<Record<number, InstrumentMarketMapping>>({});
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [mappingError, setMappingError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete>(null);
  const [deleting, setDeleting] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [instrumentCleanup, setInstrumentCleanup] = useState<InstrumentCleanup | null>(null);
  const [instrumentCleanupLoading, setInstrumentCleanupLoading] = useState(false);
  const [instrumentCleanupError, setInstrumentCleanupError] = useState<string | null>(null);
  const cleanupRequestId = useRef(0);

  const loadAccounts = useCallback(async (signal?: AbortSignal) => {
    setAccountsLoading(true);
    setAccountsError(null);
    try {
      const rows = await listAccounts(signal);
      if (!signal?.aborted) setAccounts(rows);
    } catch (error) {
      if (!signal?.aborted) {
        setAccounts([]);
        setAccountsError(formatApiError(error));
      }
    } finally {
      if (!signal?.aborted) setAccountsLoading(false);
    }
  }, []);

  const loadInstruments = useCallback(async (signal?: AbortSignal) => {
    setInstrumentsLoading(true);
    setInstrumentsError(null);
    try {
      const rows = await listInstruments({}, signal);
      if (signal?.aborted) return;
      const views = await Promise.all(rows.map((row) => getInstrumentMapping(row.id, signal)));
      if (signal?.aborted) return;
      const next: Record<number, InstrumentMarketMapping> = {};
      for (const view of views) next[view.instrument_id] = view;
      setInstruments(rows);
      setMappings(next);
    } catch (error) {
      if (!signal?.aborted) {
        setInstruments([]);
        setMappings({});
        setInstrumentsError(formatApiError(error));
      }
    } finally {
      if (!signal?.aborted) setInstrumentsLoading(false);
    }
  }, []);

  useEffect(() => {
    const accountsController = new AbortController();
    const instrumentsController = new AbortController();
    void loadAccounts(accountsController.signal);
    void loadInstruments(instrumentsController.signal);
    return () => {
      accountsController.abort();
      instrumentsController.abort();
    };
  }, [loadAccounts, loadInstruments]);

  const visibleAccounts = useMemo(
    () => accounts.filter((row) => row.status === "active" || row.status === "frozen"),
    [accounts],
  );
  const archivedAccounts = useMemo(
    () => accounts.filter((row) => row.status === "hidden" || row.status === "closed"),
    [accounts],
  );
  const activeInstruments = useMemo(
    () => instruments.filter((row) => row.is_active),
    [instruments],
  );
  const inactiveInstruments = useMemo(
    () => instruments.filter((row) => !row.is_active),
    [instruments],
  );

  function openCreateAccount() {
    setEditingAccount(null);
    setFormError(null);
    setAccountDialogOpen(true);
  }

  function openEditAccount(account: Account) {
    setEditingAccount(account);
    setFormError(null);
    setAccountDialogOpen(true);
  }

  function openCreateInstrument() {
    setEditingInstrument(null);
    setFormError(null);
    setInstrumentDialogOpen(true);
  }

  function openEditInstrument(instrument: Instrument) {
    setEditingInstrument(instrument);
    setFormError(null);
    setInstrumentDialogOpen(true);
  }

  function openMapping(instrument: Instrument) {
    const mapping = mappings[instrument.id];
    if (!mapping) return;
    setMappingInstrument(instrument);
    setMappingError(null);
  }

  function rememberMapping(view: InstrumentMarketMapping) {
    setMappings((current) => ({ ...current, [view.instrument_id]: view }));
  }

  async function handleMappingSave(payload: MarketIdentityWrite) {
    if (!mappingInstrument) return;
    setFormBusy(true);
    setMappingError(null);
    try {
      rememberMapping(await putInstrumentMapping(mappingInstrument.id, payload));
    } catch (error) {
      setMappingError(formatApiError(error));
    } finally {
      setFormBusy(false);
    }
  }

  async function handleMappingClear() {
    if (!mappingInstrument) return;
    setFormBusy(true);
    setMappingError(null);
    try {
      rememberMapping(await deleteInstrumentMapping(mappingInstrument.id));
    } catch (error) {
      setMappingError(formatApiError(error));
    } finally {
      setFormBusy(false);
    }
  }

  async function handleMappingExclude() {
    if (!mappingInstrument) return;
    setFormBusy(true);
    setMappingError(null);
    try {
      rememberMapping(await putInstrumentMappingExclusion(mappingInstrument.id));
    } catch (error) {
      setMappingError(formatApiError(error));
    } finally {
      setFormBusy(false);
    }
  }

  async function handleMappingClearExclusion() {
    if (!mappingInstrument) return;
    setFormBusy(true);
    setMappingError(null);
    try {
      rememberMapping(await deleteInstrumentMappingExclusion(mappingInstrument.id));
    } catch (error) {
      setMappingError(formatApiError(error));
    } finally {
      setFormBusy(false);
    }
  }

  async function handleMappingDiscover(query?: string | null): Promise<MarketDiscoverResult> {
    if (!mappingInstrument) throw new Error("Инструмент не выбран.");
    try {
      const normalizedQuery = query?.trim();
      return await discoverInstrumentMapping(mappingInstrument.id, {
        provider: "t_invest",
        ...(normalizedQuery ? { query: normalizedQuery } : {}),
      });
    } catch (error) {
      throw new Error(formatApiError(error));
    }
  }

  async function handleAccountSubmit(payload: AccountCreatePayload | AccountUpdatePayload) {
    setFormBusy(true);
    setFormError(null);
    try {
      if (editingAccount) await updateAccount(editingAccount.id, payload);
      else await createAccount(payload as AccountCreatePayload);
      setAccountDialogOpen(false);
      setEditingAccount(null);
      await loadAccounts();
    } catch (error) {
      setFormError(formatApiError(error));
    } finally {
      setFormBusy(false);
    }
  }

  async function handleInstrumentSubmit(
    payload: InstrumentCreatePayload | InstrumentUpdatePayload,
  ) {
    setFormBusy(true);
    setFormError(null);
    try {
      if (editingInstrument) await updateInstrument(editingInstrument.id, payload);
      else await createInstrument(payload as InstrumentCreatePayload);
      setInstrumentDialogOpen(false);
      setEditingInstrument(null);
      await loadInstruments();
    } catch (error) {
      setFormError(formatApiError(error));
    } finally {
      setFormBusy(false);
    }
  }

  async function setAccountStatus(account: Account, status: string) {
    setActionBusy(true);
    setActionError(null);
    try {
      await updateAccount(account.id, { status });
      await loadAccounts();
    } catch (error) {
      setActionError(formatApiError(error));
    } finally {
      setActionBusy(false);
    }
  }

  async function setInstrumentActive(instrument: Instrument, isActive: boolean) {
    setActionBusy(true);
    setActionError(null);
    try {
      await updateInstrument(instrument.id, { is_active: isActive });
      await loadInstruments();
    } catch (error) {
      setActionError(formatApiError(error));
    } finally {
      setActionBusy(false);
    }
  }

  function closeDeleteDialog() {
    if (deleting) return;
    cleanupRequestId.current += 1;
    setPendingDelete(null);
    setInstrumentCleanup(null);
    setInstrumentCleanupLoading(false);
    setInstrumentCleanupError(null);
  }

  function openAccountDelete(account: Account) {
    cleanupRequestId.current += 1;
    setPendingDelete({ kind: "account", item: account });
    setInstrumentCleanup(null);
    setInstrumentCleanupLoading(false);
    setInstrumentCleanupError(null);
  }

  function openInstrumentDelete(instrument: Instrument) {
    const requestId = cleanupRequestId.current + 1;
    cleanupRequestId.current = requestId;
    setPendingDelete({ kind: "instrument", item: instrument });
    setInstrumentCleanup(null);
    setInstrumentCleanupError(null);
    setInstrumentCleanupLoading(true);
    void getInstrumentCleanup(instrument.id)
      .then((cleanup) => {
        if (cleanupRequestId.current === requestId) setInstrumentCleanup(cleanup);
      })
      .catch((error) => {
        if (cleanupRequestId.current === requestId) {
          setInstrumentCleanupError(formatApiError(error));
        }
      })
      .finally(() => {
        if (cleanupRequestId.current === requestId) setInstrumentCleanupLoading(false);
      });
  }

  async function handleConfirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    setActionError(null);
    try {
      if (pendingDelete.kind === "account") {
        await deleteAccount(pendingDelete.item.id);
        await loadAccounts();
      } else {
        await deleteInstrument(pendingDelete.item.id);
        await loadInstruments();
      }
      setPendingDelete(null);
    } catch (error) {
      setActionError(formatApiError(error));
      setPendingDelete(null);
    } finally {
      setDeleting(false);
    }
  }

  function renderAccountsTable(rows: Account[]) {
    if (rows.length === 0) return <div className={styles.empty}>Нет записей в этой группе.</div>;
    return (
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Название</th>
              <th scope="col">Тип</th>
              <th scope="col">Статус</th>
              <th scope="col">В капитале</th>
              <th scope="col">В доходности</th>
              <th scope="col">Действия</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((account) => (
              <tr key={account.id}>
                <td>
                  <div className={styles.cellStack}>
                    <strong>{account.name}</strong>
                    {account.external_code ? (
                      <span className={styles.cellHint}>
                        {accountCodeLabel(account.external_code)}
                      </span>
                    ) : null}
                  </div>
                </td>
                <td>{labelOf(ACCOUNT_TYPE_LABELS, account.account_type)}</td>
                <td>
                  <StatusPill
                    label={ACCOUNT_STATUS_LABELS[account.status] ?? "Статус неизвестен"}
                    tone={accountStatusTone(account.status)}
                  />
                </td>
                <td>
                  <BooleanPill value={account.include_in_capital} />
                </td>
                <td>
                  <BooleanPill value={account.include_in_returns} />
                </td>
                <td>
                  <div className={styles.rowActions}>
                    <Button
                      disabled={actionBusy}
                      onClick={() => openEditAccount(account)}
                      size="sm"
                    >
                      Изменить
                    </Button>
                    {account.status === "hidden" ? (
                      <Button
                        disabled={actionBusy}
                        onClick={() => void setAccountStatus(account, "active")}
                        size="sm"
                      >
                        Показать
                      </Button>
                    ) : account.status !== "closed" ? (
                      <Button
                        disabled={actionBusy}
                        onClick={() => void setAccountStatus(account, "hidden")}
                        size="sm"
                      >
                        Скрыть
                      </Button>
                    ) : null}
                    <Button
                      disabled={actionBusy}
                      onClick={() => openAccountDelete(account)}
                      size="sm"
                      variant="danger"
                    >
                      Удалить
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  function renderInstrumentsTable(rows: Instrument[]) {
    if (rows.length === 0) return <div className={styles.empty}>Нет записей в этой группе.</div>;
    return (
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Название</th>
              <th scope="col">Тип</th>
              <th scope="col">Идентификатор</th>
              <th scope="col">Источник котировки</th>
              <th scope="col">Валюта</th>
              <th scope="col">Статус</th>
              <th scope="col">Действия</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((instrument) => {
              const mapping = mappings[instrument.id];
              return (
                <tr key={instrument.id}>
                  <td>
                    <div className={styles.cellStack}>
                      <strong>{instrument.name}</strong>
                      {instrument.nominal_value ? (
                        <span className={styles.cellHint}>
                          Номинал:{" "}
                          {formatMoney(instrument.nominal_value.amount, {
                            currency:
                              instrument.nominal_value.currency === "RUB"
                                ? "₽"
                                : instrument.nominal_value.currency,
                          })}
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td>{labelOf(INSTRUMENT_TYPE_LABELS, instrument.instrument_type)}</td>
                  <td>
                    <span className={styles.cellHint}>
                      {instrument.isin ?? instrument.ticker ?? "Идентификатор не задан"}
                    </span>
                  </td>
                  <td>
                    <div className={styles.sourceCell}>
                      {mapping ? (
                        <>
                          <StatusPill
                            label={labelOf(MAPPING_STATE_LABELS, mapping.state)}
                            tone={mappingStateTone(mapping.state)}
                          />
                          {mapping.identity ? (
                            <span
                              className={styles.sourceIdentity}
                              data-testid={`catalog-mapping-identity-${instrument.id}`}
                            >
                              {formatMarketIdentity(mapping.identity)}
                            </span>
                          ) : null}
                          <Button onClick={() => openMapping(instrument)} size="sm">
                            Настроить источник
                          </Button>
                        </>
                      ) : (
                        <span className={styles.cellHint}>Состояние источника не загружено</span>
                      )}
                    </div>
                  </td>
                  <td>{instrument.currency}</td>
                  <td>
                    <StatusPill
                      label={instrument.is_active ? "Активен" : "Неактивен"}
                      tone={instrument.is_active ? "ok" : "missing"}
                    />
                  </td>
                  <td>
                    <div className={styles.rowActions}>
                      <Button
                        disabled={actionBusy}
                        onClick={() => openEditInstrument(instrument)}
                        size="sm"
                      >
                        Изменить
                      </Button>
                      <Button
                        disabled={actionBusy}
                        onClick={() => void setInstrumentActive(instrument, !instrument.is_active)}
                        size="sm"
                      >
                        {instrument.is_active ? "Деактивировать" : "Активировать"}
                      </Button>
                      <Button
                        disabled={actionBusy}
                        onClick={() => openInstrumentDelete(instrument)}
                        size="sm"
                        variant="danger"
                      >
                        Удалить
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  function accountsContent(): ReactNode {
    return (
      <section className={styles.catalogPanel} data-testid="catalog-accounts">
        <div className={styles.panelHeader}>
          <div>
            <h2>Счета</h2>
            <p>
              Счета, которые участвуют в финансовой картине и постоянных сопоставлениях с брокером.
            </p>
          </div>
          <Button onClick={() => void loadAccounts()} disabled={accountsLoading} size="sm">
            Обновить
          </Button>
        </div>
        {accountsLoading ? (
          <UiV2Loading label="Загружаем счета…" />
        ) : accountsError ? (
          <UiV2Notice title="Не удалось загрузить счета" retry={() => void loadAccounts()}>
            {accountsError}
          </UiV2Notice>
        ) : accounts.length === 0 ? (
          <div className={styles.empty}>
            <p>Справочник пока пуст.</p>
            <Button onClick={openCreateAccount} size="sm" variant="primary">
              Создать счёт
            </Button>
          </div>
        ) : (
          <>
            <div className={styles.group}>
              <h3 className={styles.groupTitle}>
                Активные <span>{visibleAccounts.length}</span>
              </h3>
              {renderAccountsTable(visibleAccounts)}
            </div>
            <div className={styles.group}>
              <h3 className={styles.groupTitle}>
                Скрытые и закрытые <span>{archivedAccounts.length}</span>
              </h3>
              {renderAccountsTable(archivedAccounts)}
            </div>
          </>
        )}
      </section>
    );
  }

  function instrumentsContent(): ReactNode {
    return (
      <section className={styles.catalogPanel} data-testid="catalog-instruments">
        <div className={styles.panelHeader}>
          <div>
            <h2>Инструменты</h2>
            <p>
              Локальный справочник бумаг. Внешний источник и его идентификатор задаются отдельно и
              явно.
            </p>
          </div>
          <Button onClick={() => void loadInstruments()} disabled={instrumentsLoading} size="sm">
            Обновить
          </Button>
        </div>
        {instrumentsLoading ? (
          <UiV2Loading label="Загружаем инструменты и сохранённые источники…" />
        ) : instrumentsError ? (
          <UiV2Notice title="Не удалось загрузить инструменты" retry={() => void loadInstruments()}>
            {instrumentsError}
          </UiV2Notice>
        ) : instruments.length === 0 ? (
          <div className={styles.empty}>
            <p>Справочник пока пуст.</p>
            <Button onClick={openCreateInstrument} size="sm" variant="primary">
              Создать инструмент
            </Button>
          </div>
        ) : (
          <>
            <div className={styles.group}>
              <h3 className={styles.groupTitle}>
                Активные <span>{activeInstruments.length}</span>
              </h3>
              {renderInstrumentsTable(activeInstruments)}
            </div>
            <div className={styles.group}>
              <h3 className={styles.groupTitle}>
                Неактивные <span>{inactiveInstruments.length}</span>
              </h3>
              {renderInstrumentsTable(inactiveInstruments)}
            </div>
          </>
        )}
      </section>
    );
  }

  function mappingsContent(): ReactNode {
    return (
      <div className={styles.brokerWrap} data-testid="catalog-mappings">
        <div className={styles.brokerIntro}>
          Здесь сохраняются только явные подтверждения источника. Просмотр не обращается к внешнему
          брокеру, а переназначение и отзыв требуют отдельного подтверждения. Сопоставление
          инструмента с источником настраивается на вкладке «Инструменты».
        </div>
        <BrokerIdentityMappingsPanel />
      </div>
    );
  }

  const pendingInstrumentCleanup =
    pendingDelete?.kind === "instrument" &&
    instrumentCleanup?.instrument_id === pendingDelete.item.id
      ? instrumentCleanup
      : null;
  const deleteAllowed =
    pendingDelete?.kind === "account" || pendingInstrumentCleanup?.can_delete === true;
  const deleteName = pendingDelete?.item.name ?? "";
  const deleteDescription =
    pendingDelete?.kind !== "instrument"
      ? `Удалить «${deleteName}»? Это явное удаление записи справочника.`
      : instrumentCleanupLoading
        ? `Проверяем, можно ли безопасно удалить «${deleteName}»…`
        : instrumentCleanupError
          ? `Не удалось проверить возможность удаления «${deleteName}». ${instrumentCleanupError}`
          : (pendingInstrumentCleanup?.message ??
            "Инструмент нельзя удалить, пока проверка связанных данных не подтверждена.");

  let monthContent: ReactNode;
  if (monthsQuery.isError) {
    monthContent = (
      <UiV2Notice
        title="Не удалось загрузить отчётный контекст"
        retry={() => void monthsQuery.refetch()}
      >
        Каталоги можно открыть, но выбранный диагностический месяц не подтверждён.
      </UiV2Notice>
    );
  } else if (resolution.kind === "loading") {
    monthContent = <UiV2Loading label="Проверяем доступные отчётные месяцы…" />;
  } else if (resolution.kind === "invalid" || resolution.kind === "missing") {
    monthContent = (
      <UiV2Notice title="Параметр месяца не принят">
        Явный месяц должен существовать ровно один раз. Каталоги не подменяют его другим месяцем.
      </UiV2Notice>
    );
  } else if (resolution.kind === "empty") {
    monthContent = (
      <UiV2Notice title="Нет отчётных месяцев">
        Каталоги не требуют отчётного месяца. Создать или открыть его можно в предыдущем интерфейсе:{" "}
        <Link to="/months">Открыть месяцы ↗</Link>
      </UiV2Notice>
    );
  } else {
    monthContent = (
      <DataMonthContext automatic={resolution.automatic} month={resolution.month}>
        <Link to="/accounts">В предыдущем интерфейсе ↗</Link>
      </DataMonthContext>
    );
  }

  return (
    <UiV2DataFrame
      active="catalogs"
      busy={accountsLoading || instrumentsLoading || monthsQuery.isFetching}
      monthId={monthId}
      subtitle="Счета, инструменты и постоянные сопоставления — с явными изменениями и защитными проверками."
      title="Справочники и сопоставления"
      v1ReturnPath="/accounts"
    >
      <div className={styles.catalogs} data-testid="catalogs-page">
        {monthContent}
        <div className={dataStyles.semanticNote}>
          <strong>Изменяет данные</strong>
          <span>
            Создание, редактирование, статус, проверка связанных данных и сопоставления выполняются
            только по явному действию. Поиск инструмента во внешнем источнике запускается только
            кнопкой.
          </span>
        </div>
        <div aria-label="Каталоги" className={styles.catalogTabs} role="tablist">
          <TabButton
            active={tab === "accounts"}
            count={accounts.length}
            label="Счета"
            onClick={() => selectTab("accounts")}
          />
          <TabButton
            active={tab === "instruments"}
            count={instruments.length}
            label="Инструменты"
            onClick={() => selectTab("instruments")}
          />
          <TabButton
            active={tab === "mappings"}
            label="Постоянные сопоставления"
            onClick={() => selectTab("mappings")}
          />
        </div>
        {actionError ? (
          <div className={dataStyles.alert} role="alert">
            {actionError}
          </div>
        ) : null}
        <div className={styles.toolbar}>
          <span className={styles.toolbarNote}>
            Справочники не запускают импорт и не применяют данные месяца.
          </span>
          {tab === "accounts" ? (
            <Button onClick={openCreateAccount} variant="primary">
              Создать счёт
            </Button>
          ) : tab === "instruments" ? (
            <Button onClick={openCreateInstrument} variant="primary">
              Создать инструмент
            </Button>
          ) : null}
        </div>
        {tab === "accounts"
          ? accountsContent()
          : tab === "instruments"
            ? instrumentsContent()
            : mappingsContent()}
      </div>

      <AccountFormDialog
        account={editingAccount}
        busy={formBusy}
        error={formError}
        onCancel={() => {
          if (!formBusy) {
            setAccountDialogOpen(false);
            setEditingAccount(null);
            setFormError(null);
          }
        }}
        onSubmit={handleAccountSubmit}
        open={accountDialogOpen}
      />
      <InstrumentFormDialog
        busy={formBusy}
        error={formError}
        instrument={editingInstrument}
        onCancel={() => {
          if (!formBusy) {
            setInstrumentDialogOpen(false);
            setEditingInstrument(null);
            setFormError(null);
          }
        }}
        onSubmit={handleInstrumentSubmit}
        open={instrumentDialogOpen}
      />
      <InstrumentMappingDialog
        busy={formBusy}
        error={mappingError}
        instrument={mappingInstrument}
        mapping={mappingInstrument ? (mappings[mappingInstrument.id] ?? null) : null}
        onCancel={() => {
          if (!formBusy) {
            setMappingInstrument(null);
            setMappingError(null);
          }
        }}
        onClear={handleMappingClear}
        onClearExclusion={handleMappingClearExclusion}
        onDiscover={(_provider, query) => handleMappingDiscover(query)}
        onExclude={handleMappingExclude}
        onSave={handleMappingSave}
        open={mappingInstrument !== null}
      />
      <ConfirmDialog
        busy={deleting}
        cancelLabel="Отмена"
        confirmLabel={
          pendingDelete?.kind === "instrument" && !deleteAllowed ? "Понятно" : "Удалить"
        }
        danger={deleteAllowed}
        description={deleteDescription}
        onCancel={closeDeleteDialog}
        onConfirm={() => {
          if (pendingDelete?.kind === "instrument" && !deleteAllowed) {
            closeDeleteDialog();
            return;
          }
          void handleConfirmDelete();
        }}
        open={pendingDelete !== null}
        title={
          pendingDelete?.kind === "instrument" ? "Проверка удаления инструмента" : "Удалить запись?"
        }
      />
    </UiV2DataFrame>
  );
}
