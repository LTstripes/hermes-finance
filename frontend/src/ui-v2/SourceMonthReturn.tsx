import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { formatApiError } from "../api/client";
import { getSourceMonthlyReturns } from "../api/sourceReturns";
import { formatMoney, formatPercent } from "../lib/format";
import { fromKopecks } from "../lib/money";

export function sourceReturnMoney(amount: number | null | undefined) {
  return amount == null
    ? "—"
    : Number.isSafeInteger(amount)
      ? formatMoney(fromKopecks(BigInt(amount)))
      : "Сумма вне точного диапазона отображения";
}

export function sourceReturnRate(fraction: string | null | undefined) {
  if (fraction == null) return "—";
  const match = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d{1,3}))?$/.exec(fraction);
  if (!match) return "—";
  const digits = match[2] + (match[3] ?? "");
  const point = match[2].length + 2 + Number(match[4] ?? 0);
  const percentage =
    point <= 0
      ? `0.${"0".repeat(-point)}${digits}`
      : point >= digits.length
        ? digits + "0".repeat(point - digits.length)
        : `${digits.slice(0, point)}.${digits.slice(point)}`;
  return formatPercent(match[1] + percentage.replace(/^0+(?=\d)/, ""), { digits: 2 });
}

export function SourceMonthReturn({ account, period }: { account: string; period: string }) {
  const result = useQuery({
    queryKey: ["source-returns", "monthly", account],
    queryFn: ({ signal }) => getSourceMonthlyReturns(account, signal),
    refetchOnMount: "always",
  });
  const row = result.data?.months.find((value) => value.closing_date.startsWith(period));
  const value = sourceReturnMoney(row?.growth_kopecks);
  const rate = sourceReturnRate(row?.modified_dietz_return);
  return (
    <section aria-label="Предварительная доходность месяца">
      <h3>Предварительная доходность месяца</h3>
      {result.isPending || result.isFetching ? (
        <p>Проверяем источники и актуальность…</p>
      ) : result.isError ? (
        <p role="status">{formatApiError(result.error)}</p>
      ) : !row ? (
        <p>Нет доказанных границ этого месяца.</p>
      ) : (
        <>
          <p>
            {value} · {rate} · Modified Dietz за период, приблизительно
          </p>
          <p>
            {row.opening_date} — {row.closing_date} · счёт источника {account}. Не финансовый
            результат.
          </p>
          <p>
            {row.assumptions_used ? "Потоки с допущениями. " : ""}
            {row.income_assumptions_used ? "Выплаты с допущениями. " : ""}
            {row.reason_codes.length
              ? `Причины NULL: ${row.reason_codes.join(", ")}`
              : "Состав источников проверен для предварительного расчёта."}
          </p>
          {result.data.source_proof?.status === "current" && (
            <p>
              Доказательство источника #{result.data.source_proof.proof_id} ·{" "}
              {result.data.source_proof.confirmed_at}
            </p>
          )}
          {result.data.source_proof?.status === "stale" && (
            <p>Подтверждение источника устарело; требуется новая проверка оригиналов.</p>
          )}
        </>
      )}
      <Link to={`/v2/capital/monthly-returns?${new URLSearchParams({ source_account: account })}`}>
        Доходность и подтверждение источников
      </Link>
    </section>
  );
}
