import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { listAccounts } from "../api/accounts";
import {
  confirmBrokerIdentityMapping,
  type BrokerIdentityMapping,
  listEffectiveBrokerIdentityMappings,
  remapBrokerIdentityMapping,
  revokeBrokerIdentityMapping,
} from "../api/brokerIdentityMappings";
import { formatApiError } from "../api/client";
import type { Account } from "../api/types";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "./ui";

const ALFA_PRO_PROVIDER = "alfa_pro";

type PendingAction =
  | { kind: "revoke"; mapping: BrokerIdentityMapping }
  | { kind: "remap"; mapping: BrokerIdentityMapping; targetId: number };

function accountName(accounts: Account[], accountId: number): string {
  return accounts.find((account) => account.id === accountId)?.name ?? "Счёт Hermes не найден";
}

function replaceMapping(
  mappings: BrokerIdentityMapping[],
  next: BrokerIdentityMapping,
): BrokerIdentityMapping[] {
  return [...mappings.filter((mapping) => mapping.mapping_id !== next.mapping_id), next].sort(
    (a, b) => a.provider_identity.localeCompare(b.provider_identity),
  );
}

export function BrokerIdentityMappingsPanel() {
  const [mappings, setMappings] = useState<BrokerIdentityMapping[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [providerIdentity, setProviderIdentity] = useState("");
  const [hermesAccountId, setHermesAccountId] = useState("");
  const [remapTargets, setRemapTargets] = useState<Record<number, string>>({});
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);

  const sortedAccounts = useMemo(
    () =>
      [...accounts].sort(
        (left, right) => left.name.localeCompare(right.name, "ru") || left.id - right.id,
      ),
    [accounts],
  );

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setLoadError(null);
    try {
      const [mappingRows, accountRows] = await Promise.all([
        listEffectiveBrokerIdentityMappings(ALFA_PRO_PROVIDER, signal),
        listAccounts(signal),
      ]);
      if (signal?.aborted) return;
      setMappings(
        mappingRows
          .filter(
            (mapping) =>
              mapping.provider === ALFA_PRO_PROVIDER && mapping.subject_kind === "account",
          )
          .sort((left, right) => left.provider_identity.localeCompare(right.provider_identity)),
      );
      setAccounts(accountRows);
    } catch (error) {
      if (!signal?.aborted) {
        setMappings([]);
        setAccounts([]);
        setLoadError(formatApiError(error));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  function clearMessages() {
    setActionError(null);
    setSuccess(null);
  }

  async function confirmAccountMapping(event: FormEvent) {
    event.preventDefault();
    clearMessages();
    const normalizedIdentity = providerIdentity.trim();
    const targetId = Number(hermesAccountId);
    if (!normalizedIdentity) {
      setActionError("Укажи идентификатор счёта Alfa PRO.");
      return;
    }
    if (!Number.isInteger(targetId) || targetId < 1) {
      setActionError("Выбери существующий счёт Hermes.");
      return;
    }

    setActionBusy(true);
    try {
      const mapping = await confirmBrokerIdentityMapping({
        provider: ALFA_PRO_PROVIDER,
        subject_kind: "account",
        provider_identity: normalizedIdentity,
        hermes_target_id: targetId,
      });
      setMappings((current) => replaceMapping(current, mapping));
      setProviderIdentity("");
      setHermesAccountId("");
      setSuccess("Сопоставление счёта подтверждено.");
    } catch (error) {
      setActionError(formatApiError(error));
    } finally {
      setActionBusy(false);
    }
  }

  function requestRemap(mapping: BrokerIdentityMapping) {
    clearMessages();
    const targetId = Number(remapTargets[mapping.mapping_id]);
    if (!Number.isInteger(targetId) || targetId < 1) {
      setActionError("Выбери новый счёт Hermes для переназначения.");
      return;
    }
    if (targetId === mapping.hermes_target_id) {
      setActionError("Для переназначения выбери другой счёт Hermes.");
      return;
    }
    setPendingAction({ kind: "remap", mapping, targetId });
  }

  function requestRevoke(mapping: BrokerIdentityMapping) {
    clearMessages();
    setPendingAction({ kind: "revoke", mapping });
  }

  async function confirmPendingAction() {
    if (!pendingAction) return;
    setActionBusy(true);
    setActionError(null);
    try {
      if (pendingAction.kind === "revoke") {
        await revokeBrokerIdentityMapping(pendingAction.mapping.mapping_id);
        setMappings((current) =>
          current.filter((mapping) => mapping.mapping_id !== pendingAction.mapping.mapping_id),
        );
        setSuccess("Сопоставление отозвано. Оно больше не будет использовано автоматически.");
      } else {
        const replacement = await remapBrokerIdentityMapping(pendingAction.mapping.mapping_id, {
          hermes_target_id: pendingAction.targetId,
        });
        setMappings((current) =>
          replaceMapping(
            current.filter((mapping) => mapping.mapping_id !== pendingAction.mapping.mapping_id),
            replacement,
          ),
        );
        setRemapTargets((current) => {
          const next = { ...current };
          delete next[pendingAction.mapping.mapping_id];
          return next;
        });
        setSuccess("Сопоставление переназначено. Предыдущее подтверждение сохранено в истории.");
      }
      setPendingAction(null);
    } catch (error) {
      setPendingAction(null);
      setActionError(formatApiError(error));
    } finally {
      setActionBusy(false);
    }
  }

  const pendingAccountName = pendingAction
    ? accountName(
        accounts,
        pendingAction.kind === "remap"
          ? pendingAction.targetId
          : pendingAction.mapping.hermes_target_id,
      )
    : "";

  return (
    <Panel label="Брокер" title="Сопоставления Alfa PRO">
      <div className="stack-12">
        <p className="muted">
          Здесь хранятся только явно подтверждённые сопоставления идентификаторов счетов Alfa PRO с
          уже существующими счетами Hermes. Просмотр этой секции не обращается к Alfa PRO и не
          создаёт сопоставления автоматически.
        </p>
        <p className="muted tiny">
          Переназначение создаёт новую действующую запись, а прежнюю оставляет в истории. Для
          инструментов используется отдельное подтверждение в текущем срезе.
        </p>

        {actionError ? (
          <div className="inline-alert inline-alert--error" role="alert">
            {actionError}
          </div>
        ) : null}
        {success ? (
          <div className="inline-alert inline-alert--ok" role="status">
            {success}
          </div>
        ) : null}

        {loading ? (
          <LoadingState description="Загружаем сопоставления и счета Hermes…" inline />
        ) : loadError ? (
          <div className="stack-8">
            <ErrorState description={loadError} inline title="Не удалось загрузить сопоставления" />
            <Button onClick={() => void load()} size="sm">
              Повторить
            </Button>
          </div>
        ) : (
          <>
            <form className="form-stack broker-mappings__form" onSubmit={confirmAccountMapping}>
              <div className="editor-grid">
                <Field
                  htmlFor="alfa-account-provider-identity"
                  label="Идентификатор счёта Alfa PRO"
                >
                  <Input
                    autoComplete="off"
                    id="alfa-account-provider-identity"
                    maxLength={128}
                    onChange={(event) => {
                      setProviderIdentity(event.target.value);
                      clearMessages();
                    }}
                    placeholder="Из просмотренного снимка"
                    value={providerIdentity}
                  />
                </Field>
                <Field htmlFor="alfa-account-hermes-target" label="Счёт Hermes">
                  <Select
                    disabled={sortedAccounts.length === 0 || actionBusy}
                    id="alfa-account-hermes-target"
                    onChange={(event) => {
                      setHermesAccountId(event.target.value);
                      clearMessages();
                    }}
                    value={hermesAccountId}
                  >
                    <option value="">
                      {sortedAccounts.length > 0
                        ? "— выбери существующий счёт —"
                        : "— сначала создай счёт —"}
                    </option>
                    {sortedAccounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.name}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              {sortedAccounts.length === 0 ? (
                <p className="muted tiny">
                  Сначала добавь счёт в <Link to="/accounts">разделе «Счета»</Link>. Этот экран не
                  создаёт счета автоматически.
                </p>
              ) : null}
              <div className="toolbar">
                <Button
                  disabled={actionBusy || sortedAccounts.length === 0}
                  type="submit"
                  variant="primary"
                >
                  {actionBusy ? "Сохраняем…" : "Подтвердить сопоставление"}
                </Button>
              </div>
            </form>

            <div>
              <h3 className="section-subhead">Действующие сопоставления счетов</h3>
              {mappings.length === 0 ? (
                <EmptyState
                  description="Подтверждённых сопоставлений счетов пока нет. Добавь первое сопоставление выше."
                  inline
                  title="Нет действующих сопоставлений"
                />
              ) : (
                <Table className="broker-mappings-table">
                  <thead>
                    <tr>
                      <Th>Идентификатор Alfa PRO</Th>
                      <Th>Счёт Hermes</Th>
                      <Th>Статус</Th>
                      <Th>Действия</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {mappings.map((mapping) => (
                      <tr key={mapping.mapping_id}>
                        <Td>
                          <div className="broker-mappings__identity">
                            <strong>{mapping.provider_identity}</strong>
                            <span className="muted tiny">Идентификатор Alfa PRO</span>
                          </div>
                        </Td>
                        <Td>
                          <div className="broker-mappings__target">
                            <strong>{accountName(accounts, mapping.hermes_target_id)}</strong>
                            <span className="muted tiny">Счёт Hermes</span>
                          </div>
                        </Td>
                        <Td>
                          <Badge tone="ok">Действует</Badge>
                        </Td>
                        <Td>
                          <div className="broker-mappings__actions">
                            <Field
                              htmlFor={`alfa-account-remap-${mapping.mapping_id}`}
                              label="Новый счёт Hermes"
                            >
                              <Select
                                className="broker-mappings__actions-select"
                                disabled={actionBusy}
                                id={`alfa-account-remap-${mapping.mapping_id}`}
                                onChange={(event) => {
                                  setRemapTargets((current) => ({
                                    ...current,
                                    [mapping.mapping_id]: event.target.value,
                                  }));
                                  clearMessages();
                                }}
                                value={remapTargets[mapping.mapping_id] ?? ""}
                              >
                                <option value="">— выбери другой счёт —</option>
                                {sortedAccounts.map((account) => (
                                  <option key={account.id} value={account.id}>
                                    {account.name}
                                  </option>
                                ))}
                              </Select>
                            </Field>
                            <div className="row-actions">
                              <Button
                                disabled={actionBusy}
                                onClick={() => requestRemap(mapping)}
                                size="sm"
                              >
                                Переназначить
                              </Button>
                              <Button
                                disabled={actionBusy}
                                onClick={() => requestRevoke(mapping)}
                                size="sm"
                                variant="danger"
                              >
                                Отозвать
                              </Button>
                            </div>
                          </div>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </div>
          </>
        )}
      </div>
      <ConfirmDialog
        open={pendingAction !== null}
        title={
          pendingAction?.kind === "remap"
            ? "Переназначить сопоставление?"
            : "Отозвать сопоставление?"
        }
        description={
          pendingAction?.kind === "remap"
            ? `Идентификатор ${pendingAction.mapping.provider_identity} будет связан со счётом «${pendingAccountName}». Предыдущее подтверждение останется в истории.`
            : `Сопоставление ${pendingAction?.mapping.provider_identity ?? ""} → «${pendingAccountName}» перестанет использоваться автоматически.`
        }
        confirmLabel={
          pendingAction?.kind === "remap" ? "Подтвердить переназначение" : "Отозвать сопоставление"
        }
        busy={actionBusy}
        danger={pendingAction?.kind === "revoke"}
        onCancel={() => {
          if (!actionBusy) setPendingAction(null);
        }}
        onConfirm={() => void confirmPendingAction()}
      />
    </Panel>
  );
}
