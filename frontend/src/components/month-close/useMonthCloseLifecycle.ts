import { useEffect, useState } from "react";
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
): MonthCloseWorkflow {
  if (workflow.contract_version !== WORKFLOW_CONTRACT_VERSION) {
    throw new Error("Состояние закрытия имеет неподдерживаемую версию. Действие отменено.");
  }
  if (workflow.month.id !== expectedMonthId) {
    throw new Error("Получено состояние другого месяца. Действие отменено.");
  }
  return workflow;
}

function assertPersistedMonthIdentity(
  persisted: ReportingMonth,
  expectedMonthId: number,
  expectedStatus: ReportingMonthStatus,
) {
  if (persisted.id !== expectedMonthId) {
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
export function useMonthCloseLifecycle(monthId: number | null) {
  const workflowQuery = useMonthCloseWorkflow(monthId);
  const queryClient = useQueryClient();
  const [pendingLifecycle, setPendingLifecycle] = useState<Lifecycle | null>(null);
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const [preparingClose, setPreparingClose] = useState(false);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const { refetch } = workflowQuery;

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
    if (result.error) throw result.error;
    if (!result.data) throw new Error("Актуальное состояние месяца не получено.");
    return assertLifecycleWorkflowIdentity(result.data, monthId);
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
      assertPersistedMonthIdentity(persisted, monthId, expectedStatus);

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
