import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { ApiClientError, formatApiError } from "../api/client";
import { listAccounts } from "../api/accounts";
import {
  createIisContribution,
  createTaxBenefit,
  getIisProfile,
  listIisContributions,
  listTaxBenefits,
  upsertIisProfile,
} from "../api/iis";
import { getTaxIisPlanner } from "../api/taxIisPlanner";
import type { Account, IisContribution, IisProfile, TaxBenefit } from "../api/types";
import { formatMoney } from "../lib/format";
import { BENEFIT_STATUS_LABELS, IIS_TYPE_LABELS, labelOf } from "../lib/labels";
import { normalizeMoneyInput } from "../lib/money";
import styles from "./UiV2IisAccountForms.module.css";

type Snapshot = {
  profile: IisProfile | null;
  contributions: IisContribution[];
  benefits: TaxBenefit[];
};

type Props = {
  account: Account;
  plannerPath: string;
};

const STATUS_OPTIONS = ["planned", "submitted", "received", "rejected"] as const;

function taxYear(value: string): number | null {
  if (!/^\d{4}$/.test(value)) return null;
  const year = Number(value);
  return year >= 1900 && year <= 9999 ? year : null;
}

function validDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    year >= 1900 &&
    date.getUTCFullYear() === year &&
    date.getUTCMonth() + 1 === month &&
    date.getUTCDate() === day
  );
}

function amount(value: string): string | null {
  const normalized = normalizeMoneyInput(value);
  return normalized && !normalized.startsWith("-") ? normalized : null;
}

function sameProfile(left: IisProfile | null, right: IisProfile | null): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

async function readAccount(accountId: number, signal?: AbortSignal): Promise<Snapshot> {
  const [profile, contributions, benefits] = await Promise.all([
    getIisProfile(accountId, signal).catch((error: unknown) => {
      if (error instanceof ApiClientError && error.status === 404) return null;
      throw error;
    }),
    listIisContributions(accountId, signal),
    listTaxBenefits(accountId, signal),
  ]);
  if (
    (profile && profile.account_id !== accountId) ||
    contributions.some((row) => row.account_id !== accountId) ||
    benefits.some((row) => row.account_id !== accountId)
  ) {
    throw new Error("Сервер вернул данные другого счёта ИИС.");
  }
  return { profile, contributions, benefits };
}

export function UiV2IisAccountForms({ account, plannerPath }: Props) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [iisType, setIisType] = useState("type_a");
  const [openedAt, setOpenedAt] = useState("");
  const [contributionYear, setContributionYear] = useState(String(new Date().getFullYear()));
  const [contributionAmount, setContributionAmount] = useState("");
  const [benefitYear, setBenefitYear] = useState(String(new Date().getFullYear()));
  const [benefitStatus, setBenefitStatus] = useState<(typeof STATUS_OPTIONS)[number]>("planned");
  const [benefitAmount, setBenefitAmount] = useState("");
  const inFlight = useRef(false);
  const generation = useRef(0);

  const refresh = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const next = await readAccount(account.id);
      if (generation.current !== current) return;
      setSnapshot(next);
      if (next.profile) {
        setIisType(next.profile.iis_type);
        setOpenedAt(next.profile.opened_at);
      }
    } catch (cause) {
      if (generation.current !== current) return;
      setSnapshot(null);
      setError(formatApiError(cause));
    } finally {
      if (generation.current === current) setLoading(false);
    }
  }, [account.id]);

  useEffect(() => {
    void refresh();
    return () => {
      generation.current += 1;
    };
  }, [refresh]);

  async function runWrite(
    preflight: (current: Snapshot) => string | null,
    write: (current: Snapshot) => Promise<unknown>,
    confirms: (next: Snapshot) => boolean,
    success: string,
    afterConfirmed?: () => void,
  ) {
    if (inFlight.current || !snapshot || locked || account.status !== "active") return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    const currentGeneration = generation.current;
    let requestStarted = false;
    let writeCompleted = false;
    try {
      // A fresh account read prevents a stale form from overwriting a profile or
      // submitting a second row for a tax year already written elsewhere.
      const [currentAccounts, before] = await Promise.all([
        listAccounts(),
        readAccount(account.id),
      ]);
      if (generation.current !== currentGeneration) return;
      if (
        !currentAccounts.some(
          (row) => row.id === account.id && row.account_type === "iis" && row.status === "active",
        )
      ) {
        setLocked(true);
        setError("Счёт больше не является активным ИИС. Обновите каталог счетов.");
        return;
      }
      const rejection = preflight(before);
      if (rejection) {
        setSnapshot(before);
        if (before.profile) {
          setIisType(before.profile.iis_type);
          setOpenedAt(before.profile.opened_at);
        }
        setError(rejection);
        return;
      }
      requestStarted = true;
      await write(before);
      writeCompleted = true;
      if (generation.current !== currentGeneration) return;
      const [next, planner, confirmedAccounts] = await Promise.all([
        readAccount(account.id),
        getTaxIisPlanner(before.profile ? { accountId: account.id } : {}),
        listAccounts(),
      ]);
      if (generation.current !== currentGeneration) return;
      if (
        !confirms(next) ||
        (next.profile !== null &&
          !planner.iis_accounts.some((row) => row.account_id === account.id)) ||
        !confirmedAccounts.some((row) => row.id === account.id && row.account_type === "iis")
      ) {
        setLocked(true);
        setError(
          "Запись не подтверждена повторным чтением. Обновите данные перед новым действием.",
        );
        return;
      }
      setSnapshot(next);
      setNotice(success);
      afterConfirmed?.();
    } catch (cause) {
      if (generation.current !== currentGeneration) return;
      const ambiguous =
        writeCompleted ||
        (requestStarted &&
          (!(cause instanceof ApiClientError) || cause.status === 0 || cause.status >= 500));
      if (ambiguous) {
        setLocked(true);
        setError(
          "Результат записи неясен. Проверьте сохранённые данные ИИС; новый запрос в этой форме заблокирован до повторного открытия страницы.",
        );
      } else {
        setError(formatApiError(cause));
      }
    } finally {
      inFlight.current = false;
      if (generation.current === currentGeneration) setBusy(false);
    }
  }

  function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!validDate(openedAt)) {
      setError("Укажите существующую дату открытия ИИС.");
      return;
    }
    const type = iisType;
    const date = openedAt;
    void runWrite(
      (before) =>
        sameProfile(before.profile, snapshot?.profile ?? null)
          ? null
          : "Профиль ИИС изменился. Проверьте обновлённые данные перед сохранением.",
      (before) =>
        upsertIisProfile(account.id, {
          iis_type: type,
          opened_at: date,
          eligible_close_at: before.profile?.eligible_close_at ?? null,
          notes: before.profile?.notes ?? null,
        }),
      (next) => next.profile?.iis_type === type && next.profile.opened_at === date,
      "Профиль ИИС сохранён и подтверждён повторным чтением.",
    );
  }

  function addContribution(event: FormEvent) {
    event.preventDefault();
    const year = taxYear(contributionYear);
    const value = amount(contributionAmount);
    if (year === null || value === null) {
      setError("Укажите налоговый год 1900–9999 и неотрицательную сумму с точностью до копеек.");
      return;
    }
    void runWrite(
      (before) =>
        before.contributions.some((row) => row.tax_year === year)
          ? "Взнос за этот налоговый год уже есть. Повторное добавление недоступно."
          : null,
      () =>
        createIisContribution(account.id, {
          tax_year: year,
          amount: { amount: value, currency: "RUB" },
        }),
      (next) =>
        next.contributions.some(
          (row) =>
            row.tax_year === year && row.amount.amount === value && row.amount.currency === "RUB",
        ),
      `Взнос за ${year} год сохранён и подтверждён повторным чтением.`,
      () => setContributionAmount(""),
    );
  }

  function addBenefit(event: FormEvent) {
    event.preventDefault();
    const year = taxYear(benefitYear);
    const value = amount(benefitAmount);
    if (year === null || value === null) {
      setError("Укажите налоговый год 1900–9999 и неотрицательную сумму с точностью до копеек.");
      return;
    }
    const status = benefitStatus;
    void runWrite(
      (before) =>
        before.benefits.some((row) => row.tax_year === year && row.benefit_type === "type_a")
          ? "Вычет типа А за этот налоговый год уже есть. Повторное добавление недоступно."
          : null,
      () =>
        createTaxBenefit(account.id, {
          tax_year: year,
          benefit_type: "type_a",
          status,
          amount: { amount: value, currency: "RUB" },
        }),
      (next) =>
        next.benefits.some(
          (row) =>
            row.tax_year === year &&
            row.benefit_type === "type_a" &&
            row.status === status &&
            row.amount.amount === value &&
            row.amount.currency === "RUB",
        ),
      `Вычет за ${year} год сохранён и подтверждён повторным чтением.`,
      () => setBenefitAmount(""),
    );
  }

  const canWrite = account.status === "active" && !loading && !busy && !locked && snapshot !== null;

  return (
    <section
      aria-label={`ИИС: ${account.name}`}
      className={styles.panel}
      data-testid="catalog-iis-forms"
    >
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Счёт {account.id} · ИИС</p>
          <h2>{account.name}</h2>
          <p>
            Профиль, взносы и вычеты хранятся по счёту и налоговому году, независимо от отчётного
            месяца.
          </p>
        </div>
        <div className={styles.headerActions}>
          <button disabled={busy || loading} onClick={() => void refresh()} type="button">
            Обновить ИИС
          </button>
          <Link to={plannerPath}>Открыть планировщик ↗</Link>
        </div>
      </header>
      <p className={styles.caution}>
        Вычеты и статусы справочные. Запланированный или поданный вычет не считается полученным.
      </p>
      {account.status !== "active" ? (
        <p role="status">
          Запись ИИС доступна для просмотра; изменения разрешены только активному счёту.
        </p>
      ) : null}
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className={styles.success} role="status">
          {notice}
        </p>
      ) : null}
      {loading ? <p role="status">Загружаем данные ИИС…</p> : null}
      {snapshot ? (
        <div className={styles.sections}>
          <section>
            <h3>Профиль ИИС</h3>
            <form className={styles.form} onSubmit={saveProfile}>
              <label>
                Тип ИИС
                <select
                  disabled={!canWrite}
                  onChange={(event) => setIisType(event.target.value)}
                  value={iisType}
                >
                  <option value="type_a">Тип А</option>
                  <option value="type_b">Тип Б</option>
                  <option value="type_3">Тип 3</option>
                </select>
              </label>
              <label>
                Дата открытия
                <input
                  disabled={!canWrite}
                  onChange={(event) => setOpenedAt(event.target.value)}
                  required
                  type="date"
                  value={openedAt}
                />
              </label>
              <button disabled={!canWrite} type="submit">
                Сохранить профиль
              </button>
            </form>
            {snapshot.profile ? (
              <p className={styles.hint}>
                Дата доступного закрытия: {snapshot.profile.eligible_close_at ?? "не указана"}
              </p>
            ) : null}
          </section>
          <section>
            <h3>Взносы</h3>
            {snapshot.contributions.length ? (
              <ul className={styles.rows}>
                {snapshot.contributions.map((row) => (
                  <li key={row.id}>
                    {row.tax_year}: {formatMoney(row.amount.amount)} ·{" "}
                    {row.is_target_reached ? "цель достигнута" : "цель не достигнута"}
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.hint}>Взносов пока нет.</p>
            )}
            <form className={styles.form} onSubmit={addContribution}>
              <label>
                Налоговый год взноса
                <input
                  disabled={!canWrite}
                  max="9999"
                  min="1900"
                  onChange={(event) => setContributionYear(event.target.value)}
                  required
                  type="number"
                  value={contributionYear}
                />
              </label>
              <label>
                Сумма взноса, ₽
                <input
                  disabled={!canWrite}
                  inputMode="decimal"
                  onChange={(event) => setContributionAmount(event.target.value)}
                  required
                  value={contributionAmount}
                />
              </label>
              <button
                disabled={
                  !canWrite ||
                  snapshot.contributions.some((row) => row.tax_year === taxYear(contributionYear))
                }
                type="submit"
              >
                Добавить взнос
              </button>
            </form>
          </section>
          <section>
            <h3>Налоговые вычеты</h3>
            {snapshot.benefits.length ? (
              <ul className={styles.rows}>
                {snapshot.benefits.map((row) => (
                  <li key={row.id}>
                    {row.tax_year} · {labelOf(IIS_TYPE_LABELS, row.benefit_type)} ·{" "}
                    {labelOf(BENEFIT_STATUS_LABELS, row.status)} · {formatMoney(row.amount.amount)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.hint}>Вычетов пока нет.</p>
            )}
            <form className={styles.form} onSubmit={addBenefit}>
              <label>
                Налоговый год вычета
                <input
                  disabled={!canWrite}
                  max="9999"
                  min="1900"
                  onChange={(event) => setBenefitYear(event.target.value)}
                  required
                  type="number"
                  value={benefitYear}
                />
              </label>
              <label>
                Статус вычета
                <select
                  disabled={!canWrite}
                  onChange={(event) =>
                    setBenefitStatus(event.target.value as (typeof STATUS_OPTIONS)[number])
                  }
                  value={benefitStatus}
                >
                  {STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>
                      {labelOf(BENEFIT_STATUS_LABELS, status)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Сумма вычета, ₽
                <input
                  disabled={!canWrite}
                  inputMode="decimal"
                  onChange={(event) => setBenefitAmount(event.target.value)}
                  required
                  value={benefitAmount}
                />
              </label>
              <button
                disabled={
                  !canWrite ||
                  snapshot.benefits.some(
                    (row) => row.tax_year === taxYear(benefitYear) && row.benefit_type === "type_a",
                  )
                }
                type="submit"
              >
                Добавить вычет типа А
              </button>
            </form>
          </section>
        </div>
      ) : null}
    </section>
  );
}
