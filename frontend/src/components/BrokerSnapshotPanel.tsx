import { useState } from "react";

import { formatApiError } from "../api/client";
import {
  applyBrokerSnapshot,
  previewBrokerSnapshot,
  type BrokerMapping,
  type BrokerPositionRow,
  type BrokerSnapshotPreview,
} from "../api/brokerSnapshot";
import type { Account } from "../api/types";
import { Badge, Button, Field, Panel, Table, Td, Th } from "./ui";

export function BrokerSnapshotPanel({ accounts }: { accounts: Account[] }) {
  const [monthId, setMonthId] = useState("");
  const [providerRefs, setProviderRefs] = useState<Record<number, string>>({});
  const [preview, setPreview] = useState<BrokerSnapshotPreview | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [localValues, setLocalValues] = useState<
    Record<string, { average: string; price: string; priceDate: string; accrued: string }>
  >({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  function mapping(): BrokerMapping {
    return {
      accounts: accounts
        .map((account) => ({
          hermes_account_id: account.id,
          provider_account_id: providerRefs[account.id]?.trim() ?? "",
        }))
        .filter((row) => row.provider_account_id),
      instruments: [],
    };
  }

  async function refresh() {
    const id = Number(monthId);
    if (!Number.isInteger(id) || id < 1) return setMessage("Укажи ID отчётного месяца.");
    setBusy(true);
    setMessage(null);
    try {
      const next = await previewBrokerSnapshot(id, mapping());
      setPreview(next);
      setSelected(
        Object.fromEntries(
          next.positions.map((row) => [
            `${row.account_id}:${row.instrument_id}`,
            row.status === "matched" && Boolean(row.fingerprint),
          ]),
        ),
      );
      if (next.error_code) setMessage(next.message ?? "Не удалось обновить снимок.");
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!preview) return;
    const rows = preview.positions.filter(
      (row) => selected[`${row.account_id}:${row.instrument_id}`] && row.fingerprint,
    );
    if (rows.length === 0) return setMessage("Выбери хотя бы одну сопоставленную позицию.");
    setBusy(true);
    setMessage(null);
    try {
      const result = await applyBrokerSnapshot(
        Number(monthId),
        mapping(),
        rows.map((row: BrokerPositionRow) => {
          const values = localValues[`${row.account_id}:${row.instrument_id}`];
          if (row.status === "provider_only") {
            return {
              account_id: row.account_id,
              instrument_id: row.instrument_id,
              fingerprint: row.fingerprint as string,
              action: "create" as const,
              average_cost: { action: "replace" as const, value: values?.average ?? "" },
              market_price: {
                action: "replace" as const,
                market_price_per_unit: values?.price ?? "",
                price_date: values?.priceDate ?? "",
                price_source: "manual",
              },
              accrued_interest: { action: "replace" as const, value: values?.accrued ?? "" },
            };
          }
          return {
            account_id: row.account_id,
            instrument_id: row.instrument_id,
            fingerprint: row.fingerprint as string,
            action: "update" as const,
            average_cost: { action: "keep_existing" as const },
            market_price: { action: "keep_existing" as const },
            accrued_interest: { action: "keep_existing" as const },
          };
        }),
      );
      setMessage(
        result.success
          ? `Применено позиций: ${result.selected_count}.`
          : (result.message ?? "Снимок не применён."),
      );
      if (result.success) setPreview(null);
    } catch (error) {
      setMessage(formatApiError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel label="Alfa PRO" title="Текущий снимок брокера">
      <p className="muted">
        Снимок читается только после явного запроса. Сопоставления остаются в этом просмотре и не
        сохраняются.
      </p>
      <div className="editor-grid">
        <Field htmlFor="broker-month-id" label="ID отчётного месяца">
          <input
            id="broker-month-id"
            value={monthId}
            onChange={(event) => setMonthId(event.target.value)}
            inputMode="numeric"
          />
        </Field>
        {accounts.map((account) => (
          <Field
            key={account.id}
            htmlFor={`broker-account-${account.id}`}
            label={`Alfa ID · ${account.name}`}
          >
            <input
              id={`broker-account-${account.id}`}
              value={providerRefs[account.id] ?? ""}
              onChange={(event) =>
                setProviderRefs((current) => ({ ...current, [account.id]: event.target.value }))
              }
            />
          </Field>
        ))}
      </div>
      <div className="toolbar">
        <Button onClick={() => void refresh()} disabled={busy}>
          Обновить из Альфа PRO
        </Button>
        {preview ? (
          <Button
            onClick={() => void apply()}
            disabled={busy || !preview.eligible_for_apply}
            variant="primary"
          >
            Применить выбранное
          </Button>
        ) : null}
      </div>
      {message ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {message}
        </div>
      ) : null}
      {preview ? (
        <div className="stack-12">
          <div className="toolbar">
            <Badge tone={preview.eligible_for_apply ? "ok" : "closed"}>{preview.status}</Badge>
            <span className="muted">{preview.warnings.join(" ")}</span>
          </div>
          <Table>
            <thead>
              <tr>
                <Th>Выбор</Th>
                <Th>Счёт / инструмент</Th>
                <Th>Статус</Th>
                <Th>Количество</Th>
              </tr>
            </thead>
            <tbody>
              {preview.positions.map((row) => {
                const key = `${row.account_id}:${row.instrument_id}`;
                const values = localValues[key] ?? {
                  average: "",
                  price: "",
                  priceDate: "",
                  accrued: "",
                };
                return (
                  <tr key={key}>
                    <Td>
                      <input
                        type="checkbox"
                        checked={Boolean(selected[key])}
                        disabled={!row.fingerprint}
                        onChange={(event) =>
                          setSelected((current) => ({ ...current, [key]: event.target.checked }))
                        }
                        aria-label={`Выбрать позицию ${key}`}
                      />
                    </Td>
                    <Td>{key}</Td>
                    <Td>
                      {row.status}
                      {row.status === "provider_only" ? (
                        <div className="stack-8">
                          <input
                            aria-label={`Средняя стоимость ${key}`}
                            placeholder="Средняя стоимость"
                            value={values.average}
                            onChange={(event) =>
                              setLocalValues((current) => ({
                                ...current,
                                [key]: { ...values, average: event.target.value },
                              }))
                            }
                          />
                          <input
                            aria-label={`Рыночная цена ${key}`}
                            placeholder="Цена"
                            value={values.price}
                            onChange={(event) =>
                              setLocalValues((current) => ({
                                ...current,
                                [key]: { ...values, price: event.target.value },
                              }))
                            }
                          />
                          <input
                            aria-label={`Дата цены ${key}`}
                            type="date"
                            value={values.priceDate}
                            onChange={(event) =>
                              setLocalValues((current) => ({
                                ...current,
                                [key]: { ...values, priceDate: event.target.value },
                              }))
                            }
                          />
                          <input
                            aria-label={`НКД ${key}`}
                            placeholder="НКД"
                            value={values.accrued}
                            onChange={(event) =>
                              setLocalValues((current) => ({
                                ...current,
                                [key]: { ...values, accrued: event.target.value },
                              }))
                            }
                          />
                        </div>
                      ) : null}
                    </Td>
                    <Td>{row.provider_quantity ?? "—"}</Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </div>
      ) : null}
    </Panel>
  );
}
