import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import { listAccounts } from "../api/accounts";
import { listInstruments } from "../api/instruments";
import { listInvestmentFlows } from "../api/investmentFlows";
import { getCloseReadiness, getMonth } from "../api/months";
import type { Account, Instrument, ReportingMonth } from "../api/types";
import {
  StatementImportPanel,
  type StatementApplyVerification,
} from "../components/StatementImportPanel";
import type { AlfaStatementTransientOutcome } from "../components/month-close/statementOutcome";
import { formatMonth } from "../lib/format";
import { queryKeys } from "../queryClient";
import styles from "./UiV2PayoutForecast.module.css";

/**
 * Authoritative post-apply readback for one native statement import (#567).
 *
 * Nothing is published as a success until the exact explicit month has been
 * reread and every applied `investment_cash_flow_id` is proven to exist in
 * that month with the account/instrument identity the selection exposed, and
 * until readiness is proven against the reread month lifecycle.
 */
export async function confirmStatementApply(
  monthId: number,
  verification: StatementApplyVerification,
): Promise<void> {
  const { submittedCount, selectedCount, items, expectations } = verification;
  if (items.length !== selectedCount || selectedCount !== submittedCount) {
    throw new Error("сервер подтвердил не весь отправленный набор строк");
  }

  const [rereadMonth, flows, readiness] = await Promise.all([
    getMonth(monthId),
    listInvestmentFlows(monthId),
    getCloseReadiness(monthId),
  ]);

  if (rereadMonth.id !== monthId) {
    throw new Error("получен другой отчётный месяц");
  }
  if (flows.some((flow) => flow.reporting_month_id !== monthId)) {
    throw new Error("повторная загрузка месяца вернула запись другого месяца");
  }

  const flowById = new Map(flows.map((flow) => [flow.id, flow]));
  const expectationByIdentity = new Map(
    expectations.map((expectation) => [expectation.natural_identity ?? "", expectation]),
  );

  for (const item of items) {
    const flow = flowById.get(item.investment_cash_flow_id);
    if (!flow) {
      throw new Error(
        `применённая запись #${item.investment_cash_flow_id} не найдена в повторно загруженном месяце`,
      );
    }
    const expectation = expectationByIdentity.get(item.natural_identity ?? "");
    if (!expectation) {
      throw new Error("результат импорта не сопоставляется с отправленными строками");
    }
    if (
      flow.account_id !== expectation.expected_hermes_account_id ||
      flow.instrument_id !== expectation.expected_hermes_instrument_id
    ) {
      throw new Error("сохранённая запись не совпала с ожидаемыми счётом и инструментом");
    }
  }

  if (
    readiness.year !== rereadMonth.year ||
    readiness.month !== rereadMonth.month ||
    readiness.snapshot_date !== rereadMonth.snapshot_date ||
    readiness.status !== rereadMonth.status
  ) {
    throw new Error("готовность к закрытию не совпала с повторно загруженным месяцем");
  }
}

export function UiV2StatementImportSection({
  closeStepActive,
  month,
  onApplyingChange,
  onOutcome,
  outcome,
  returnPath,
}: {
  closeStepActive: boolean;
  month: ReportingMonth;
  onApplyingChange: (applying: boolean) => void;
  onOutcome: (outcome: AlfaStatementTransientOutcome | null) => void;
  outcome: AlfaStatementTransientOutcome | null;
  returnPath: string | null;
}) {
  const client = useQueryClient();
  const accountsQuery = useQuery({
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
  });
  const instrumentsQuery = useQuery({
    queryKey: queryKeys.instruments,
    queryFn: ({ signal }) => listInstruments({ active: true }, signal),
  });

  const accounts: Account[] = accountsQuery.data ?? [];
  const instruments: Instrument[] = instrumentsQuery.data ?? [];

  return (
    <div className={styles.statement}>
      <p className="muted">
        Строки PDF применяются в месяц, соответствующий дате события из отчёта. Перед показом успеха
        Hermes повторно загружает выбранный месяц «{formatMonth(month.year, month.month)}», его
        инвестиционные потоки и готовность к закрытию; строка, попавшая в другой месяц, не считается
        подтверждённой.
      </p>
      <StatementImportPanel
        accounts={accounts}
        instruments={instruments}
        readOnly={month.status === "closed"}
        onApplied={async () => {
          await client.invalidateQueries({ refetchType: "none" });
        }}
        onApplyingChange={onApplyingChange}
        onInstrumentsChange={(next) => client.setQueryData(queryKeys.instruments, next)}
        onOutcome={onOutcome}
        verifyApplied={(verification) => confirmStatementApply(month.id, verification)}
      />
      {closeStepActive && returnPath && outcome ? (
        <div className="statement-import__wizard-outcome" role="status">
          <div>
            <strong>Результат проверки PDF Alfa</strong>
            <p>
              {outcome.kind === "applied"
                ? `Выбранные строки применены: ${outcome.selectedCount}. Сохранённые факты будут повторно показаны в закрытии после обновления.`
                : "Подходящих выплат не найдено. Этот результат не сохранён и не отмечает шаг выполненным."}
            </p>
          </div>
          <Link
            className="btn btn--secondary"
            state={{ alfaStatementOutcome: outcome }}
            to={returnPath}
          >
            Продолжить к закрытию
          </Link>
        </div>
      ) : null}
    </div>
  );
}
