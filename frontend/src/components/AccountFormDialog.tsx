import { useEffect, useId, useState, type FormEvent } from "react";

import type { AccountCreatePayload, AccountUpdatePayload } from "../api/accounts";
import type { Account } from "../api/types";
import { ACCOUNT_TYPE_LABELS, labelOf } from "../lib/labels";
import { Button, Field, Input, Select } from "./ui";

const ACCOUNT_TYPES = ["brokerage", "iis", "deposit", "savings", "cash", "other"] as const;
const ACCOUNT_STATUSES = ["active", "frozen", "closed", "hidden"] as const;
const STATUS_LABELS: Record<string, string> = {
  active: "Активен",
  frozen: "Заморожен",
  closed: "Закрыт",
  hidden: "Скрыт",
};

type Props = {
  open: boolean;
  account: Account | null;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (payload: AccountCreatePayload | AccountUpdatePayload) => Promise<void>;
};

export function AccountFormDialog({ open, account, busy, error, onCancel, onSubmit }: Props) {
  const titleId = useId();
  const descriptionId = useId();
  const [name, setName] = useState("");
  const [accountType, setAccountType] = useState("brokerage");
  const [status, setStatus] = useState("active");
  const [externalCode, setExternalCode] = useState("");
  const [notes, setNotes] = useState("");
  const [includeInCapital, setIncludeInCapital] = useState(true);
  const [includeInReturns, setIncludeInReturns] = useState(true);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(account?.name ?? "");
    setAccountType(account?.account_type ?? "brokerage");
    setStatus(account?.status ?? "active");
    setExternalCode(account?.external_code ?? "");
    setNotes(account?.notes ?? "");
    setIncludeInCapital(account?.include_in_capital ?? true);
    setIncludeInReturns(account?.include_in_returns ?? true);
    setLocalError(null);
  }, [open, account]);

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
    if (!normalizedName) {
      setLocalError("Название обязательно.");
      return;
    }
    if (normalizedName.length > 128) {
      setLocalError("Название должно быть не длиннее 128 символов.");
      return;
    }
    if (externalCode.length > 128 || notes.length > 2000) {
      setLocalError("Проверь длину внешнего кода и заметки.");
      return;
    }

    setLocalError(null);
    if (account) {
      const payload: AccountUpdatePayload = {
        name: normalizedName,
        account_type: accountType,
        status,
        include_in_capital: includeInCapital,
        include_in_returns: includeInReturns,
      };
      if (externalCode.trim()) payload.external_code = externalCode.trim();
      if (notes.trim()) payload.notes = notes.trim();
      await onSubmit(payload);
      return;
    }

    await onSubmit({
      name: normalizedName,
      account_type: accountType,
      external_code: externalCode.trim() || null,
      status,
      include_in_capital: includeInCapital,
      include_in_returns: includeInReturns,
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
          {account ? "Редактировать счёт" : "Создать счёт"}
        </h2>
        <p className="dialog__body" id={descriptionId}>
          Тип, статус и параметры учёта помогают правильно показывать счёт в итогах.
          {account
            ? " Уже заполненные дополнительные поля сохраняются, если оставить их без изменений."
            : ""}
        </p>
        <form className="form-stack" onSubmit={handleSubmit}>
          <Field htmlFor="account-name" label="Название">
            <Input
              autoFocus
              id="account-name"
              maxLength={128}
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </Field>
          <div className="form-row-2">
            <Field htmlFor="account-type" label="Тип">
              <Select
                id="account-type"
                onChange={(event) => setAccountType(event.target.value)}
                value={accountType}
              >
                {ACCOUNT_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {labelOf(ACCOUNT_TYPE_LABELS, value)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field htmlFor="account-status" label="Статус">
              <Select
                id="account-status"
                onChange={(event) => setStatus(event.target.value)}
                value={status}
              >
                {ACCOUNT_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {STATUS_LABELS[value]}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field htmlFor="account-external-code" label="Внешний код">
            <Input
              id="account-external-code"
              maxLength={128}
              onChange={(event) => setExternalCode(event.target.value)}
              value={externalCode}
            />
          </Field>
          <label className="check-row">
            <input
              checked={includeInCapital}
              onChange={(event) => setIncludeInCapital(event.target.checked)}
              type="checkbox"
            />
            Учитывать в капитале
          </label>
          <label className="check-row">
            <input
              checked={includeInReturns}
              onChange={(event) => setIncludeInReturns(event.target.checked)}
              type="checkbox"
            />
            Учитывать в доходности
          </label>
          <Field htmlFor="account-notes" label="Заметка">
            <textarea
              className="input"
              id="account-notes"
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
              {busy ? "Сохраняем…" : account ? "Сохранить" : "Создать"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
