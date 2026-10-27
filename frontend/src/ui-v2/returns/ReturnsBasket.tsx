import { useQuery } from "@tanstack/react-query";
import { useLayoutEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { apiRequest } from "../../api/client";
import { displayMetric, type Period, periodLabel, validDate } from "./model";
import styles from "./Returns.module.css";
import { Explanation, Info } from "./ReturnsInfo";

export const basketCategories = ["brokerage", "iis", "deposits", "gold"] as const;
const labels = ["Брокерские счета", "ИИС", "Депозиты и накопительные", "Физическое золото"];
type Cell = { period: Period; value_kopecks: string | null; reason_codes: string[] };
type Subtotal = {
  value_kopecks: string | null;
  covered_cells: number;
  total_cells: number;
  method: string;
  reason_codes: string[];
};
export type Basket = {
  period: Period;
  categories: string[];
  partial: true;
  result_kopecks: null;
  known_partial_subtotal_kopecks: string | null;
  reason_codes: string[];
  source_subtotal: Subtotal;
  deposit_received_interest: Subtotal;
  components: {
    id: string;
    label: string;
    category: string;
    basis: string;
    method: string;
    cells: Cell[];
  }[];
};
const money = (value: string | null) =>
  displayMetric({ value, method: "", unit: "kopecks", estimate: true, reason_codes: [] }, true);

export function ReturnsBasket({ period, refreshing }: { period: Period; refreshing: boolean }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { hash, key: locationKey } = useLocation();
  const raw = params.get("categories") ?? basketCategories.join(",");
  // Controlled input feedback is immediate; financial reads/display wait for
  // the matching committed Router URL, including Back/Reload and ABA.
  const [inputSelection, setInputSelection] = useState({ key: locationKey, value: raw });
  useLayoutEffect(() => setInputSelection({ key: locationKey, value: raw }), [raw, locationKey]);
  const inputParts = inputSelection.value ? inputSelection.value.split(",") : [];
  const inputMatchesUrl = inputSelection.key === locationKey && inputSelection.value === raw;
  const parts = raw ? raw.split(",") : [];
  const categories = basketCategories.filter((c) => parts.includes(c)).join(",");
  const valid =
    validDate(period.start) &&
    validDate(period.end) &&
    period.start < period.end &&
    ["scope", "start", "end", "categories"].every((key) => params.getAll(key).length <= 1) &&
    parts.length === new Set(parts).size &&
    parts.every((c) => (basketCategories as readonly string[]).includes(c));
  const query = useQuery({
    queryKey: ["returns", "basket", period.start, period.end, categories],
    queryFn: async ({ signal }) => {
      const q = new URLSearchParams({ start: period.start, end: period.end, categories });
      const result = await apiRequest<Basket>(`/api/returns/basket?${q}`, { signal });
      if (
        result.period.start !== period.start ||
        result.period.end !== period.end ||
        result.categories.join(",") !== categories
      )
        throw new Error("basket_selection_mismatch");
      return result;
    },
    enabled: valid && inputMatchesUrl && !refreshing,
    staleTime: 0,
  });
  const data =
    valid && inputMatchesUrl && !refreshing && !query.isFetching && !query.isError
      ? query.data
      : undefined;
  return (
    <section className={styles.panel} aria-labelledby="my-returns-heading">
      <div className={styles.sectionHead}>
        <h2 id="my-returns-heading">Моя доходность</h2>
        {valid && <span>{periodLabel(period)}</span>}
      </div>
      <fieldset className={`${styles.filters} ${styles.basketCategories}`}>
        <legend>Что учитывать</legend>
        {basketCategories.map((category, i) => (
          <label key={category}>
            <input
              type="checkbox"
              checked={inputParts.includes(category)}
              onChange={() => {
                const next = new URLSearchParams(params);
                const selected = basketCategories
                  .filter((c) =>
                    c === category ? !inputParts.includes(c) : inputParts.includes(c),
                  )
                  .join(",");
                setInputSelection({ key: locationKey, value: selected });
                next.set("categories", selected);
                navigate({ search: next.toString(), hash });
              }}
            />
            {labels[i]}
          </label>
        ))}
      </fieldset>
      {!valid ? (
        <p role="status">Выберите корректный период и категории.</p>
      ) : !parts.length ? (
        <p role="status">Выбери хотя бы одну категорию</p>
      ) : query.isError ? (
        <p role="alert">Не удалось загрузить выбранную корзину.</p>
      ) : !data ? (
        <p role="status">Пересчитываем выбранное…</p>
      ) : (
        <>
          <div className={`${styles.cards} ${styles.basketCards}`}>
            <div className={styles.card}>
              <h3>Результат выбранного</h3>
              <strong>—</strong>
              <p>Доходность: —</p>
              <Info label="Полный результат корзины">
                <p>
                  Полный результат и общий процент выбранных категорий пока не подтверждены общей
                  моделью. Частичные суммы их не заменяют.
                </p>
              </Info>
            </div>
            <section className={styles.card} aria-label="Известная часть по выпискам">
              <h3>Известная часть по выпискам</h3>
              <strong>{money(data.known_partial_subtotal_kopecks)}</strong>
              <p>
                Покрытие: {data.source_subtotal.covered_cells} из {data.source_subtotal.total_cells}{" "}
                счёт-месяцев
              </p>
              <small>
                Предварительный результат. Личный итог после всех налогов не подтверждён. Брокерские
                / ИИС: тип в истории не подтверждён.
              </small>
            </section>
            <section className={styles.card} aria-label="Полученные депозитные проценты">
              <h3>Полученные проценты · известная часть</h3>
              <strong>{money(data.deposit_received_interest.value_kopecks)}</strong>
              <p>
                Покрытие: {data.deposit_received_interest.covered_cells} из{" "}
                {data.deposit_received_interest.total_cells} счёт-месяцев
              </p>
              <small>
                Отдельные полученные депозитные проценты. К результату по выпискам не прибавляются.
                Пополнения и ожидаемые проценты не учитываются.
              </small>
            </section>
          </div>
          <details>
            <summary>Покрытие и причины по категориям</summary>
            <p>
              Счёт-месяцы показывают наличие наблюдений, а не долю капитала. Пустые данные не
              означают нулевой результат.
            </p>
            {data.components.map((component) => (
              <div key={component.id}>
                <h3>
                  {component.category === "brokerage_iis"
                    ? "Брокерские / ИИС"
                    : component.category === "deposits"
                      ? "Депозиты и накопительные"
                      : "Физическое золото"}
                  : {component.label}
                </h3>
                <p>
                  {component.basis === "statements"
                    ? "Предварительно по выпискам; один экономический счёт."
                    : component.basis === "accepted"
                      ? "Полученные проценты из закрытых отчётов; полнота класса не подтверждена."
                      : "Полный результат за период не подтверждён."}
                </p>
                {component.id.startsWith("source:") && component.basis === "statements" && (
                  <Link
                    to={{
                      hash,
                      search: (() => {
                        const next = new URLSearchParams(params);
                        next.set("scope", component.id);
                        return next.toString();
                      })(),
                    }}
                  >
                    Подробнее по счёту
                  </Link>
                )}
                <ul>
                  {component.cells.map((cell) => (
                    <li key={cell.period.start}>
                      {periodLabel(cell.period)}:{" "}
                      {cell.value_kopecks === null ? "Не учтён" : money(cell.value_kopecks)}
                      <Explanation codes={cell.reason_codes} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </details>
        </>
      )}
    </section>
  );
}
