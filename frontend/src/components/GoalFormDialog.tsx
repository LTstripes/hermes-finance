import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import type { Goal, GoalCreatePayload, GoalUpdatePayload } from "../api/goals";
import {
  defaultCalculationMode,
  GOAL_TYPE_LABELS,
  GOAL_TYPES,
  goalCalculationModeLabel,
  goalForecastSupportLabel,
} from "../lib/goals";
import { normalizeMoneyInput } from "../lib/money";
import { Button, Field, Input, Select } from "./ui";

type Props = {
  open: boolean;
  goal: Goal | null;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (payload: GoalCreatePayload | GoalUpdatePayload) => Promise<void>;
  restoreFocusRef?: { current: HTMLElement | null };
};

export function GoalFormDialog({
  open,
  goal,
  busy,
  error,
  onCancel,
  onSubmit,
  restoreFocusRef,
}: Props) {
  const titleId = useId();
  const descriptionId = useId();
  const restoreFocusTargetRef = useRef<HTMLElement | null>(null);
  const [name, setName] = useState("");
  const [goalType, setGoalType] = useState("passive_income");
  const [targetValue, setTargetValue] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [isMain, setIsMain] = useState(false);
  const [calculationMode, setCalculationMode] = useState(defaultCalculationMode("passive_income"));
  const [notes, setNotes] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const initialType = goal?.goal_type ?? "passive_income";
    setName(goal?.name ?? "");
    setGoalType(initialType);
    setTargetValue(goal?.target_value.amount ?? "");
    setTargetDate(goal?.target_date ?? "");
    setIsActive(goal?.is_active ?? true);
    setIsMain(goal?.is_main ?? false);
    setCalculationMode(goal?.calculation_mode ?? defaultCalculationMode(initialType));
    setNotes(goal?.notes ?? "");
    setLocalError(null);
  }, [open, goal]);

  useEffect(() => {
    if (!open) return;
    restoreFocusTargetRef.current =
      restoreFocusRef?.current ??
      (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    return () => {
      if (restoreFocusTargetRef.current?.isConnected) {
        restoreFocusTargetRef.current.focus();
      }
      restoreFocusTargetRef.current = null;
    };
  }, [open, restoreFocusRef]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, busy, onCancel]);

  if (!open) return null;

  function handleGoalTypeChange(nextType: string) {
    setGoalType(nextType);
    setCalculationMode(
      goal && nextType === goal.goal_type
        ? goal.calculation_mode
        : defaultCalculationMode(nextType),
    );
    if (nextType !== "passive_income") {
      setIsMain(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const normalizedName = name.trim();
    const normalizedTarget = normalizeMoneyInput(targetValue);
    const normalizedNotes = notes.trim();

    if (!normalizedName) {
      setLocalError("Название обязательно.");
      return;
    }
    if (normalizedName.length > 128) {
      setLocalError("Название должно быть не длиннее 128 символов.");
      return;
    }
    if (normalizedTarget == null || normalizedTarget.startsWith("-")) {
      setLocalError("Целевое значение должно быть неотрицательной суммой с точностью до копеек.");
      return;
    }
    if (normalizedNotes.length > 2000) {
      setLocalError("Заметка должна быть не длиннее 2000 символов.");
      return;
    }
    if (goal?.target_date && !targetDate) {
      setLocalError(
        "Пока нельзя полностью очистить уже заданный срок. Укажи новую дату или оставь прежнюю.",
      );
      return;
    }
    if (goal?.notes && !normalizedNotes) {
      setLocalError(
        "Пока нельзя полностью очистить уже заданную заметку. Измени текст или оставь прежний.",
      );
      return;
    }
    if (isMain && (goalType !== "passive_income" || !isActive)) {
      setLocalError("Основной может быть только активная цель пассивного дохода.");
      return;
    }

    setLocalError(null);
    const target = { amount: normalizedTarget, currency: "RUB" };

    if (goal) {
      const payload: GoalUpdatePayload = {
        name: normalizedName,
        goal_type: goalType,
        target_value: target,
        is_active: isActive,
        is_main: isMain,
        calculation_mode: calculationMode,
      };
      if (targetDate) payload.target_date = targetDate;
      if (normalizedNotes) payload.notes = normalizedNotes;
      await onSubmit(payload);
      return;
    }

    await onSubmit({
      name: normalizedName,
      goal_type: goalType,
      target_value: target,
      target_date: targetDate || null,
      is_active: isActive,
      is_main: isMain,
      calculation_mode: calculationMode,
      notes: normalizedNotes || null,
    });
  }

  const mainLocked = goal?.is_main ?? false;

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
          {goal ? "Редактировать цель" : "Создать цель"}
        </h2>
        <p className="dialog__body" id={descriptionId}>
          Финансовый прогресс и прогноз рассчитываются автоматически. Поле «срок» — твой дедлайн, а
          не обещанная дата достижения.
        </p>
        <form className="form-stack" onSubmit={handleSubmit}>
          <Field htmlFor="goal-name" label="Название">
            <Input
              autoFocus
              id="goal-name"
              maxLength={128}
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </Field>

          <div className="form-row-2">
            <Field htmlFor="goal-type" label="Тип">
              <Select
                disabled={mainLocked}
                id="goal-type"
                onChange={(event) => handleGoalTypeChange(event.target.value)}
                value={goalType}
              >
                {GOAL_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {GOAL_TYPE_LABELS[value]}
                  </option>
                ))}
              </Select>
            </Field>
            <Field htmlFor="goal-target" label="Целевое значение">
              <Input
                id="goal-target"
                inputMode="decimal"
                onChange={(event) => setTargetValue(event.target.value)}
                placeholder="100000,00"
                required
                value={targetValue}
              />
            </Field>
          </div>

          <Field htmlFor="goal-target-date" label="Срок (необязательно)">
            <Input
              id="goal-target-date"
              onChange={(event) => setTargetDate(event.target.value)}
              type="date"
              value={targetDate}
            />
          </Field>

          <div className="field">
            <span className="field__label">Способ расчёта</span>
            <p>{goalCalculationModeLabel(calculationMode)}</p>
            <p className="muted tiny">{goalForecastSupportLabel(goalType, calculationMode)}</p>
          </div>

          <label className="check-row">
            <input
              checked={isActive}
              disabled={mainLocked || isMain}
              onChange={(event) => {
                setIsActive(event.target.checked);
                if (!event.target.checked) setIsMain(false);
              }}
              type="checkbox"
            />
            Активная цель
          </label>

          {goalType === "passive_income" ? (
            <label className="check-row">
              <input
                checked={isMain}
                disabled={mainLocked}
                onChange={(event) => {
                  setIsMain(event.target.checked);
                  if (event.target.checked) setIsActive(true);
                }}
                type="checkbox"
              />
              Основная цель
            </label>
          ) : null}

          <Field htmlFor="goal-notes" label="Заметка">
            <textarea
              className="input"
              id="goal-notes"
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
              {busy ? "Сохраняем…" : goal ? "Сохранить" : "Создать"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
