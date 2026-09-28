import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
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
 * reread and until the submitted set is proven one-to-one: exact
 * `natural_identity` + `material_fingerprint`, exact
 * `investment_cash_flow_id`/account/instrument in that month, and an active
 * `statement_link` pointing at the returned `applied_statement_event_id`.
 * Readiness must match the reread month lifecycle.
 */
export async function confirmStatementApply(
  monthId: number,
  verification: StatementApplyVerification,
): Promise<void> {
  const { submittedCount, selectedCount, items, expectations } = verification;
  if (items.length !== selectedCount || selectedCount !== submittedCount) {
    throw new Error("сервер подтвердил не весь отправленный набор строк");
  }
  if (expectations.length !== submittedCount) {
    throw new Error("ожидания отправленных строк не совпали с набором");
  }

  // Exact one-to-one identity proof: no missing, duplicated or foreign
  // natural_identity may be accepted as the submitted set.
  const expectationByIdentity = new Map(
    expectations.map((expectation) => [expectation.natural_identity ?? "", expectation]),
  );
  const seenIdentities = new Set<string>();
  for (const item of items) {
    const identity = item.natural_identity ?? "";
    if (seenIdentities.has(identity)) {
      throw new Error("результат содержит повторную natural_identity");
    }
    seenIdentities.add(identity);
    const expectation = expectationByIdentity.get(identity);
    if (!expectation) {
      throw new Error("результат импорта не сопоставляется с отправленными строками");
    }
    if (
      expectation.material_fingerprint == null ||
      item.material_fingerprint !== expectation.material_fingerprint
    ) {
      throw new Error("material_fingerprint результата не совпал с отправленной строкой");
    }
  }
  if (seenIdentities.size !== expectationByIdentity.size) {
    throw new Error("результат не содержит всех отправленных строк");
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
    // The cash flow must be linked to exactly this applied statement event:
    // an unrelated or retracted link is not proof of this import.
    const link = flow.statement_link;
    if (!link) {
      throw new Error(`у записи #${item.investment_cash_flow_id} нет связи со строкой отчёта`);
    }
    if (link.status !== "active") {
      throw new Error("связь записи со строкой отчёта не активна");
    }
    if (link.applied_statement_event_id !== item.applied_statement_event_id) {
      throw new Error("связь записи указывает на другое событие отчёта");
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
  const targetPeriod = useMemo(
    () => ({ year: month.year, month: month.month }),
    [month.year, month.month],
  );

  return (
    <div className={styles.statement}>
      <p className="muted">
        Строки PDF применяются в месяц, соответствующий дате события из отчёта. В этом рабочем окне
        доступны только строки за «{formatMonth(month.year, month.month)}»: строки других отчётных
        месяцев остаются видимыми, но не выбираются и не применяются. Перед показом успеха Hermes
        повторно загружает этот месяц, его инвестиционные потоки и готовность к закрытию; запись без
        активной связи со строкой отчёта не считается применённой.
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
        targetPeriod={targetPeriod}
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
