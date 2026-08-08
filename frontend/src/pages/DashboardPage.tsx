import { BackendStatus } from "../components/BackendStatus";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Field,
  Input,
  KpiCard,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "../components/ui";
import {
  formatDate,
  formatMoney,
  formatMoneyDelta,
  formatMonth,
  formatPercent,
  formatRatio,
} from "../lib/format";

/** Visual shell only — synthetic labels, no live finance wiring (E01). */
const PLACEHOLDER_MONTHS = [
  {
    period: formatMonth(2026, 7),
    status: "draft" as const,
    snapshot: "2026-07-31",
    passive: "86420",
  },
  {
    period: formatMonth(2026, 6),
    status: "closed" as const,
    snapshot: "2026-06-30",
    passive: "85220",
  },
  {
    period: formatMonth(2026, 5),
    status: "closed" as const,
    snapshot: "2026-05-31",
    passive: "81900",
  },
];

export function DashboardPage() {
  return (
    <section className="dashboard stack-18">
      <header className="page-header">
        <p className="eyebrow">Обзор</p>
        <h1>Дашборд</h1>
        <p className="page-header__description">
          Визуальный каркас Hermes Finance: навигация, KPI, таблица, форма и состояния. Финансовые
          цифры ниже — placeholder, без подключения доменных данных.
        </p>
      </header>

      <div className="toolbar">
        <Button variant="primary" type="button" disabled>
          Создать следующий месяц
        </Button>
        <Button type="button" disabled>
          Обновить сводку
        </Button>
      </div>

      <section className="kpi-grid" aria-label="KPI placeholder">
        <KpiCard
          label="Ликвидный капитал"
          value={formatMoney("4820500")}
          delta={`${formatPercent("2.4", { signed: true })} · месяц`}
          deltaTone="up"
        />
        <KpiCard
          label="Пассив / мес"
          value={formatMoney("86420")}
          delta={formatMoneyDelta("1200")}
          deltaTone="up"
        />
        <KpiCard
          label="Ипотека"
          value={formatMoney("12450000")}
          delta={formatMoneyDelta("-48200")}
          deltaTone="down"
        />
        <KpiCard
          label="Покрытие"
          value={formatRatio("0.68")}
          delta="цель 1,00×"
          deltaTone="neutral"
        />
      </section>

      <div className="dashboard-grid">
        <BackendStatus />

        <Panel empty label="Финансовая сводка" title="Данные ещё не подключены">
          <p>
            Живые KPI, allocation и calendar появятся после wiring dashboard API. Сейчас — только
            design system и layout.
          </p>
          <span className="pending-badge">E02+</span>
        </Panel>
      </div>

      <div className="dashboard-grid">
        <Panel action={<Badge>placeholder</Badge>} label="Периоды" title="Отчётные месяцы">
          <Table>
            <thead>
              <tr>
                <Th>Период</Th>
                <Th>Статус</Th>
                <Th numeric>Снимок</Th>
                <Th numeric>Пассив</Th>
              </tr>
            </thead>
            <tbody>
              {PLACEHOLDER_MONTHS.map((row) => (
                <tr key={row.snapshot}>
                  <Td>{row.period}</Td>
                  <Td>
                    <Badge tone={row.status === "draft" ? "draft" : "closed"}>{row.status}</Badge>
                  </Td>
                  <Td numeric>{formatDate(row.snapshot)}</Td>
                  <Td numeric>{formatMoney(row.passive)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>

        <Panel label="Форма" title="Новый черновик">
          <form
            className="form-stack"
            onSubmit={(event) => {
              event.preventDefault();
            }}
          >
            <Field htmlFor="period" label="Период">
              <Input id="period" name="period" defaultValue="Август 2026" readOnly />
            </Field>
            <Field htmlFor="source" label="Источник">
              <Select id="source" name="source" defaultValue="clone" disabled>
                <option value="clone">Клонировать предыдущий</option>
                <option value="manual">С нуля</option>
              </Select>
            </Field>
            <Field htmlFor="note" label="Комментарий">
              <Input id="note" name="note" placeholder="Необязательно" disabled />
            </Field>
            <Button variant="primary" block type="submit" disabled>
              Сохранить
            </Button>
          </form>
        </Panel>
      </div>

      <Panel label="Примитивы" title="Loading · Error · Empty">
        <div className="states-grid">
          <LoadingState description="Собираем dashboard…" />
          <ErrorState description="Backend недоступен на 127.0.0.1:8000" />
          <EmptyState description="Месяцев пока нет — создай первый период" />
        </div>
      </Panel>
    </section>
  );
}
