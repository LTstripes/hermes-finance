import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useEffectEvent, useId, useRef, useState } from "react";
import { ApiClientError, formatApiError } from "../../api/client";
import {
  closeIntentionallyEmptyMonth,
  getCloseReadiness,
  getIntentionalEmptyCloseReceipt,
  getMonth,
} from "../../api/months";
import type {
  EmptyCloseIdentity,
  IntentionalEmptyCloseCommand,
  IntentionalEmptyCloseOption,
  IntentionalEmptyCloseReceipt,
  ReportingMonth,
} from "../../api/types";
import { formatDate, formatMonth } from "../../lib/format";
import { queryKeys } from "../../queryClient";
import { Button, ConfirmDialog, Field } from "../ui";

const COMMAND = "close_intentionally_empty_manual_month";
const POLICY = "intentional_empty_manual_month_v1";
const identityFields = ["month_id", "year", "month", "snapshot_date", "expected_identity"] as const;

function sameIdentity(a: EmptyCloseIdentity, b: EmptyCloseIdentity) {
  return identityFields.every((field) => a[field] === b[field]);
}

/** Only the server can offer the exception; a template/UNKNOWN is never an actual. */
export function IntentionalEmptyClose({
  month,
  available,
  onPendingChange,
}: {
  month: Pick<ReportingMonth, "id" | "year" | "month" | "snapshot_date">;
  available: boolean;
  onPendingChange?: (pending: boolean) => void;
}) {
  const client = useQueryClient();
  const reasonId = useId();
  const storageKey = `hermes:empty-close:v1:${month.id}`;
  const [option, setOption] = useState<IntentionalEmptyCloseOption | null>(null);
  const [reason, setReason] = useState("");
  const [checked, setChecked] = useState(false);
  const [pending, setPending] = useState<IntentionalEmptyCloseCommand | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const lock = useRef(false);
  const blocked = useRef(false);
  const active = useRef(true);

  function matchesPeriod(value: EmptyCloseIdentity) {
    return value.month_id === month.id && value.year === month.year && value.month === month.month;
  }

  async function readOption() {
    const readiness = await getCloseReadiness(month.id);
    const offered = readiness.intentional_empty_close;
    const blockers = readiness.items.filter((item) => item.severity === "hard_blocker");
    if (
      !offered?.eligible ||
      offered.command !== COMMAND ||
      offered.policy_version !== POLICY ||
      !matchesPeriod(offered) ||
      offered.snapshot_date !== month.snapshot_date ||
      !/^[a-f0-9]{64}$/.test(offered.expected_identity) ||
      readiness.year !== month.year ||
      readiness.month !== month.month ||
      readiness.snapshot_date !== offered.snapshot_date ||
      readiness.status !== "draft" ||
      readiness.source !== "manual" ||
      readiness.can_close ||
      blockers.length !== 1 ||
      blockers[0].code !== "empty_manual_month"
    )
      throw new Error(
        "Сервер не подтвердил возможность закрыть этот период как пустой. Проверь готовность.",
      );
    return offered;
  }

  async function refresh() {
    await Promise.all([
      client.invalidateQueries({ queryKey: queryKeys.months }),
      client.invalidateQueries({ queryKey: queryKeys.monthCloseWorkflow(month.id) }),
      client.invalidateQueries({ queryKey: queryKeys.dashboard(month.id) }),
    ]);
  }

  function assertReceipt(
    receipt: IntentionalEmptyCloseReceipt,
    command: IntentionalEmptyCloseCommand,
  ) {
    if (
      !receipt ||
      !sameIdentity(receipt, command) ||
      receipt.request_id !== command.request_id ||
      receipt.reason !== command.reason ||
      receipt.policy_version !== POLICY ||
      receipt.result_status !== "closed" ||
      !Number.isFinite(Date.parse(receipt.closed_at))
    ) {
      throw new Error(
        "Квитанция не совпала с отправленным намерением. Повторная команда заблокирована.",
      );
    }
  }

  async function readResult(command: IntentionalEmptyCloseCommand) {
    // A receipt is historical. Always reread the current month as well, including after Reopen.
    const receipt = await getIntentionalEmptyCloseReceipt(month.id, command.request_id);
    assertReceipt(receipt, command);
    const current = await getMonth(month.id);
    if (
      current.id !== month.id ||
      current.year !== command.year ||
      current.month !== command.month ||
      !["draft", "closed"].includes(current.status)
    ) {
      throw new Error(
        "Текущее состояние периода не подтверждено. Повтори только проверку результата.",
      );
    }
    await refresh();
    sessionStorage.removeItem(storageKey);
    blocked.current = false;
    setPending(null);
    setError(null);
    setOutcome(
      current.status === "closed" && current.snapshot_date === command.snapshot_date
        ? "Закрытие пустого периода подтверждено квитанцией и повторным чтением месяца."
        : "Историческая квитанция закрытия найдена, но состояние или снимок месяца изменились. Повторное закрытие не выполнялось.",
    );
  }

  async function recover(command: IntentionalEmptyCloseCommand) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      await readResult(command);
    } catch (failure) {
      setError(
        `Результат пока не подтверждён. Доступна только GET-проверка: ${formatApiError(failure)}`,
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  const resumeSaved = useEffectEvent(() => {
    try {
      const saved = sessionStorage.getItem(storageKey);
      if (!saved) return;
      blocked.current = true;
      const command = JSON.parse(saved) as IntentionalEmptyCloseCommand;
      if (
        command.command !== COMMAND ||
        command.policy_version !== POLICY ||
        !matchesPeriod(command) ||
        typeof command.reason !== "string" ||
        !command.reason.trim() ||
        typeof command.request_id !== "string" ||
        !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(command.request_id) ||
        typeof command.expected_identity !== "string" ||
        !/^[a-f0-9]{64}$/.test(command.expected_identity)
      ) {
        throw new Error("Сохранённое намерение не подтверждено. Новая команда заблокирована.");
      }
      setPending(command);
      void recover(command);
    } catch (failure) {
      blocked.current = true;
      setError(formatApiError(failure));
    }
  });
  // The parent keys this component by exact selected period. Recovery never sends a POST.
  useEffect(() => {
    active.current = true;
    resumeSaved();
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    onPendingChange?.(pending !== null || blocked.current);
  }, [pending, onPendingChange]);

  async function prepare() {
    if (lock.current || blocked.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    setOutcome(null);
    try {
      setOption(await readOption());
      setReason("");
      setChecked(false);
    } catch (failure) {
      setError(formatApiError(failure));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  async function confirm() {
    if (
      !option ||
      !reason.trim() ||
      reason.length > 2000 ||
      !checked ||
      lock.current ||
      blocked.current
    )
      return;
    lock.current = true;
    setBusy(true);
    setError(null);
    let sent = false;
    try {
      const fresh = await readOption();
      if (!active.current) return;
      if (!sameIdentity(option, fresh))
        throw new Error("Период изменился. Открой подтверждение заново.");
      const command: IntentionalEmptyCloseCommand = {
        command: COMMAND,
        policy_version: POLICY,
        request_id: crypto.randomUUID(),
        reason,
        month_id: option.month_id,
        year: option.year,
        month: option.month,
        snapshot_date: option.snapshot_date,
        expected_identity: option.expected_identity,
      };
      // Persist before dispatch so Back/Reload cannot enable a second intent after a lost ACK.
      sessionStorage.setItem(storageKey, JSON.stringify(command));
      blocked.current = true;
      setPending(command);
      setOption(null);
      sent = true;
      try {
        const ack = await closeIntentionallyEmptyMonth(month.id, command);
        assertReceipt(ack, command);
      } catch (failure) {
        // Only a typed definitive rejection permits a new confirmation. Network/5xx/unknown ACK
        // retain the immutable intent, even when the first receipt GET is still 404.
        if (
          failure instanceof ApiClientError &&
          [409, 422, 404].includes(failure.status) &&
          failure.code !== "http_error"
        ) {
          sessionStorage.removeItem(storageKey);
          blocked.current = false;
          setPending(null);
          throw failure;
        }
      }
      await readResult(command);
    } catch (failure) {
      setOption(null);
      setError(
        `${sent && blocked.current ? "Результат не подтверждён. Повтори только GET-проверку. " : ""}${formatApiError(failure)}`,
      );
      await refresh();
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  return (
    <section aria-label="Намеренно пустой период">
      {available && !pending && !blocked.current ? (
        <Button disabled={busy} onClick={() => void prepare()} type="button" variant="secondary">
          Закрыть намеренно пустой период…
        </Button>
      ) : null}
      {pending ? (
        <p>
          Намерение отправлено для {formatMonth(pending.year, pending.month)} · снимок{" "}
          {formatDate(pending.snapshot_date)}. Повторная отправка заблокирована.
        </p>
      ) : null}
      {pending ? (
        <Button disabled={busy} onClick={() => void recover(pending)} type="button">
          Проверить результат закрытия
        </Button>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
      {outcome ? <p role="status">{outcome}</p> : null}
      <ConfirmDialog
        open={option !== null}
        busy={busy}
        danger
        title="Закрыть намеренно пустой период?"
        description={
          option
            ? `${formatMonth(option.year, option.month)} · ID ${option.month_id} · снимок ${formatDate(option.snapshot_date)}. Причина будет сохранена в аудите. Сервер повторно проверит период и все блокеры.`
            : ""
        }
        confirmLabel="Подтвердить пустой Close"
        confirmDisabled={!reason.trim() || reason.length > 2000 || !checked}
        onCancel={() => setOption(null)}
        onConfirm={() => void confirm()}
      >
        <Field label="Причина пустого периода" htmlFor={reasonId}>
          <textarea
            id={reasonId}
            className="input"
            rows={3}
            maxLength={2000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            disabled={busy}
          />
        </Field>
        <label>
          <input
            type="checkbox"
            checked={checked}
            onChange={(event) => setChecked(event.target.checked)}
            disabled={busy}
          />
          Подтверждаю точный период и намеренное отсутствие фактов
        </label>
        <p>Записи с нулевыми суммами не создаются. Остальные блокеры закрытия сохраняются.</p>
      </ConfirmDialog>
    </section>
  );
}
