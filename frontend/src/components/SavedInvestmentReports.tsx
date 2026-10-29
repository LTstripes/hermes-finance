import { useQuery } from "@tanstack/react-query";
import { formatApiError } from "../api/client";
import { getInvestmentReports } from "../api/sourceReportPreview";
import { SourceReportResults } from "./SourceReportResults";

export function SavedInvestmentReports({ account, period }: { account?: string; period?: string }) {
  const query = useQuery({
    queryKey: ["source-returns", "investment-reports", account],
    queryFn: ({ signal }) => getInvestmentReports(account, signal),
    refetchOnMount: "always",
  });
  if (query.isPending || query.isFetching) return <p>Проверяем сохранённые PDF-связи…</p>;
  if (query.isError) return <p role="alert">{formatApiError(query.error)}</p>;
  return (
    <>
      {query.data.reports
        .filter(
          (p) =>
            !period || (p.interval?.period_kind === "monthly" && p.covered_to.startsWith(period)),
        )
        .map((proof) => (
          <details key={proof.proof_id}>
            <summary>
              Сохранённая сверка XML и PDF: {proof.source_account}, {proof.covered_from} —{" "}
              {proof.covered_to}
            </summary>
            {proof.status !== "current" || !proof.interval ? (
              <p>
                Свидетельство устарело: {proof.reason_codes.join(", ")}. Числа скрыты; нужна новая
                проверка оригиналов.
              </p>
            ) : (
              <SourceReportResults
                result={{
                  source_accounts: [proof.source_account],
                  pdf_period: proof.pdf_period,
                  pdf_payout_rows: proof.pdf_payout_rows,
                  comparison: [],
                  intervals: [proof.interval],
                }}
              />
            )}
            <p>Предварительный расчёт по источникам, без финансового Apply и изменения CLOSED.</p>
          </details>
        ))}
    </>
  );
}
