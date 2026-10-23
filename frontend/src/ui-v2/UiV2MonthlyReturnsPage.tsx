import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiClientError, formatApiError } from "../api/client";
import { listAllSourceIntakes, readSourceIntake, saveSourceIntake } from "../api/sourceIntake";
import {
  getSourceInstrumentReturns,
  getSourceMonthlyReturns,
  type InstrumentTotals,
  type ReturnGap,
} from "../api/sourceReturns";
import { UiV2BondSlice } from "./UiV2BondSlice";
import styles from "./UiV2MonthlyReturnsPage.module.css";
import pageStyles from "./UiV2Page.module.css";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Shell } from "./UiV2Shell";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

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
  overlap_flow_deduplicated: "повтор потока в перекрывающихся выписках учтён один раз",
  partial_month_source: "источник покрывает месяц частично",
};
const flags = (values: string[]) =>
  values.length
    ? Array.from(new Set(values))
        .map((value) => flagLabels[value] ?? value)
        .join(", ")
    : "нет";
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
const assumptions = (flows: boolean, income: boolean) => (
  <span className={styles.badges}>
    {flows && <span className={styles.badge}>потоки с допущениями</span>}
    {income && <span className={styles.badge}>купоны/дивиденды с допущениями</span>}
  </span>
);
function ReturnGaps({ gaps }: { gaps: ReturnGap[] }) {
  if (!gaps.length) return null;
  return (
    <div>
      <h3>Пробелы и перекрытия источников</h3>
      <ul>
        {gaps.map((gap) => (
          <li key={JSON.stringify(gap)}>
            {flags([gap.code])}
            {gap.month && <> · месяц: {month(gap.month)}</>}
            {gap.intake_id !== null && <> · выписка: {gap.intake_id}</>}
            {gap.source_reference && <> · строка: {gap.source_reference}</>}
            {gap.isin && <> · ISIN: {gap.isin}</>}
          </li>
        ))}
      </ul>
    </div>
  );
}
type Upload = {
  id: string;
  name: string;
  state: string;
  detail: string;
  intakeId?: number;
  readbackFailed?: boolean;
};
const instrumentCells = (row: InstrumentTotals, partial = row.total_kopecks === null) => (
  <>
    <td>{money(row.price_effect_kopecks)}</td>
    <td>{money(row.coupons_kopecks)}</td>
    <td>{money(row.dividends_kopecks)}</td>
    <td>{money(row.total_kopecks)}</td>
    <td>{rate(row.return_percent, false)}</td>
    <td>
      {badges(row.approximate, partial, row.income_complete)}
      {assumptions(false, row.income_assumptions_used)}
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
      Array.from(
        new Set(
          (intakes.data ?? [])
            .flatMap(({ document }) => [
              document.filename_account,
              ...(document.source_accounts ?? []),
            ])
            .filter((value) => typeof value === "string" && value.trim().length > 0),
        ),
      ).sort(),
    [intakes.data],
  );
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = searchParams.get("source_account") ?? "";
  const account = selected || accounts[0] || "";
  const [uploads, setUploads] = useState<Upload[]>([]);
  const uploadBusy = useRef(false);
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
  function updateUpload(id: string, patch: Partial<Upload>) {
    setUploads((old) => old.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }
  async function readUploadedIntake(id: string, intakeId: number) {
    updateUpload(id, { state: "Сохранен · читаем", intakeId, readbackFailed: false });
    try {
      const intake = await readSourceIntake(intakeId);
      const detail = intake.exceptions.length
        ? `Сохранено наблюдений: ${intake.observations.length}. Флаги: ${intake.exceptions.join(", ")}`
        : `Сохранено наблюдений: ${intake.observations.length}. Пробелов не найдено.`;
      updateUpload(id, { state: "Сохранен", detail });
    } catch (error) {
      updateUpload(id, {
        state: "Сохранен · не удалось прочитать",
        detail: `Сохранение подтверждено. Повторите чтение без повторной загрузки. ${formatApiError(error)}`,
        readbackFailed: true,
      });
    }
  }
  async function retryReadback(id: string, intakeId: number) {
    if (uploadBusy.current) return;
    uploadBusy.current = true;
    setUploading(true);
    try {
      await readUploadedIntake(id, intakeId);
    } finally {
      uploadBusy.current = false;
      setUploading(false);
    }
  }
  async function upload(files: File[]) {
    if (uploadBusy.current || !files.length) return;
    uploadBusy.current = true;
    setUploading(true);
    const batch = files.map((file) => ({ file, id: crypto.randomUUID() }));
    setUploads(
      batch.map(({ file, id }) => ({ id, name: file.name, state: "Сохраняем", detail: "" })),
    );
    try {
      await Promise.all(
        batch.map(async ({ file, id }) => {
          let intakeId: number;
          try {
            const ack = await saveSourceIntake(file, id, 0, null);
            intakeId = ack.intake_id;
          } catch (error) {
            const detail =
              error instanceof ApiClientError && error.status === 409
                ? `${formatApiError(error)} Причина: ${error.message}`
                : formatApiError(error);
            updateUpload(id, { state: "Не сохранен", detail });
            return;
          }
          await readUploadedIntake(id, intakeId);
        }),
      );
      await client.invalidateQueries({ queryKey: ["source-intakes"] });
      await client.invalidateQueries({ queryKey: ["source-returns"] });
    } finally {
      uploadBusy.current = false;
      setUploading(false);
    }
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
              disabled={uploading}
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                event.target.value = "";
                void upload(files);
              }}
            />
          </label>
          <p className={styles.note}>
            Каждый файл обрабатывается отдельно: всё распознанное сохраняется, а пробелы и флаги
            остаются видимыми.
          </p>
          {uploads.length > 0 && (
            <ul className={styles.fileList}>
              {uploads.map((item) => (
                <li key={item.id}>
                  <strong>
                    {item.name}: {item.state}
                  </strong>
                  {item.detail && <> — {item.detail}</>}
                  {item.readbackFailed && item.intakeId !== undefined && (
                    <button
                      type="button"
                      disabled={uploading}
                      onClick={() => {
                        if (item.intakeId !== undefined) void retryReadback(item.id, item.intakeId);
                      }}
                    >
                      Повторить чтение {item.name}
                    </button>
                  )}
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
              onChange={(e) =>
                setSearchParams((previous) => {
                  const next = new URLSearchParams(previous);
                  next.set("source_account", e.target.value);
                  next.delete("bond_period");
                  next.delete("bond_isin");
                  return next;
                })
              }
            >
              {accounts.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
        )}
      </UiV2Panel>
      {!!account && instruments.data && (
        <UiV2BondSlice key={account} account={account} sources={instruments.data} />
      )}
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
              {badges(monthly.data.period.approximate, monthly.data.period.missing_endpoint)}
              {assumptions(monthly.data.period.assumptions_used, false)}
              <p>
                <strong>Взносы:</strong> {money(monthly.data.period.contributions_kopecks)} ·{" "}
                <strong>Выводы:</strong> {money(monthly.data.period.withdrawals_kopecks)} ·{" "}
                <strong>Рост отдельно:</strong> {money(monthly.data.period.growth_kopecks)}
              </p>
              <p>
                <strong>XIRR, годовых:</strong> {rate(monthly.data.period.xirr_annualized_return)} ·{" "}
                <strong>XIRR за период:</strong> {rate(monthly.data.period.xirr_period_return)} ·{" "}
                <strong>Цепной Modified Dietz (≈TWRR, приблизительно):</strong>{" "}
                {rate(monthly.data.period.chained_return)}
              </p>
              {monthly.data.defaults_applied.length > 0 && (
                <div>
                  <h3>Потоки по правилам по умолчанию (допущения)</h3>
                  <ul>
                    {monthly.data.defaults_applied.map((flow) => (
                      <li key={JSON.stringify(flow)}>
                        {flow.event_date} · {money(flow.amount_kopecks)} · {flow.classification}
                        {flow.included ? " · включён" : " · исключён"}
                        {flow.source_references.length > 0 &&
                          ` · строки: ${flow.source_references.join(", ")}`}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <ReturnGaps gaps={monthly.data.gaps} />
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
                          {assumptions(row.assumptions_used, row.income_assumptions_used)}
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
            <p className={styles.note}>
              Совместимые месячные показатели используют простой процент, не Modified Dietz. Полный
              результат и условная оценка облигаций показаны отдельно в блоке выше.
            </p>
            <ReturnGaps gaps={instruments.data.gaps} />
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
