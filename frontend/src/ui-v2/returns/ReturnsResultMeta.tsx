import { type AccountLink, dateLabel, type Period, periodLabel } from "./model";

export function ReturnsResultMeta({
  period,
  valuationDate,
  accountLink,
  accountLabel,
}: {
  period: Period | null;
  valuationDate: string | null;
  accountLink?: AccountLink | null;
  accountLabel?: string;
}) {
  return (
    <div style={{ display: "grid", gap: 2 }}>
      {accountLink && (
        <small title={accountLink.source_account_id}>
          {accountLink.status === "linked"
            ? (accountLabel ?? accountLink.label)
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
