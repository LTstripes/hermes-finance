import { useEffect, useId, useMemo, useState, type FormEvent } from "react";

import { formatApiError } from "../../api/client";
import { cloneMonth } from "../../api/months";
import type { ReportingMonth } from "../../api/types";
import { formatMonth } from "../../lib/format";
import { defaultCloneTarget, lastDayOfMonth } from "../../lib/period";
import { Button } from "./Button";
import { Field, Input, Select } from "./Field";

const MONTH_LABELS = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
] as const;

const COPIED = [
  "Позиции (количество, цены и оценка)",
  "Депозиты (фактический процент → 0, прогноз пересчитан)",
  "Денежные средства",
  "Обязательные расходы",
  "Откладывание накоплений",
  "Долги",
  "Недвижимость / ипотека",
  "Шаблон зарплаты (регулярная зарплата)",
] as const;

const NOT_COPIED = [
  "Инвестиционные денежные потоки (купоны, дивиденды, …)",
  "Ожидаемые денежные потоки и прогноз",
  "Необязательные расходы, премии и кэшбэк",
  "Комментарии месяца",
  "Глобальные счета, инструменты, цели и ИИС",
] as const;

type CloneMonthDialogProps = {
  open: boolean;
  source: ReportingMonth | null;
  onCancel: () => void;
  onCloned: (month: ReportingMonth) => void;
};

export function CloneMonthDialog({ open, source, onCancel, onCloned }: CloneMonthDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const [target, setTarget] = useState({ year: 2026, month: 1, snapshot_date: "2026-01-31" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !source) {
      return;
    }
    setTarget(defaultCloneTarget(source));
    setError(null);
    setSuccess(null);
    setBusy(false);
  }, [open, source]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) {
        onCancel();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, busy, onCancel]);

  const monthOptions = useMemo(
    () => MONTH_LABELS.map((label, index) => ({ value: index + 1, label })),
    [],
  );

  if (!open || !source) {
    return null;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!source) {
      return;
    }
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const cloned = await cloneMonth(source.id, {
        year: target.year,
        month: target.month,
        snapshot_date: target.snapshot_date,
      });
      setSuccess(`Создан черновик ${formatMonth(cloned.year, cloned.month)}`);
      onCloned(cloned);
    } catch (err) {
      setError(formatApiError(err));
      setBusy(false);
    }
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
          Создать следующий месяц
        </h2>
        <p className="dialog__body" id={descriptionId}>
          Копируем данные из <strong>{formatMonth(source.year, source.month)}</strong>
          {source.status === "closed" ? " (месяц закрыт)" : " (черновик)"}. Изменения сохраняются
          целиком: либо создаётся полный черновик, либо ничего не меняется.
        </p>

        <div className="clone-grid">
          <div className="clone-col">
            <p className="clone-col__title clone-col__title--ok">Будет скопировано</p>
            <ul className="clone-list">
              {COPIED.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div className="clone-col">
            <p className="clone-col__title clone-col__title--muted">Не копируется / обнуляется</p>
            <ul className="clone-list">
              {NOT_COPIED.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>

        <form className="form-stack" onSubmit={handleSubmit}>
          <div className="form-row-2">
            <Field htmlFor="clone-year" label="Целевой год">
              <Input
                id="clone-year"
                inputMode="numeric"
                max={9999}
                min={1}
                name="year"
                onChange={(event) => {
                  const year = Number(event.target.value);
                  setTarget((prev) => ({
                    ...prev,
                    year,
                    snapshot_date: lastDayOfMonth(year, prev.month),
                  }));
                }}
                required
                type="number"
                value={target.year}
              />
            </Field>
            <Field htmlFor="clone-month" label="Целевой месяц">
              <Select
                id="clone-month"
                name="month"
                onChange={(event) => {
                  const month = Number(event.target.value);
                  setTarget((prev) => ({
                    ...prev,
                    month,
                    snapshot_date: lastDayOfMonth(prev.year, month),
                  }));
                }}
                value={target.month}
              >
                {monthOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field htmlFor="clone-snapshot" label="Дата снимка нового периода">
            <Input
              id="clone-snapshot"
              name="snapshot_date"
              onChange={(event) =>
                setTarget((prev) => ({ ...prev, snapshot_date: event.target.value }))
              }
              required
              type="date"
              value={target.snapshot_date}
            />
          </Field>

          {error ? (
            <div className="inline-alert inline-alert--error" role="alert">
              {error}
            </div>
          ) : null}
          {success ? (
            <div className="inline-alert inline-alert--ok" role="status">
              {success}
            </div>
          ) : null}

          <div className="dialog__actions">
            <Button disabled={busy} onClick={onCancel} type="button">
              Отмена
            </Button>
            <Button disabled={busy} type="submit" variant="primary">
              {busy ? "Копируем…" : "Копировать данные"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
