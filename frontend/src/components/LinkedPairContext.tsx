import type { Account, DashboardLinkedPair, DebtEntry, MoneyValue } from "../api/types";
import { formatMoney } from "../lib/format";
import { moneyAmount } from "../lib/money";
import { Badge, DataValue, EmptyState, ErrorState, Panel } from "./ui";

export type PairFact = {
  debtId: number;
  debtName: string;
  accountName: string;
  accountBalance: MoneyValue | null;
  debtBalance: MoneyValue | null;
  netContribution: MoneyValue | null;
  contextAvailable: boolean;
};

type Props = {
  accounts: Account[];
  debts: DebtEntry[];
  error?: string | null;
  pairs: DashboardLinkedPair[] | null;
  label?: string;
  title?: string;
};

function fallbackFact(debt: DebtEntry, accountName: string): PairFact {
  return {
    debtId: debt.id,
    debtName: debt.name,
    accountName,
    accountBalance: null,
    debtBalance: debt.current_balance,
    netContribution: null,
    contextAvailable: false,
  };
}

/**
 * Canonical linked-pair facts: backend pair facts first, then a fail-closed
 * fallback for a persisted link whose asset fact is missing. Shared so another
 * surface cannot invent a different A / D / A − D reading.
 */
export function buildLinkedPairFacts(
  pairs: DashboardLinkedPair[] | null,
  debts: DebtEntry[],
  accounts: Account[],
): PairFact[] {
  const accountNames = new Map(accounts.map((account) => [account.id, account.name]));
  const linkedDebts = debts.filter((debt) => debt.linked_account_id != null);
  const facts: PairFact[] = [];
  const seenDebtIds = new Set<number>();

  for (const pair of pairs ?? []) {
    facts.push({
      debtId: pair.debt_id,
      debtName: pair.debt_name,
      accountName: pair.account_name || accountNames.get(pair.account_id) || "Счёт не найден",
      accountBalance: pair.account_balance,
      debtBalance: pair.debt_balance,
      netContribution: pair.net_contribution,
      contextAvailable: true,
    });
    seenDebtIds.add(pair.debt_id);
  }

  for (const debt of linkedDebts) {
    if (seenDebtIds.has(debt.id)) continue;
    facts.push(
      fallbackFact(debt, accountNames.get(debt.linked_account_id as number) ?? "Счёт не найден"),
    );
  }

  return facts;
}

export function pairFactNote(fact: PairFact): string {
  if (!fact.contextAvailable) {
    return "Связь сохранена, но факт актива за выбранный месяц недоступен. A и A − D не подменяются нулём.";
  }
  return "A и D уже входят в общую сводку. Чистый вклад — пояснение пары; долг не вычитается повторно.";
}

export function LinkedPairContext({
  accounts,
  debts,
  error = null,
  pairs,
  label = "Связь",
  title = "Контекст связанных пар",
}: Props) {
  const facts = buildLinkedPairFacts(pairs, debts, accounts);
  const hasUnavailableFact = facts.some((fact) => !fact.contextAvailable);

  return (
    <div data-testid="linked-pair-context">
      <Panel className="linked-pair-context" label={label} title={title}>
        <p className="linked-pair-context__intro">
          Связь показывает две стороны одной позиции: актив A и долг D остаются видимыми, а A − D —
          её экономический вклад. Это пояснение, а не дополнительное вычитание долга.
        </p>
        {error && facts.length > 0 ? (
          <div className="inline-alert inline-alert--warn" role="alert">
            {error}
          </div>
        ) : null}
        {pairs === null && facts.length === 0 ? (
          <ErrorState
            description={
              error ?? "Для связанных пар не удалось загрузить данные выбранного месяца."
            }
            inline
            title="Контекст пары недоступен"
          />
        ) : facts.length === 0 ? (
          <EmptyState
            description="В выбранном месяце счета и кредитные долги не связаны."
            inline
            title="Связанных пар нет"
          />
        ) : (
          <div className="linked-pair-context__list">
            {hasUnavailableFact ? (
              <div className="inline-alert inline-alert--warn" role="status">
                Для части связей не хватает факта актива за выбранный месяц. Недоступные суммы
                остаются «—».
              </div>
            ) : null}
            {facts.map((fact) => (
              <article
                className={`linked-pair-card${fact.contextAvailable ? "" : " linked-pair-card--unavailable"}`}
                data-testid={`linked-pair-${fact.debtId}`}
                key={fact.debtId}
              >
                <div className="linked-pair-card__heading">
                  <div className="linked-pair-card__names">
                    <strong>{fact.accountName}</strong>
                    <span className="muted">↔ {fact.debtName}</span>
                  </div>
                  <Badge tone={fact.contextAvailable ? "ok" : "unknown"}>
                    {fact.contextAvailable ? "Связано" : "Контекст неполный"}
                  </Badge>
                </div>
                <div className="linked-pair-card__values">
                  <DataValue
                    label="Актив A · брутто"
                    value={formatMoney(moneyAmount(fact.accountBalance))}
                  />
                  <DataValue
                    label="Связанный долг D"
                    value={formatMoney(moneyAmount(fact.debtBalance))}
                  />
                  <DataValue
                    label="Чистый вклад A − D"
                    value={formatMoney(moneyAmount(fact.netContribution))}
                  />
                </div>
                <p className="linked-pair-card__note">{pairFactNote(fact)}</p>
              </article>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
