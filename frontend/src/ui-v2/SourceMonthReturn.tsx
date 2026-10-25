import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { formatApiError } from "../api/client";
import { getSourceMonthlyReturns } from "../api/sourceReturns";
import { formatMoney } from "../lib/format";
import { fromKopecks } from "../lib/money";
import { formatSourceReturnRate } from "../lib/sourceReturnFormat";
import { Reasons } from "./SourceInstrumentDetail";

export function sourceReturnMoney(amount: number | null | undefined) {
  return amount == null
    ? "—"
    : Number.isSafeInteger(amount)
      ? formatMoney(fromKopecks(BigInt(amount)))
      : "Сумма вне точного диапазона отображения";
}

export function SourceMonthReturn({ account, period }: { account: string; period: string }) {
  const [year, month] = period.split("-").map(Number);
  const opening = new Date(Date.UTC(year, month - 1, 0)).toISOString().slice(0, 10);
  const closing = new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
  const result = useQuery({
    queryKey: ["source-returns", "monthly", account],
    queryFn: async ({ signal }) => {
      const value = await getSourceMonthlyReturns(account, signal);
      if (
        value.source_account !== account ||
        value.authority !== "provisional" ||
        value.financial_authority !== "none"
      )
        throw new Error("Счёт или полномочия предварительного расчёта не подтверждены.");
      return value;
    },
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
  });
  const row = result.data?.months.find(
    (value) => value.opening_date === opening && value.closing_date === closing,
  );
  const value = sourceReturnMoney(row?.growth_kopecks);
  const rate = formatSourceReturnRate(row?.modified_dietz_return);
  const qualityCodes = [...new Set([...(row?.reason_codes ?? []), ...(row?.flags ?? [])])];
  return (
    <section aria-label="Предварительная доходность месяца">
      <h3>Предварительная доходность месяца</h3>
      {result.isPending || result.isFetching ? (
        <p>Проверяем источники и актуальность…</p>
      ) : result.isError ? (
        <p role="status">{formatApiError(result.error)}</p>
      ) : !row ? (
        <p>
          Доходность недоступна: нет доказанных границ этого месяца — EOD {opening} и {closing}.
          Нужен полный месячный оригинал; историческая или промежуточная выписка его не заменяет.
        </p>
      ) : (
        <>
          <p>
            {row.growth_kopecks === null ? "Результат недоступен" : value} ·{" "}
            {row.modified_dietz_return === null ? "Доходность недоступна" : rate} · Modified Dietz
            за период, приблизительно
          </p>
          {row.missing_endpoint && (
            <p>
              Нужны подтверждённые EOD {opening} и {closing}; отсутствующая граница не равна нулю.
            </p>
          )}
          <details>
            <summary>Подробнее о предварительном расчёте</summary>{" "}
            <p>
              {row.opening_date} — {row.closing_date} · счёт источника {account}. Не финансовый
              результат.
            </p>
            {qualityCodes.length ? (
              <>
                {qualityCodes.includes("seam_mismatch") && (
                  <p>Остатки соседних месяцев различаются</p>
                )}
                <Reasons codes={qualityCodes.filter((code) => code !== "seam_mismatch")} />
              </>
            ) : (
              <p>Дополнительных предупреждений нет.</p>
            )}
            {(row.assumptions_used || row.income_assumptions_used) && (
              <p>
                {row.assumptions_used ? "Потоки с допущениями. " : ""}
                {row.income_assumptions_used ? "Выплаты с допущениями. " : ""}
              </p>
            )}
            {result.data.source_proof?.status === "current" && (
              <p>
                Доказательство источника #{result.data.source_proof.proof_id} ·{" "}
                {result.data.source_proof.confirmed_at}
              </p>
            )}
            {result.data.source_proof?.status === "stale" && (
              <p>Подтверждение источника устарело; требуется новая проверка оригиналов.</p>
            )}
          </details>
        </>
      )}
      <details>
        <summary>Источники расчёта</summary>
        <Link
          to={`/v2/capital/monthly-returns?${new URLSearchParams({ source_account: account })}`}
        >
          Доходность и подтверждение источников
        </Link>
      </details>
    </section>
  );
}
