import { Link } from "react-router";

import { parseMonthlyCloseReturnContext } from "./navigation";

export function MonthlyCloseReturnBar() {
  const context = parseMonthlyCloseReturnContext(new URLSearchParams(window.location.search));
  if (!context) return null;

  return (
    <aside className="monthly-close-return" aria-label="Возврат к закрытию месяца">
      <span>Изменения относятся к выбранному месяцу.</span>
      <Link
        className="btn btn--secondary btn--sm"
        to={`/months/${context.monthId}/close#${context.step}`}
      >
        Вернуться к закрытию
      </Link>
    </aside>
  );
}
