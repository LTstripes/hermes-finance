import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
import type {
  Account,
  Instrument,
  InstrumentCleanup,
  InstrumentMarketMapping,
  MarketDiscoverResult,
  MarketIdentityWrite,
} from "../api/types";
import { AccountFormDialog } from "../components/AccountFormDialog";
import { BrokerSnapshotPanel } from "../components/BrokerSnapshotPanel";
import { IisAccountSection } from "../components/IisAccountSection";
import { MonthlyCloseReturnBar } from "../components/month-close/MonthlyCloseReturnBar";
import { parseMonthlyCloseReturnContext } from "../components/month-close/navigation";
import { InstrumentFormDialog } from "../components/InstrumentFormDialog";
import { InstrumentMappingDialog } from "../components/InstrumentMappingDialog";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
  OverflowMenu,
  OverflowMenuItem,
  Panel,
  Table,
  Td,
  Th,
} from "../components/ui";
import { formatMoney } from "../lib/format";
import { ACCOUNT_TYPE_LABELS, INSTRUMENT_TYPE_LABELS, labelOf } from "../lib/labels";
import { formatMarketIdentity, MAPPING_STATE_LABELS, mappingStateTone } from "../lib/marketData";

const ACCOUNT_STATUS_LABELS: Record<string, string> = {
  active: "Активен",
  frozen: "Заморожен",
  closed: "Закрыт",
  hidden: "Скрыт",
};

type Tab = "accounts" | "instruments";
type PendingDelete =
  | { kind: "account"; item: Account }
  | { kind: "instrument"; item: Instrument }
  | null;

function accountStatusTone(status: string): "ok" | "draft" | "closed" | "info" | "neutral" {
  if (status === "active") return "ok";
  if (status === "frozen") return "draft";
  if (status === "closed") return "closed";
  if (status === "hidden") return "info";
  return "neutral";
}

function BooleanBadge({ value }: { value: boolean }) {
  return <Badge tone={value ? "ok" : "neutral"}>{value ? "Да" : "Нет"}</Badge>;
}

function accountCodeLabel(code: string): string {
  return code.startsWith("legacy:") ? "Импортирован из прежней версии" : `Код: ${code}`;
}

export function AccountsPage() {
  const closeContext = parseMonthlyCloseReturnContext(new URLSearchParams(window.location.search));
  const [tab, setTab] = useState<Tab>("accounts");
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
      for (const view of views) {
        next[view.instrument_id] = view;
      }
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
    if (!mappings[instrument.id]) return;
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

  async function handleMappingDiscover(query?: string | null): Promise<MarketDiscoverResult> {
    if (!mappingInstrument) {
      throw new Error("Инструмент не выбран.");
    }
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

  async function handleAccountSubmit(payload: AccountCreatePayload | AccountUpdatePayload) {
    setFormBusy(true);
    setFormError(null);
    try {
      if (editingAccount) {
        await updateAccount(editingAccount.id, payload);
      } else {
        await createAccount(payload as AccountCreatePayload);
      }
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
      if (editingInstrument) {
        await updateInstrument(editingInstrument.id, payload);
      } else {
        await createInstrument(payload as InstrumentCreatePayload);
      }
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
    setActionError(null);
    try {
      await updateAccount(account.id, { status });
      await loadAccounts();
    } catch (error) {
      setActionError(formatApiError(error));
    }
  }

  async function setInstrumentActive(instrument: Instrument, isActive: boolean) {
    setActionError(null);
    try {
      await updateInstrument(instrument.id, { is_active: isActive });
      await loadInstruments();
    } catch (error) {
      setActionError(formatApiError(error));
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
    if (rows.length === 0) return <p className="muted">Нет записей в этой группе.</p>;
    return (
      <Table>
        <thead>
          <tr>
            <Th>Название</Th>
            <Th>Тип</Th>
            <Th>Статус</Th>
            <Th>В капитале</Th>
            <Th>В доходности</Th>
            <Th>Действия</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((account) => (
            <tr key={account.id}>
              <Td>
                <div className="stack-8">
                  <strong>{account.name}</strong>
                  {account.external_code ? (
                    <span className="muted tiny">{accountCodeLabel(account.external_code)}</span>
                  ) : null}
                </div>
              </Td>
              <Td>{labelOf(ACCOUNT_TYPE_LABELS, account.account_type)}</Td>
              <Td>
                <Badge tone={accountStatusTone(account.status)}>
                  {ACCOUNT_STATUS_LABELS[account.status] ?? "Статус неизвестен"}
                </Badge>
              </Td>
              <Td>
                <BooleanBadge value={account.include_in_capital} />
              </Td>
              <Td>
                <BooleanBadge value={account.include_in_returns} />
              </Td>
              <Td>
                <div className="row-actions">
                  <Button onClick={() => openEditAccount(account)} size="sm">
                    Изменить
                  </Button>
                  {account.status === "hidden" ? (
                    <Button onClick={() => void setAccountStatus(account, "active")} size="sm">
                      Показать
                    </Button>
                  ) : account.status !== "closed" ? (
                    <Button onClick={() => void setAccountStatus(account, "hidden")} size="sm">
                      Скрыть
                    </Button>
                  ) : null}
                  <Button onClick={() => openAccountDelete(account)} size="sm" variant="danger">
                    Удалить
                  </Button>
                </div>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    );
  }

  function renderInstrumentsTable(rows: Instrument[]) {
    if (rows.length === 0) return <p className="muted">Нет записей в этой группе.</p>;
    return (
      <Table>
        <thead>
          <tr>
            <Th>Название</Th>
            <Th>Тип</Th>
            <Th>Идентификатор</Th>
            <Th>Источник котировки</Th>
            <Th>Валюта</Th>
            <Th>Статус</Th>
            <Th>Действия</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((instrument) => (
            <tr key={instrument.id}>
              <Td>
                <div className="stack-8">
                  <strong>{instrument.name}</strong>
                  {instrument.nominal_value ? (
                    <span className="muted tiny">
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
              </Td>
              <Td>{labelOf(INSTRUMENT_TYPE_LABELS, instrument.instrument_type)}</Td>
              <Td>
                <span className="muted">{instrument.isin ?? instrument.ticker ?? "—"}</span>
              </Td>
              <Td>
                {(() => {
                  const mapping = mappings[instrument.id];
                  if (!mapping) {
                    return (
                      <span className="muted tiny" data-testid={`mapping-unknown-${instrument.id}`}>
                        Состояние источника не загружено
                      </span>
                    );
                  }
                  return (
                    <div className="stack-8">
                      <Badge tone={mappingStateTone(mapping.state)}>
                        {labelOf(MAPPING_STATE_LABELS, mapping.state)}
                      </Badge>
                      {mapping.identity ? (
                        <span
                          className="muted tiny"
                          data-testid={`mapping-identity-${instrument.id}`}
                        >
                          {formatMarketIdentity(mapping.identity)}
                        </span>
                      ) : null}
                      <Button onClick={() => openMapping(instrument)} size="sm">
                        Настроить источник
                      </Button>
                    </div>
                  );
                })()}
              </Td>
              <Td>{instrument.currency}</Td>
              <Td>
                <Badge tone={instrument.is_active ? "ok" : "closed"}>
                  {instrument.is_active ? "Активен" : "Неактивен"}
                </Badge>
              </Td>
              <Td>
                <OverflowMenu label={`Действия для инструмента «${instrument.name}»`}>
                  <OverflowMenuItem onClick={() => openEditInstrument(instrument)}>
                    Изменить
                  </OverflowMenuItem>
                  <OverflowMenuItem
                    onClick={() => void setInstrumentActive(instrument, !instrument.is_active)}
                  >
                    {instrument.is_active ? "Деактивировать" : "Активировать"}
                  </OverflowMenuItem>
                  <OverflowMenuItem danger onClick={() => openInstrumentDelete(instrument)}>
                    Удалить
                  </OverflowMenuItem>
                </OverflowMenu>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    );
  }

  const deleteName = pendingDelete?.item.name ?? "";
  const pendingInstrumentCleanup =
    pendingDelete?.kind === "instrument" &&
    instrumentCleanup?.instrument_id === pendingDelete.item.id
      ? instrumentCleanup
      : null;
  const deleteAllowed =
    pendingDelete?.kind === "account" || pendingInstrumentCleanup?.can_delete === true;
  const deleteDescription =
    pendingDelete?.kind !== "instrument"
      ? `Удалить «${deleteName}»?`
      : instrumentCleanupLoading
        ? `Проверяем, можно ли безопасно удалить «${deleteName}»…`
        : instrumentCleanupError
          ? `Не удалось проверить возможность удаления «${deleteName}». ${instrumentCleanupError}`
          : (pendingInstrumentCleanup?.message ??
            "Не удалось получить правила удаления. Обнови данные и повтори попытку.");

  return (
    <section className="stack-18">
      <MonthlyCloseReturnBar />
      <header className="page-header">
        <p className="eyebrow">Данные</p>
        <h1>Счета и инструменты</h1>
        <p className="page-header__description">
          Справочники счетов и инвестиционных инструментов для отчётных месяцев.
        </p>
      </header>

      <div className="toolbar">
        <Button
          aria-pressed={tab === "accounts"}
          onClick={() => setTab("accounts")}
          variant={tab === "accounts" ? "primary" : "secondary"}
        >
          Счета ({accounts.length})
        </Button>
        <Button
          aria-pressed={tab === "instruments"}
          onClick={() => setTab("instruments")}
          variant={tab === "instruments" ? "primary" : "secondary"}
        >
          Инструменты ({instruments.length})
        </Button>
        <Button
          disabled={tab === "accounts" ? accountsLoading : instrumentsLoading}
          onClick={() => void (tab === "accounts" ? loadAccounts() : loadInstruments())}
        >
          Обновить
        </Button>
        <Button
          onClick={tab === "accounts" ? openCreateAccount : openCreateInstrument}
          variant="primary"
        >
          {tab === "accounts" ? "Создать счёт" : "Создать инструмент"}
        </Button>
      </div>

      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      {tab === "accounts" ? (
        <>
          <Panel label="Справочник" title="Счета">
            {accountsLoading ? (
              <LoadingState description="Загружаем счета…" inline />
            ) : accountsError ? (
              <div className="stack-8">
                <ErrorState description={accountsError} inline title="Не удалось загрузить счета" />
                <Button onClick={() => void loadAccounts()} size="sm">
                  Повторить
                </Button>
              </div>
            ) : accounts.length === 0 ? (
              <EmptyState
                action={
                  <Button onClick={openCreateAccount} size="sm" variant="primary">
                    Создать счёт
                  </Button>
                }
                description="Справочник пока пуст."
                inline
                title="Нет счетов"
              />
            ) : (
              <>
                <h3 className="section-subhead">Активные ({visibleAccounts.length})</h3>
                {renderAccountsTable(visibleAccounts)}
                <h3 className="section-subhead">Скрытые и закрытые ({archivedAccounts.length})</h3>
                {renderAccountsTable(archivedAccounts)}
              </>
            )}
          </Panel>
          <IisAccountSection accounts={accounts} />
          <BrokerSnapshotPanel
            accounts={accounts}
            initialMonthId={closeContext?.monthId}
            instruments={instruments}
            onApplied={async () => {
              await loadAccounts();
              await loadInstruments();
            }}
          />
        </>
      ) : (
        <Panel label="Справочник" title="Инструменты">
          {instrumentsLoading ? (
            <LoadingState description="Загружаем инструменты…" inline />
          ) : instrumentsError ? (
            <div className="stack-8">
              <ErrorState
                description={instrumentsError}
                inline
                title="Не удалось загрузить инструменты"
              />
              <Button onClick={() => void loadInstruments()} size="sm">
                Повторить
              </Button>
            </div>
          ) : instruments.length === 0 ? (
            <EmptyState
              action={
                <Button onClick={openCreateInstrument} size="sm" variant="primary">
                  Создать инструмент
                </Button>
              }
              description="Справочник пока пуст."
              inline
              title="Нет инструментов"
            />
          ) : (
            <>
              <h3 className="section-subhead">Активные ({activeInstruments.length})</h3>
              {renderInstrumentsTable(activeInstruments)}
              <h3 className="section-subhead">Неактивные ({inactiveInstruments.length})</h3>
              {renderInstrumentsTable(inactiveInstruments)}
            </>
          )}
        </Panel>
      )}

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
    </section>
  );
}
