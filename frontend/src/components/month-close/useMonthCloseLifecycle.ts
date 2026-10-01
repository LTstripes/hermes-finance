import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { formatApiError } from "../../api/client";
import { useMonthCloseWorkflow, type MonthCloseWorkflow } from "../../api/monthCloseWorkflow";
import { closeMonth, reopenMonth } from "../../api/months";
import type { ReportingMonth, ReportingMonthStatus } from "../../api/types";
import { queryKeys } from "../../queryClient";

type Lifecycle = "close" | "reopen";
const WORKFLOW_CONTRACT_VERSION = "monthly_close_workflow_v1";

function assertLifecycleWorkflowIdentity(
  workflow: MonthCloseWorkflow,
  expectedMonthId: number,
  expectedPeriod?: Pick<ReportingMonth, "year" | "month">,
): MonthCloseWorkflow {
  if (workflow.contract_version !== WORKFLOW_CONTRACT_VERSION) {
    throw new Error("Состояние закрытия имеет неподдерживаемую версию. Действие отменено.");
  }
  if (
    workflow.month.id !== expectedMonthId ||
    (expectedPeriod &&
      (workflow.month.year !== expectedPeriod.year ||
        workflow.month.month !== expectedPeriod.month))
  ) {
    throw new Error("Получено состояние другого месяца. Действие отменено.");
  }
  const periodMatches = (period: Pick<ReportingMonth, "id" | "year" | "month">) =>
    period.id === workflow.month.id &&
    period.year === workflow.month.year &&
    period.month === workflow.month.month;
  if (
    (workflow.final_review.available &&
      (!periodMatches(workflow.final_review.month_header) ||
        workflow.final_review.month_header.status !== workflow.month.status)) ||
    (workflow.outlook && !periodMatches(workflow.outlook.source_month))
  ) {
    throw new Error("Получено состояние другого месяца. Действие отменено.");
  }
  return workflow;
}

function assertPersistedMonthIdentity(
  persisted: ReportingMonth,
  expectedMonthId: number,
  expectedStatus: ReportingMonthStatus,
  expectedPeriod?: Pick<ReportingMonth, "year" | "month">,
) {
  if (
    persisted.id !== expectedMonthId ||
    (expectedPeriod &&
      (persisted.year !== expectedPeriod.year || persisted.month !== expectedPeriod.month))
  ) {
    throw new Error("Изменение подтверждено для другого месяца. Новое состояние не доказано.");
  }
  if (persisted.status !== expectedStatus) {
    throw new Error("Новое состояние месяца не подтверждено.");
  }
}

/**
 * One shared, non-optimistic lifecycle for both the v1 and native v2 shells.
 * The server workflow stays authoritative: refetch before the dialog, refetch
 * again before the command, verify persisted status, invalidate, then refetch.
 */
export function useMonthCloseLifecycle(
  monthId: number | null,
  expectedPeriod?: Pick<ReportingMonth, "year" | "month">,
) {
  const workflowQuery = useMonthCloseWorkflow(monthId);
  const queryClient = useQueryClient();
  const [pendingLifecycle, setPendingLifecycle] = useState<Lifecycle | null>(null);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [preparingClose, setPreparingClose] = useState(false);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const { refetch } = workflowQuery;
  const identityKey = `${monthId}:${expectedPeriod?.year}:${expectedPeriod?.month}`;
  const currentIdentity = useRef(identityKey);
  const previousIdentity = useRef(identityKey);
  currentIdentity.current = identityKey;
  useEffect(() => {
    if (previousIdentity.current === identityKey) return;
    previousIdentity.current = identityKey;
    setPendingLifecycle(null);
    setLifecycleError(null);
  }, [identityKey]);

  useEffect(() => {
    function refetchOnFocus() {
      void refetch();
    }
    window.addEventListener("focus", refetchOnFocus);
    return () => window.removeEventListener("focus", refetchOnFocus);
  }, [refetch]);

  async function refetchAuthoritativeWorkflow(): Promise<MonthCloseWorkflow> {
    if (monthId === null) throw new Error("Месяц для действия не выбран.");
    const result = await refetch();
    if (currentIdentity.current !== identityKey) {
      throw new Error("Выбранный месяц изменился. Действие отменено.");
    }
    if (result.error) throw result.error;
    if (!result.data) throw new Error("Актуальное состояние месяца не получено.");
    return assertLifecycleWorkflowIdentity(result.data, monthId, expectedPeriod);
  }

  function closeIsAllowed(current: MonthCloseWorkflow): boolean {
    return current.month.status === "draft" && current.readiness.can_close;
  }

  async function prepareClose() {
    if (!workflowQuery.data || preparingClose || lifecycleBusy) return;
    setPreparingClose(true);
    setLifecycleError(null);
    try {
      const latest = await refetchAuthoritativeWorkflow();
      if (latest.month.status === "closed") {
        setLifecycleError("Месяц уже закрыт в другой вкладке. Состояние обновлено.");
      } else if (!closeIsAllowed(latest)) {
        setLifecycleError(
          "Состояние готовности изменилось. Проверь актуальные блокеры и предупреждения.",
        );
      } else {
        setPendingLifecycle("close");
      }
    } catch (error) {
      setLifecycleError(formatApiError(error));
    } finally {
      setPreparingClose(false);
    }
  }

  function requestReopen() {
    if (!workflowQuery.data || lifecycleBusy) return;
    setLifecycleError(null);
    setPendingLifecycle("reopen");
  }

  async function confirmLifecycle() {
    if (!pendingLifecycle || !workflowQuery.data || lifecycleBusy || monthId === null) return;
    setLifecycleBusy(true);
    setLifecycleError(null);
    try {
      const latest = await refetchAuthoritativeWorkflow();
      if (pendingLifecycle === "close" && !closeIsAllowed(latest)) {
        setPendingLifecycle(null);
        setLifecycleError(
          latest.month.status === "closed"
            ? "Месяц уже закрыт в другой вкладке. Состояние обновлено."
            : "Состояние готовности изменилось. Проверь актуальные блокеры и предупреждения.",
        );
        return;
      }
      if (pendingLifecycle === "reopen" && latest.month.status !== "closed") {
        setPendingLifecycle(null);
        setLifecycleError("Месяц уже открыт для редактирования. Состояние обновлено.");
        return;
      }

      const persisted =
        pendingLifecycle === "close" ? await closeMonth(monthId) : await reopenMonth(monthId);
      const expectedStatus = pendingLifecycle === "close" ? "closed" : "draft";
      assertPersistedMonthIdentity(persisted, monthId, expectedStatus, expectedPeriod);

      await queryClient.invalidateQueries({ queryKey: queryKeys.months });
      await queryClient.invalidateQueries({ queryKey: queryKeys.dashboard(monthId) });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.monthCloseWorkflow(monthId),
        refetchType: "none",
      });
      const refreshed = await refetchAuthoritativeWorkflow();
      if (refreshed.month.status !== expectedStatus) {
        throw new Error("Актуальное состояние месяца не совпало с полученными данными.");
      }
      setPendingLifecycle(null);
    } catch (error) {
      setPendingLifecycle(null);
      setLifecycleError(formatApiError(error));
      try {
        await refetchAuthoritativeWorkflow();
      } catch {
        // Query state retains the authoritative failure, including a possible 404.
      }
    } finally {
      setLifecycleBusy(false);
    }
  }

  return {
    cancelLifecycle: () => setPendingLifecycle(null),
    confirmLifecycle,
    lifecycleBusy,
    lifecycleError,
    pendingLifecycle,
    prepareClose,
    preparingClose,
    requestReopen,
    workflowQuery,
  };
}
