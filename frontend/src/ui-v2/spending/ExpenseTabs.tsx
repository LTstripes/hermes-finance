import { Link, useSearchParams } from "react-router";
import { monthPath, spendingPath, validMonth } from "./common";
import styles from "./Spending.module.css";

export function ExpenseTabs({ reserve = false }: { reserve?: boolean }) {
  const [params] = useSearchParams();
  const month = params.get("month");
  const query = month && validMonth(month) ? `?month=${month}` : "";
  return (
    <nav aria-label="Раздел расходов" className={styles.actions}>
      <Link
        aria-current={reserve ? undefined : "page"}
        to={month && validMonth(month) ? monthPath(month) : spendingPath}
      >
        Операции
      </Link>
      <Link aria-current={reserve ? "page" : undefined} to={`${spendingPath}/reserve${query}`}>
        Подушка
      </Link>
    </nav>
  );
}
