import { type AccountLink, dateLabel, type Period, periodLabel } from "./model";

export function ReturnsResultMeta({
  period,
  valuationDate,
  accountLink,
}: {
  period: Period | null;
  valuationDate: string | null;
  accountLink?: AccountLink | null;
}) {
  return (
    <div style={{ display: "grid", gap: 2 }}>
      {accountLink && (
        <small>
          {accountLink.status === "linked"
            ? accountLink.label
            : `Выписка ${accountLink.source_account_id}: связь со счётом не подтверждена`}
        </small>
      )}
      <small>
        {period ? periodLabel(period) : "Период не установлен"} ·{" "}
        {valuationDate ? `Оценка на ${dateLabel(valuationDate)}` : "Дата оценки не подтверждена"}
      </small>
    </div>
  );
}
