import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import { spendingApi, type SpendingMonth } from "../../api/spending";
import { Button, HelpTip, Table, Td } from "../../components/ui";
import { formatMonthKey, formatPercent, pluralRu } from "../../lib/format";
import sheet from "../ReportSheet.module.css";
import { UiV2Shell } from "../UiV2Shell";
import {
  isQueryReady,
  UiV2Loading,
  UiV2Notice,
  UiV2Skeleton,
  UiV2WidgetState,
} from "../UiV2StateBlocks";
import { spendingComparisonNote, spendingMonthForm } from "../uiV2Copy";
import { coordinate, DailyChart, HistoryChart } from "./SpendingCharts";
import { operationForms, Operations } from "./SpendingOperations";
import {
  coverageLabel,
  currentMonth,
  importPath,
  isNonzero,
  Money,
  MonthSelect,
  Section,
  shiftMonth,
  shortDate,
  signedPercent,
  sourceLabels,
  sources,
  spendingPath,
  TemplateButton,
  typeColors,
  typeLabels,
  types,
  UploadLink,
  validMonth,
} from "./common";
import styles from "./Spending.module.css";

function MonthFigures({ data }: { data: SpendingMonth }) {
  const { comparison, month, cash, open_exceptions: exceptions } = data;
  const location = useLocation();
  const note = comparison && spendingComparisonNote(data.has_manual, comparison.months);
  const split = [
    exceptions.excluded_count ? `${exceptions.excluded_count} не входят в траты` : "",
    exceptions.double_risk_count
      ? `${exceptions.double_risk_count} может быть посчитана дважды`
      : "",
  ].filter(Boolean);
  return (
    <section className={sheet.section}>
      <div className={sheet.figures}>
        <div className={sheet.figure}>
          <strong className={sheet.hero}>
            <Money value={data.total} empty="Недоступно" />
          </strong>
          <span className={sheet.figureLabel}>
            Траты за {spendingMonthForm(month, "accusative")}
          </span>
        </div>
        {comparison && !data.partial ? (
          <>
            <div className={sheet.figure}>
              <strong className={sheet.figureValue}>
                <Money value={comparison.average_total} />
              </strong>
              <span className={sheet.figureLabel}>
                Среднее за 3 мес{" "}
                <HelpTip label="Период среднего">
                  {comparison.months.map((item) => formatMonthKey(item.month)).join(", ")}.
                  Частичные месяцы в среднее не входят.
                </HelpTip>
              </span>
            </div>
            {comparison.delta_percent !== null && (
              <div className={sheet.figure}>
                <strong className={`${sheet.delta} ${styles.neutralDelta}`}>
                  {signedPercent(comparison.delta_percent)}
                </strong>
                <span className={sheet.figureLabel}>к среднему</span>
              </div>
            )}
          </>
        ) : (
          <p className={sheet.muted}>
            {data.partial
              ? "Частичный месяц со средним не сравнивается"
              : "Сравнивать пока не с чем: нужен хотя бы один полный прошлый месяц"}
          </p>
        )}
      </div>
      {note && !data.partial && <p className={sheet.gapNote}>{note}</p>}
      {sources.some((source) => isNonzero(data.by_source[source])) && (
        <p className={`${sheet.figureDetail} ${styles.sources}`}>
          {sources
            .filter((source) => isNonzero(data.by_source[source]))
            .map((source, index) => {
              const params = new URLSearchParams(location.search);
              params.set("month", month);
              params.set("source", source);
              return (
                <span key={source}>
                  {index > 0 && <span aria-hidden="true">· </span>}
                  <Link to={{ search: params.toString(), hash: "#spending-operations" }}>
                    {sourceLabels[source]} <Money value={data.by_source[source]} />
                  </Link>
                </span>
              );
            })}
        </p>
      )}
      {data.partial && (
        <p className={sheet.gapNote}>
          Выписка покрывает не весь месяц. Загрузите выписку за остальные дни — уже загруженные
          операции не пропадут.
        </p>
      )}
      {data.has_statement && !data.has_manual && (
        <p className={sheet.gapNote}>
          {data.partial
            ? "Ручной файл не загружен"
            : "Ручной файл не загружен: наличные и Сбер не учтены."}
        </p>
      )}
      {!data.has_statement && data.has_manual && (
        <p className={sheet.gapNote}>
          Выписка Альфы не загружена: в итоге только то, что вы записали сами.
        </p>
      )}
      {data.has_statement &&
        data.total &&
        !isNonzero(data.total) &&
        !sources.some((source) => isNonzero(data.by_source[source])) && (
          <p className={sheet.gapNote}>
            В выписке нет покупок: все операции — переводы или технические.
          </p>
        )}
      {data.has_manual && (
        <p className={sheet.gapNote}>
          Ручной файл — это крупные траты, которые вы записали сами. Мелкие наличные сюда не
          попадают.
        </p>
      )}
      {isNonzero(data.processing_total) && (
        <p className={sheet.muted}>
          Из них в обработке: <Money value={data.processing_total} />{" "}
          <HelpTip label="Покупки в обработке">
            Банк ещё не провёл эти покупки. Они уже входят в итог; после проводки сумма может
            немного измениться.
          </HelpTip>
        </p>
      )}
      {cash.withdrawn && (
        <p className={sheet.muted}>
          Снято наличными <Money value={cash.withdrawn} /> · записано наличных трат{" "}
          <Money value={cash.recorded} />{" "}
          <HelpTip label="Наличные">
            Снятие наличных — не трата. Наличные траты берутся только из ручного файла; в него вы
            записываете крупные покупки, поэтому разница — это мелкие траты и деньги в кошельке.
          </HelpTip>
        </p>
      )}
      {data.entry_links.slice(0, 3).map((link) => (
        <p className={sheet.muted} key={link.expense_entry_id}>
          Связано с записями месяца: {link.entry_category} — в месяце{" "}
          <Money value={link.month_amount} />, в выписке <Money value={link.diary_amount} />
        </p>
      ))}
      {data.entry_links.length > 3 && (
        <p className={sheet.muted}>и ещё {data.entry_links.length - 3}</p>
      )}
      {exceptions.count > 0 && (
        <div className={styles.actions}>
          <p>
            <span className={styles.warningIcon} aria-hidden="true">
              ⚠{" "}
            </span>
            {exceptions.count} {pluralRu(exceptions.count, operationForms)}{" "}
            {exceptions.count === 1 ? "ждёт" : "ждут"} решения
            {split.length ? `: ${split.join(", ")}` : ""}.
          </p>
          <Link className="btn btn--secondary" to={importPath(month, true)}>
            Разобрать
          </Link>
        </div>
      )}
    </section>
  );
}

function CategoryDetail({
  month,
  category,
  selectMonth,
}: {
  month: string;
  category: number;
  selectMonth: (month: string) => void;
}) {
  const history = useQuery({
    queryKey: ["spending", "category-history", category, month],
    queryFn: ({ signal }) => spendingApi.history(month, 12, category, signal),
  });
  return (
    <div className={styles.categoryDetail}>
      {history.isError ? (
        <UiV2WidgetState retry={() => void history.refetch()} />
      ) : history.data ? (
        <HistoryChart items={history.data.items} selected={month} selectMonth={selectMonth} mini />
      ) : (
        <UiV2Loading label="Загружаем историю категории" />
      )}
      <Operations month={month} category={category} inline />
      {category > 0 && (
        <Link className={styles.sectionLink} to={`${spendingPath}/rules#category-${category}`}>
          Изменить категорию
        </Link>
      )}
    </div>
  );
}

type Update = (values: Record<string, string | null>) => void;
function MonthCategories({
  data,
  params,
  update,
  selectMonth,
}: {
  data: SpendingMonth;
  params: URLSearchParams;
  update: Update;
  selectMonth: (month: string) => void;
}) {
  const type = types.find((item) => params.get("type") === item);
  const selected = params.get("category");
  const comparison = data.comparison != null && !data.partial;
  const categories = data.positive_categories.filter((category) => !type || category.type === type);
  const max = coordinate(data.positive_categories[0]?.amount) ?? 1;
  const refunds = data.categories.filter(
    (category) => (!type || category.type === type) && category.amount.amount.startsWith("-"),
  );
  return (
    <Section
      title="Категории"
      eyebrow={formatMonthKey(data.month)}
      actions={
        <div className={sheet.segmented}>
          <Button aria-pressed={!type} onClick={() => update({ type: null })}>
            Все
          </Button>
          {types.map((value) => (
            <Button
              key={value}
              aria-pressed={type === value}
              onClick={() => update({ type: value })}
            >
              {typeLabels[value]}
            </Button>
          ))}
        </div>
      }
    >
      {!categories.length && !refunds.length && (
        <UiV2WidgetState title={type ? "Трат этого типа нет" : "Трат в этом месяце нет"} />
      )}
      <div className={styles.categories}>
        {categories.map((category) => {
          const open = String(category.id) === selected;
          const average = coordinate(category.average_3m);
          return (
            <div key={category.id}>
              <button
                className={`${sheet.rowButton} ${sheet.pickable} ${styles.category}`}
                type="button"
                aria-expanded={open}
                data-comparison={comparison}
                onClick={() => update({ category: open ? null : String(category.id) })}
              >
                <span className={styles.categoryName}>
                  <i className={sheet.dot} style={{ background: typeColors[category.type] }} />
                  {category.name}
                </span>
                <span className={styles.categoryTrack} aria-hidden="true">
                  <span style={{ width: `${((coordinate(category.amount) ?? 0) / max) * 100}%` }} />
                  {average !== null && (
                    <i style={{ left: `${Math.max(0, Math.min(100, (average / max) * 100))}%` }} />
                  )}
                </span>
                <Money value={category.amount} />
                <span>{formatPercent(category.share_percent, { share: true })}</span>
                {comparison && (
                  <span>
                    {category.is_new ? "новая" : signedPercent(category.delta_percent, true)}
                  </span>
                )}
              </button>
              {open && (
                <>
                  <CategoryDetail
                    month={data.month}
                    category={category.id}
                    selectMonth={selectMonth}
                  />
                  <Button variant="ghost" onClick={() => update({ category: null })}>
                    Свернуть
                  </Button>
                </>
              )}
            </div>
          );
        })}
      </div>
      {refunds.length > 0 && (
        <div className={styles.summaryLine}>
          <span>Возвраты</span>
          <span>
            {refunds.map((category) => (
              <span className={styles.refundItem} key={category.id}>
                <Money value={category.amount} /> {category.name}
              </span>
            ))}
          </span>
        </div>
      )}
      {(categories.length > 0 || refunds.length > 0) && (
        <div className={styles.summaryLine}>
          <strong>Итого</strong>
          <strong>
            <Money value={data.total} empty="Недоступно" />
          </strong>
        </div>
      )}
    </Section>
  );
}

async function allHistory(until: string, signal: AbortSignal) {
  let count = 24;
  let value = await spendingApi.history(until, count, undefined, signal);
  while (value.has_more && count < 1200) {
    count = Math.min(count * 2, 1200);
    value = await spendingApi.history(until, count, undefined, signal);
  }
  const first = value.items.findIndex((item) => item.loaded);
  return first < 0 ? value.items : value.items.slice(first);
}

export default function SpendingPage() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const requested = params.get("month");
  const invalid =
    requested !== null && (!validMonth(requested) || params.getAll("month").length !== 1);
  const [all, setAll] = useState(false);
  const latest = useQuery({
    queryKey: ["spending", "latest"],
    queryFn: ({ signal }) => spendingApi.history(undefined, 12, undefined, signal),
    enabled: !invalid,
  });
  const last = latest.data?.items.at(-1);
  const month = requested ?? last?.month;
  const data = useQuery({
    queryKey: ["spending", "month", month],
    queryFn: ({ signal }) => spendingApi.month(month ?? "", signal),
    enabled: Boolean(month) && !invalid,
  });
  const until = last?.loaded && month && month > last.month ? last.month : month;
  const history = useQuery({
    queryKey: ["spending", "history", until, all],
    queryFn: async ({ signal }) => {
      if (all) return { items: await allHistory(until ?? "", signal), has_more: true };
      return spendingApi.history(until, 12, undefined, signal);
    },
    enabled: Boolean(until && last?.loaded && !invalid),
  });
  const hasAll = all || Boolean(history.data?.has_more);
  const busy = !invalid && !latest.isError && !data.isError && (!latest.data || !data.data);
  const update: Update = (values) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next, { preventScrollReset: true });
  };
  const selectMonth = (value: string) => update({ month: value });
  const categoryParam = params.get("category");
  const category =
    categoryParam && /^-?\d+$/.test(categoryParam) && Number.isSafeInteger(Number(categoryParam))
      ? Number(categoryParam)
      : undefined;
  const source = sources.find((item) => item === params.get("source"));
  const result = data.data;
  const monthName = formatMonthKey(month);
  const status = (
    location.state as {
      spending?: { month: string; added: number; changed: number; removed: number };
    } | null
  )?.spending;
  const operationsLocation =
    !busy && result && result.month === month && location.hash === "#spending-operations"
      ? location.key
      : null;
  useEffect(() => {
    if (operationsLocation) {
      document.getElementById("spending-operations")?.scrollIntoView({ block: "start" });
    }
  }, [operationsLocation]);
  return (
    <UiV2Shell
      busy={busy}
      header={
        <div className={`${styles.actions} ${styles.screenHeader}`}>
          <h1>Расходы</h1>
          {month && !invalid && (
            <>
              <div className={styles.actions}>
                <Button
                  aria-label="Предыдущий месяц"
                  disabled={month <= "1000-01"}
                  onClick={() => selectMonth(shiftMonth(month, -1))}
                >
                  ‹
                </Button>
                <MonthSelect month={month} onChange={selectMonth} />
                <Button
                  aria-label="Следующий месяц"
                  disabled={month >= currentMonth()}
                  onClick={() => selectMonth(shiftMonth(month, 1))}
                >
                  ›
                </Button>
              </div>
              <UploadLink month={month} />
            </>
          )}
        </div>
      }
    >
      <div className={sheet.sheet}>
        {invalid ? (
          <>
            <UiV2WidgetState title="Такого месяца нет" />
            <Link className={styles.sectionLink} to={spendingPath}>
              К последнему месяцу
            </Link>
          </>
        ) : latest.isError || data.isError ? (
          <UiV2Notice
            title="Траты временно недоступны"
            retry={() => void (latest.isError ? latest.refetch() : data.refetch())}
          >
            Не удалось получить данные. Загруженные выписки не потеряны.
          </UiV2Notice>
        ) : busy || !result || !month ? (
          <UiV2Skeleton label="Загружаем траты" />
        ) : (
          <>
            <div className={styles.status}>
              {result.loaded && (
                <span
                  className={sheet.chip}
                  data-coverage={
                    result.partial
                      ? "partial"
                      : result.has_manual && result.has_statement
                        ? "both"
                        : "single"
                  }
                >
                  {coverageLabel(result)}
                </span>
              )}
              <Link to={`${spendingPath}/rules?month=${month}`}>Категории и правила</Link>
            </div>
            {status?.month === month && isQueryReady(data) && (
              <p role="status">
                {monthName} обновлён: +{status.added} операции, изменено {status.changed}, удалено{" "}
                {status.removed}.
              </p>
            )}
            {result.loaded ? (
              <>
                <MonthFigures data={result} />
                <Section title="Операции" eyebrow={monthName} id="spending-operations">
                  <div className={styles.filters}>
                    <label className={sheet.select}>
                      Категория{" "}
                      <select
                        value={category ?? ""}
                        onChange={(event) => update({ category: event.target.value || null })}
                      >
                        <option value="">Все</option>
                        {result.categories.map((item) => (
                          <option value={item.id} key={item.id}>
                            {item.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className={sheet.select}>
                      Источник{" "}
                      <select
                        value={source ?? ""}
                        onChange={(event) => update({ source: event.target.value || null })}
                      >
                        <option value="">Все</option>
                        {sources.map((item) => (
                          <option value={item} key={item}>
                            {sourceLabels[item]}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <Operations
                    key={`${month}:${category}:${source}`}
                    month={month}
                    category={category}
                    source={source}
                  />
                </Section>
              </>
            ) : (
              <>
                <UiV2Notice title={`${monthName}: файлы расходов не загружены`}>
                  Загрузите выписку Альфа-Банка в CSV и ручной файл Markdown, если вели его.
                </UiV2Notice>
                <div className={styles.actions}>
                  <UploadLink month={month} />
                  <TemplateButton month={month} />
                </div>
                <Section
                  title="Записи из отчёта месяца"
                  eyebrow={monthName}
                  id="spending-operations"
                >
                  <Operations key={month} month={month} source="month_entries" />
                </Section>
              </>
            )}
            {(last?.loaded || result.loaded) && (
              <>
                <Section
                  title="Траты по месяцам"
                  eyebrow="История"
                  actions={
                    <div className={sheet.segmented}>
                      <Button aria-pressed={!all} onClick={() => setAll(false)}>
                        12 мес
                      </Button>
                      {hasAll && (
                        <Button aria-pressed={all} onClick={() => setAll(true)}>
                          Всё
                        </Button>
                      )}
                    </div>
                  }
                >
                  {history.isError ? (
                    <UiV2WidgetState retry={() => void history.refetch()} />
                  ) : history.data ? (
                    <HistoryChart
                      items={history.data.items}
                      selected={month}
                      selectMonth={selectMonth}
                    />
                  ) : (
                    <UiV2Loading label="Загружаем историю трат" />
                  )}
                </Section>
                {result.loaded && (
                  <>
                    <MonthCategories
                      data={result}
                      params={params}
                      update={update}
                      selectMonth={selectMonth}
                    />
                    <div className={`${sheet.columns} ${styles.purchaseColumns}`}>
                      {result.top_purchases.length > 0 && (
                        <Section title="Крупнейшие покупки" eyebrow={monthName}>
                          <Table aria-label="Крупнейшие покупки">
                            <tbody>
                              {result.top_purchases.map((item) => (
                                <tr key={item.id}>
                                  <Td>{shortDate(item.date)}</Td>
                                  <Td>{item.description}</Td>
                                  <Td>{item.category_name}</Td>
                                  <Td numeric>
                                    <Money value={item.amount} />
                                  </Td>
                                </tr>
                              ))}
                            </tbody>
                          </Table>
                        </Section>
                      )}
                      <Section title="Как набегали траты" eyebrow={monthName}>
                        <DailyChart month={month} daily={result.daily} />
                      </Section>
                    </div>
                  </>
                )}
              </>
            )}
          </>
        )}
      </div>
    </UiV2Shell>
  );
}
