import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { formatApiError } from "../api/client";
import { listAllSourceIntakes, readSourceIntake, saveSourceIntake } from "../api/sourceIntake";
import {
  getSourceInstrumentReturns,
  getSourceMonthlyReturns,
  type InstrumentTotals,
} from "../api/sourceReturns";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Shell } from "./UiV2Shell";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";
import pageStyles from "./UiV2Page.module.css";
import styles from "./UiV2MonthlyReturnsPage.module.css";

const money = (value: number | null) =>
  value === null
    ? "—"
    : `${new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2 }).format(value / 100)} ₽`;
const rate = (value: string | null, fraction = true) =>
  value === null
    ? "—"
    : `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(value) * (fraction ? 100 : 1))} %`;
const month = (value: string) =>
  new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric", timeZone: "UTC" }).format(
    new Date(`${value.slice(0, 10)}T00:00:00Z`),
  );
const flagLabels: Record<string, string> = {
  missing_endpoint: "нет границы месяца",
  unknown_flow: "неизвестный поток",
  seam_mismatch: "расхождение границ",
  missing_month: "месяц отсутствует",
  unattributed_income: "доход не отнесён",
};
const flags = (values: string[]) =>
  values.length ? values.map((value) => flagLabels[value] ?? value).join(", ") : "нет";
const badges = (approximate: boolean, partial: boolean, incomeComplete?: boolean) => (
  <span className={styles.badges}>
    {approximate && <span className={styles.badge}>приблизительно</span>}
    {partial && <span className={styles.badge}>частичные данные</span>}
    {incomeComplete === false && <span className={styles.badge}>доходы неполные</span>}
    {!approximate && !partial && incomeComplete !== false && (
      <span className={`${styles.badge} ${styles.ok}`}>полные данные</span>
    )}
  </span>
);
const instrumentCells = (row: InstrumentTotals, partial = row.total_kopecks === null) => (
  <>
    <td>{money(row.price_effect_kopecks)}</td>
    <td>{money(row.coupons_kopecks)}</td>
    <td>{money(row.dividends_kopecks)}</td>
    <td>{money(row.total_kopecks)}</td>
    <td>{rate(row.return_percent, false)}</td>
    <td>
      {badges(row.approximate, partial, row.income_complete)}
      {flags(row.flags)}
    </td>
  </>
);

export default function UiV2MonthlyReturnsPage() {
  const client = useQueryClient();
  const intakes = useQuery({
    queryKey: ["source-intakes", "all"],
    queryFn: ({ signal }) => listAllSourceIntakes(signal),
  });
  const accounts = useMemo(
    () =>
      Array.from(new Set((intakes.data ?? []).flatMap((i) => i.document.source_accounts))).sort(),
    [intakes.data],
  );
  const [selected, setSelected] = useState("");
  const account = selected || accounts[0] || "";
  const [uploads, setUploads] = useState<Array<{ name: string; state: string; detail: string }>>(
    [],
  );
  const [uploading, setUploading] = useState(false);
  const monthly = useQuery({
    queryKey: ["source-returns", "monthly", account],
    queryFn: ({ signal }) => getSourceMonthlyReturns(account, signal),
    enabled: !!account,
  });
  const instruments = useQuery({
    queryKey: ["source-returns", "instruments", account],
    queryFn: ({ signal }) => getSourceInstrumentReturns(account, signal),
    enabled: !!account,
  });
  async function upload(files: File[]) {
    setUploading(true);
    setUploads(files.map((file) => ({ name: file.name, state: "Сохраняем", detail: "" })));
    await Promise.all(
      files.map(async (file, index) => {
        try {
          const ack = await saveSourceIntake(file, crypto.randomUUID(), 0, null);
          const intake = await readSourceIntake(ack.intake_id);
          const detail = intake.exceptions.length
            ? `Сохранено наблюдений: ${intake.observations.length}. Флаги: ${intake.exceptions.join(", ")}`
            : `Сохранено наблюдений: ${intake.observations.length}. Пробелов не найдено.`;
          setUploads((old) =>
            old.map((item, i) => (i === index ? { ...item, state: "Сохранен", detail } : item)),
          );
        } catch (error) {
          setUploads((old) =>
            old.map((item, i) =>
              i === index ? { ...item, state: "Не сохранен", detail: formatApiError(error) } : item,
            ),
          );
        }
      }),
    );
    await client.invalidateQueries({ queryKey: ["source-intakes"] });
    await client.invalidateQueries({ queryKey: ["source-returns"] });
    setUploading(false);
  }
  return (
    <UiV2Shell
      active="capital"
      busy={uploading}
      header={
        <>
          <p className={pageStyles.eyebrow}>Капитал · Источник</p>
          <h1>Доходность по месяцам</h1>
          <p className={pageStyles.subtitle}>
            Предварительная оценка по сохранённым выпискам. Не финансовый результат.
          </p>
          <Link to="/v2/capital">← Капитал</Link>
        </>
      }
    >
      <UiV2Panel
        eyebrow="Выписки"
        id="monthly-upload"
        testIdPrefix="returns"
        title="Добавить несколько файлов"
        wide
      >
        <div className={styles.upload}>
          <label>
            XML-файлы
            <input
              aria-label="XML-файлы"
              accept=".xml"
              multiple
              type="file"
              onChange={(event) => void upload(Array.from(event.target.files ?? []))}
            />
          </label>
          <p className={styles.note}>
            Каждый файл обрабатывается отдельно: всё распознанное сохраняется, а пробелы и флаги
            остаются видимыми.
          </p>
          {uploads.length > 0 && (
            <ul className={styles.fileList}>
              {uploads.map((item) => (
                <li key={item.name}>
                  <strong>
                    {item.name}: {item.state}
                  </strong>
                  {item.detail && <> — {item.detail}</>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </UiV2Panel>
      <UiV2Panel
        eyebrow="Охват"
        id="monthly-account"
        testIdPrefix="returns"
        title="Счёт источника"
        wide
      >
        {intakes.isPending ? (
          <UiV2Loading label="Читаем источники…" />
        ) : intakes.isError ? (
          <UiV2Notice title="Не удалось прочитать источники">
            {formatApiError(intakes.error)}
          </UiV2Notice>
        ) : accounts.length === 0 ? (
          <UiV2Notice title="Нет сохранённых выписок">Добавьте XML-файлы выше.</UiV2Notice>
        ) : (
          <label>
            Счёт в выписке
            <select
              aria-label="Счёт в выписке"
              value={account}
              onChange={(e) => setSelected(e.target.value)}
            >
              {accounts.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
        )}
      </UiV2Panel>
      {!!account &&
        (monthly.isPending ? (
          <UiV2Loading label="Считаем месяцы…" />
        ) : monthly.isError ? (
          <UiV2Notice title="Не удалось рассчитать месяцы">
            {formatApiError(monthly.error)}
          </UiV2Notice>
        ) : (
          <>
            <UiV2Panel
              eyebrow="Сводка"
              id="monthly-total"
              testIdPrefix="returns"
              title="За всё время"
              wide
            >
              {badges(true, monthly.data.period.missing_endpoint)}
              <p>
                <strong>Взносы:</strong> {money(monthly.data.period.contributions_kopecks)} ·{" "}
                <strong>Выводы:</strong> {money(monthly.data.period.withdrawals_kopecks)} ·{" "}
                <strong>Рост отдельно:</strong> {money(monthly.data.period.growth_kopecks)}
              </p>
              <p>
                <strong>XIRR, годовых:</strong> {rate(monthly.data.period.xirr_annualized_return)} ·{" "}
                <strong>XIRR за период:</strong> {rate(monthly.data.period.xirr_period_return)} ·{" "}
                <strong>TWRR:</strong> {rate(monthly.data.period.chained_return)}
              </p>
            </UiV2Panel>
            <UiV2Panel
              eyebrow="Помесячно"
              id="monthly-table"
              testIdPrefix="returns"
              title="Взносы и рост"
              wide
            >
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Месяц</th>
                      <th>Взносы</th>
                      <th>Выводы</th>
                      <th>Рост</th>
                      <th>Купоны</th>
                      <th>Дивиденды</th>
                      <th>Доходность</th>
                      <th>Качество и флаги</th>
                    </tr>
                  </thead>
                  <tbody>
                    {monthly.data.months.map((row) => (
                      <tr key={row.closing_date}>
                        <td>{month(row.closing_date)}</td>
                        <td>{money(row.contributions_kopecks)}</td>
                        <td>{money(row.withdrawals_kopecks)}</td>
                        <td>{money(row.growth_kopecks)}</td>
                        <td>{money(row.coupons_kopecks)}</td>
                        <td>{money(row.dividends_kopecks)}</td>
                        <td>{rate(row.modified_dietz_return)}</td>
                        <td>
                          {badges(row.approximate, row.missing_endpoint)}
                          {flags([...row.reason_codes, ...row.flags])}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </UiV2Panel>
          </>
        ))}
      {!!account &&
        (instruments.isPending ? (
          <UiV2Loading label="Считаем инструменты…" />
        ) : instruments.isError ? (
          <UiV2Notice title="Не удалось рассчитать инструменты">
            {formatApiError(instruments.error)}
          </UiV2Notice>
        ) : (
          <UiV2Panel
            eyebrow="Инструменты"
            id="instrument-table"
            testIdPrefix="returns"
            title="Цена и выплаты по инструментам"
            wide
          >
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Инструмент / период</th>
                    <th>Изменение цены</th>
                    <th>Купоны</th>
                    <th>Дивиденды</th>
                    <th>Итого</th>
                    <th>Доходность</th>
                    <th>Качество и флаги</th>
                  </tr>
                </thead>
                <tbody>
                  {instruments.data.instruments.flatMap((instrument) => [
                    <tr key={`${instrument.isin}:all`}>
                      <th>
                        {instrument.source_name ?? instrument.isin}
                        <br />
                        <small>{instrument.isin} · всё время</small>
                      </th>
                      {instrumentCells(instrument.all_time, instrument.all_time.partial)}
                    </tr>,
                    ...instrument.months.map((row) => (
                      <tr key={`${instrument.isin}:${row.month}`}>
                        <td>↳ {month(row.month)}</td>
                        {instrumentCells(row)}
                      </tr>
                    )),
                  ])}
                </tbody>
              </table>
            </div>
          </UiV2Panel>
        ))}
    </UiV2Shell>
  );
}
