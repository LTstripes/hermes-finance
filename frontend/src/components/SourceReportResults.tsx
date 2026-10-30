import type { SourceMetric, SourceReportPreview } from "../api/sourceReportPreview";
import { fromKopecks } from "../lib/money";
import { formatSourceReturnRate } from "../lib/sourceReturnFormat";
import { Table, Td, Th } from "./ui";

const money = (value: string | null) =>
  value === null ? "Не определено" : `${fromKopecks(BigInt(value))} ₽`;
const rate = (metric: SourceMetric) =>
  metric.value === null ? "Не определено" : formatSourceReturnRate(metric.value);
const names: Record<string, string> = {
  account_fee: "Общесчётные комиссии",
  account_tax: "Общесчётный НДФЛ",
  unallocated_compensation: "Нераспределённая компенсация",
  repo_financing: "REPO: денежный результат",
};

export function SourceReportResults({
  result,
}: {
  result: Pick<
    SourceReportPreview,
    "pdf_period" | "source_accounts" | "pdf_payout_rows" | "comparison" | "intervals"
  >;
}) {
  return (
    <div role="status">
      <p>
        Период PDF: {result.pdf_period.covered_from} — {result.pdf_period.covered_to}. Выбранные
        счета: {result.source_accounts.join(", ")}. Фактических строк выплат PDF:{" "}
        {result.pdf_payout_rows}. Прогнозы сюда не входят.
      </p>
      <Table>
        <thead>
          <tr>
            <Th>Счёт</Th>
            <Th>Новые сделки</Th>
            <Th>Повторные</Th>
            <Th>Конфликты</Th>
            <Th>Несопоставленные / повторные денежные строки</Th>
          </tr>
        </thead>
        <tbody>
          {result.comparison.map((c) => (
            <tr key={`${c.source_account}:${c.source_sha256 ?? c.kind}`}>
              <Td>{c.source_account}</Td>
              <Td>{c.new_native_trades ?? "—"}</Td>
              <Td>{c.repeated_native_trades ?? "—"}</Td>
              <Td>{c.kind ?? c.conflicting_native_trades ?? "—"}</Td>
              <Td>
                {c.unmatched_money_occurrences ?? "—"} / {c.repeated_money_occurrences ?? "—"}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {result.comparison.flatMap((c) =>
        (c.conflicts ?? []).map((conflict) => (
          <p key={`${c.source_account}:${conflict.identity}`}>
            Конфликт сохранённой сделки: счёт {c.source_account}, {conflict.isin},{" "}
            {conflict.settlement_date}. Сохранённые данные не заменены.
          </p>
        )),
      )}
      <p>
        Несопоставленная денежная строка может быть новой или изменённой: без устойчивого ID
        совпадение не доказывается. Эта проверка не заменяет сохранённые факты.
      </p>
      {result.intervals.map((a) => {
        const totals = new Map<string, bigint>();
        for (const item of a.account_only)
          totals.set(item.kind, (totals.get(item.kind) ?? 0n) + BigInt(item.amount_kopecks));
        return (
          <section key={`${a.source_account}:${a.source_sha256}`}>
            <h3>
              Счёт {a.source_account}: {a.opening_date} — {a.closing_date}
            </h3>
            <p>
              {a.period_kind === "monthly" ? "Месяц" : "Исторический период"}. Рублёвый результат
              счёта: {money(a.pnl.value)}. Доходность за период (Modified Dietz, оценка):{" "}
              {rate(a.modified_dietz)}. Денежно-взвешенная за период: {rate(a.xirr_period)}. XIRR
              годовых: {rate(a.xirr_annualized)}.
            </p>
            {a.pnl.value === null && a.known_subtotal?.value != null && (
              <p>
                Известная часть по денежным операциям и оценке счёта:{" "}
                {money(a.known_subtotal.value)}. Смысл прочих движений имущества не установлен; это
                не полный результат.
              </p>
            )}
            {!!a.source_advisories?.length && (
              <p>
                Дополнительные разделы исходного XML не получили финансовой приёмки:{" "}
                {a.source_advisories.join(", ")}. Расчёт по разобранным операциям остаётся
                предварительным.
              </p>
            )}
            {!!a.unresolved_movements?.length && (
              <p>
                Требуют разбора движения бумаг: {a.unresolved_movements.length}. Без их смысла, дат
                и стоимости полные показатели счёта и затронутых бумаг не определены.
              </p>
            )}
            <p>
              Сопоставлено денежных строк выплат: {a.reconciliation.linked_payout_occurrences} из{" "}
              {a.reconciliation.xml_payout_occurrences}. Две строки одной выплаты могут
              соответствовать одной строке PDF.
            </p>
            {a.reason_codes.length > 0 && (
              <p>Ограничения результата счёта: {a.reason_codes.join(", ")}</p>
            )}
            <p>
              Проверка денежных остатков: {money(a.reconciliation.cash_delta_kopecks)}. расхождение
              конечной стоимости с PDF: {money(a.reconciliation.pdf_closing_delta_kopecks)}.
            </p>
            <Table>
              <thead>
                <tr>
                  <Th>ISIN</Th>
                  <Th>Результат, ₽</Th>
                  <Th>Modified Dietz за период</Th>
                  <Th>Денежно-взвешенная за период</Th>
                  <Th>XIRR годовых</Th>
                </tr>
              </thead>
              <tbody>
                {a.instruments.map((s) => (
                  <tr key={s.isin}>
                    <Td>{s.isin}</Td>
                    <Td>
                      {money(s.pnl.value)}
                      {s.pnl.value === null && s.known_subtotal.value !== null && (
                        <div>Известная часть: {money(s.known_subtotal.value)}</div>
                      )}
                    </Td>
                    <Td>{rate(s.modified_dietz)}</Td>
                    <Td>{rate(s.xirr_period)}</Td>
                    <Td>{rate(s.xirr_annualized)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <p>
              По инструментам показаны связанные денежные операции и стоимость. Общесчётные суммы
              отдельно, без произвольного распределения:{" "}
              {Array.from(
                totals,
                ([kind, total]) => `${names[kind] ?? kind}: ${money(String(total))}`,
              ).join("; ") || "не наблюдались"}
              .
            </p>
            {a.instruments
              .filter((s) => s.reason_codes.length)
              .map((s) => (
                <p key={s.isin}>
                  {s.isin}: {s.reason_codes.join(", ")}. Известная часть:{" "}
                  {money(s.known_subtotal.value)}.
                </p>
              ))}
            {a.unallocated_payouts.length > 0 && (
              <p>
                Требуют решения: {a.unallocated_payouts.length} денежных строк выплат. Они учтены в
                денежном остатке счёта, связь с бумагой не подтверждена.
              </p>
            )}
            {(a.exceptions ?? []).map((item) => (
              <p key={item.reference}>
                Требует разбора: {item.date}, {item.classification}, {money(item.amount_kopecks)}
                {item.currency !== "RUB"
                  ? ` (валюта источника ${item.currency}; рублёвая оценка неизвестна)`
                  : ""}
                .{item.registration ? ` Регистрация ${item.registration}.` : ""}
              </p>
            ))}
          </section>
        );
      })}
    </div>
  );
}
