import { useEffect, useId, useState, type FormEvent } from "react";

import type { InstrumentCreatePayload, InstrumentUpdatePayload } from "../api/instruments";
import type { Instrument } from "../api/types";
import { INSTRUMENT_TYPE_LABELS, labelOf } from "../lib/labels";
import { Button, Field, Input, Select } from "./ui";

const INSTRUMENT_TYPES = ["stock", "bond", "fund", "currency", "gold", "other"] as const;

type Props = {
  open: boolean;
  instrument: Instrument | null;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (payload: InstrumentCreatePayload | InstrumentUpdatePayload) => Promise<void>;
};

function normalizeMoney(value: string): string {
  return value.trim().replace(",", ".");
}

export function InstrumentFormDialog({ open, instrument, busy, error, onCancel, onSubmit }: Props) {
  const titleId = useId();
  const descriptionId = useId();
  const [name, setName] = useState("");
  const [instrumentType, setInstrumentType] = useState("bond");
  const [isin, setIsin] = useState("");
  const [ticker, setTicker] = useState("");
  const [moexSecid, setMoexSecid] = useState("");
  const [currency, setCurrency] = useState("RUB");
  const [nominalValue, setNominalValue] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [manualPriceAllowed, setManualPriceAllowed] = useState(true);
  const [notes, setNotes] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(instrument?.name ?? "");
    setInstrumentType(instrument?.instrument_type ?? "bond");
    setIsin(instrument?.isin ?? "");
    setTicker(instrument?.ticker ?? "");
    setMoexSecid(instrument?.moex_secid ?? "");
    setCurrency(instrument?.currency ?? "RUB");
    setNominalValue(instrument?.nominal_value?.amount ?? "");
    setIsActive(instrument?.is_active ?? true);
    setManualPriceAllowed(instrument?.manual_price_allowed ?? true);
    setNotes(instrument?.notes ?? "");
    setLocalError(null);
  }, [open, instrument]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, busy, onCancel]);

  if (!open) return null;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const normalizedName = name.trim();
    const normalizedCurrency = currency.trim().toUpperCase();
    const normalizedNominal = normalizeMoney(nominalValue);
    if (!normalizedName) {
      setLocalError("Название обязательно.");
      return;
    }
    if (normalizedName.length > 128) {
      setLocalError("Название должно быть не длиннее 128 символов.");
      return;
    }
    if (!/^[A-Z]{3}$/.test(normalizedCurrency)) {
      setLocalError("Валюта должна быть трёхбуквенным кодом, например RUB.");
      return;
    }
    if (normalizedNominal && !/^\d+(\.\d{1,2})?$/.test(normalizedNominal)) {
      setLocalError("Номинал укажи десятичной строкой, например 1000.00.");
      return;
    }
    if (isin.length > 12 || ticker.length > 32 || moexSecid.length > 32 || notes.length > 2000) {
      setLocalError("Проверь длину ISIN, тикера, MOEX SECID и заметки.");
      return;
    }

    setLocalError(null);
    const common = {
      name: normalizedName,
      instrument_type: instrumentType,
      currency: normalizedCurrency,
      is_active: isActive,
      manual_price_allowed: manualPriceAllowed,
    };

    if (instrument) {
      const payload: InstrumentUpdatePayload = { ...common };
      if (isin.trim()) payload.isin = isin.trim().toUpperCase();
      if (ticker.trim()) payload.ticker = ticker.trim();
      if (moexSecid.trim()) payload.moex_secid = moexSecid.trim();
      if (normalizedNominal) {
        payload.nominal_value = { amount: normalizedNominal, currency: normalizedCurrency };
      }
      if (notes.trim()) payload.notes = notes.trim();
      await onSubmit(payload);
      return;
    }

    await onSubmit({
      ...common,
      isin: isin.trim() ? isin.trim().toUpperCase() : null,
      ticker: ticker.trim() || null,
      moex_secid: moexSecid.trim() || null,
      nominal_value: normalizedNominal
        ? { amount: normalizedNominal, currency: normalizedCurrency }
        : null,
      notes: notes.trim() || null,
    });
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <div
        aria-describedby={descriptionId}
        aria-labelledby={titleId}
        aria-modal="true"
        className="dialog dialog--wide"
        role="dialog"
      >
        <h2 className="dialog__title" id={titleId}>
          {instrument ? "Редактировать инструмент" : "Создать инструмент"}
        </h2>
        <p className="dialog__body" id={descriptionId}>
          Денежные значения сохраняются точно, без округления.
          {instrument ? " Уже заполненные дополнительные поля сохраняются, если оставить их без изменений." : ""}
        </p>
        <form className="form-stack" onSubmit={handleSubmit}>
          <Field htmlFor="instrument-name" label="Название">
            <Input
              autoFocus
              id="instrument-name"
              maxLength={128}
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </Field>
          <div className="form-row-2">
            <Field htmlFor="instrument-type" label="Тип">
              <Select
                id="instrument-type"
                onChange={(event) => setInstrumentType(event.target.value)}
                value={instrumentType}
              >
                {INSTRUMENT_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {labelOf(INSTRUMENT_TYPE_LABELS, value)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field htmlFor="instrument-currency" label="Валюта">
              <Input
                id="instrument-currency"
                maxLength={3}
                onChange={(event) => setCurrency(event.target.value)}
                required
                value={currency}
              />
            </Field>
          </div>
          <div className="form-row-2">
            <Field htmlFor="instrument-isin" label="ISIN">
              <Input
                id="instrument-isin"
                maxLength={12}
                onChange={(event) => setIsin(event.target.value)}
                value={isin}
              />
            </Field>
            <Field htmlFor="instrument-ticker" label="Тикер">
              <Input
                id="instrument-ticker"
                maxLength={32}
                onChange={(event) => setTicker(event.target.value)}
                value={ticker}
              />
            </Field>
          </div>
          <div className="form-row-2">
            <Field htmlFor="instrument-moex" label="MOEX SECID">
              <Input
                id="instrument-moex"
                maxLength={32}
                onChange={(event) => setMoexSecid(event.target.value)}
                value={moexSecid}
              />
            </Field>
            <Field htmlFor="instrument-nominal" label="Номинал">
              <Input
                className="input--money"
                id="instrument-nominal"
                inputMode="decimal"
                onChange={(event) => setNominalValue(event.target.value)}
                placeholder="1000.00"
                value={nominalValue}
              />
            </Field>
          </div>
          <label className="check-row">
            <input
              checked={isActive}
              onChange={(event) => setIsActive(event.target.checked)}
              type="checkbox"
            />
            Активен
          </label>
          <label className="check-row">
            <input
              checked={manualPriceAllowed}
              onChange={(event) => setManualPriceAllowed(event.target.checked)}
              type="checkbox"
            />
            Разрешена ручная цена
          </label>
          <Field htmlFor="instrument-notes" label="Заметка">
            <textarea
              className="input"
              id="instrument-notes"
              maxLength={2000}
              onChange={(event) => setNotes(event.target.value)}
              rows={3}
              value={notes}
            />
          </Field>
          {localError || error ? (
            <div className="inline-alert inline-alert--error" role="alert">
              {localError ?? error}
            </div>
          ) : null}
          <div className="dialog__actions">
            <Button disabled={busy} onClick={onCancel} type="button">
              Отмена
            </Button>
            <Button disabled={busy} type="submit" variant="primary">
              {busy ? "Сохраняем…" : instrument ? "Сохранить" : "Создать"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
