import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { formatApiError } from "../api/client";
import {
  createIisContribution,
  createTaxBenefit,
  getIisProfile,
  listIisContributions,
  listTaxBenefits,
  upsertIisProfile,
} from "../api/iis";
import type { Account, IisContribution, IisProfile, TaxBenefit } from "../api/types";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  LoadingState,
  Panel,
  Select,
  Table,
  Td,
  Th,
} from "./ui";
import { formatMoney } from "../lib/format";
import { BENEFIT_STATUS_LABELS, IIS_TYPE_LABELS, labelOf } from "../lib/labels";
import { moneyAmount, normalizeMoneyInput, rub } from "../lib/money";

type Props = { accounts: Account[] };

export function IisAccountSection({ accounts }: Props) {
  const iisAccounts = useMemo(
    () =>
      accounts.filter((account) => account.account_type === "iis" && account.status === "active"),
    [accounts],
  );
  const [accountId, setAccountId] = useState("");
  const [profile, setProfile] = useState<IisProfile | null>(null);
  const [contributions, setContributions] = useState<IisContribution[]>([]);
  const [benefits, setBenefits] = useState<TaxBenefit[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [iisType, setIisType] = useState("type_a");
  const [openedAt, setOpenedAt] = useState("");
  const [contributionAmount, setContributionAmount] = useState("");
  const [contributionYear, setContributionYear] = useState(String(new Date().getFullYear()));
  const [benefitAmount, setBenefitAmount] = useState("");
  const [benefitYear, setBenefitYear] = useState(String(new Date().getFullYear()));
  const [benefitStatus, setBenefitStatus] = useState("planned");

  useEffect(() => {
    if (iisAccounts.length === 0) {
      setAccountId("");
      return;
    }
    setAccountId((current) =>
      current && iisAccounts.some((account) => String(account.id) === current)
        ? current
        : String(iisAccounts[0].id),
    );
  }, [iisAccounts]);

  const load = useCallback(async () => {
    const selectedId = Number(accountId);
    if (!Number.isInteger(selectedId) || selectedId < 1) {
      setProfile(null);
      setContributions([]);
      setBenefits([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [nextProfile, nextContributions, nextBenefits] = await Promise.all([
        getIisProfile(selectedId).catch(() => null),
        listIisContributions(selectedId),
        listTaxBenefits(selectedId),
      ]);
      setProfile(nextProfile);
      setContributions(nextContributions);
      setBenefits(nextBenefits);
      if (nextProfile) {
        setIisType(nextProfile.iis_type);
        setOpenedAt(nextProfile.opened_at);
      }
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, [accountId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    const selectedId = Number(accountId);
    if (!selectedId || !openedAt) {
      setError("Счёт ИИС и дата открытия обязательны");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await upsertIisProfile(selectedId, { iis_type: iisType, opened_at: openedAt });
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addContribution(event: FormEvent) {
    event.preventDefault();
    const selectedId = Number(accountId);
    if (!selectedId || !normalizeMoneyInput(contributionAmount)) {
      setError("Счёт ИИС и сумма взноса обязательны");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createIisContribution(selectedId, {
        tax_year: Number(contributionYear),
        amount: rub(contributionAmount),
      });
      setContributionAmount("");
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addBenefit(event: FormEvent) {
    event.preventDefault();
    const selectedId = Number(accountId);
    if (!selectedId || !normalizeMoneyInput(benefitAmount)) {
      setError("Счёт ИИС и сумма льготы обязательны");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createTaxBenefit(selectedId, {
        tax_year: Number(benefitYear),
        benefit_type: "type_a",
        status: benefitStatus,
        amount: rub(benefitAmount),
      });
      setBenefitAmount("");
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (iisAccounts.length === 0) return null;
  if (loading) return <LoadingState description="Загружаем данные ИИС…" inline />;

  return (
    <Panel action={<Badge>счётный контекст</Badge>} label="Счета и инструменты" title="ИИС">
      {error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {error}
        </div>
      ) : null}
      <div className="editor-grid filter-grid">
        <Field htmlFor="account-iis" label="Счёт ИИС">
          <Select
            id="account-iis"
            onChange={(event) => setAccountId(event.target.value)}
            value={accountId}
          >
            {iisAccounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <div className="inline-alert inline-alert--warn" role="status">
        Налоговые льготы и статусы хранятся справочно. Это не налоговый расчёт и не замена
        декларации.
      </div>
      <form className="form-stack asset-form" onSubmit={saveProfile}>
        <div className="editor-grid">
          <Field htmlFor="account-iis-type" label="Тип ИИС">
            <Select
              id="account-iis-type"
              onChange={(event) => setIisType(event.target.value)}
              value={iisType}
            >
              <option value="type_a">Тип А</option>
              <option value="type_b">Тип Б</option>
              <option value="type_3">Тип 3</option>
            </Select>
          </Field>
          <Field htmlFor="account-iis-opened" label="Дата открытия">
            <Input
              id="account-iis-opened"
              onChange={(event) => setOpenedAt(event.target.value)}
              required
              type="date"
              value={openedAt}
            />
          </Field>
        </div>
        <Button disabled={busy} type="submit" variant="primary">
          Сохранить профиль ИИС
        </Button>
        {profile ? <p className="muted field-hint">Профиль открыт {profile.opened_at}</p> : null}
      </form>

      <h3 className="section-subhead">Взносы</h3>
      {contributions.length === 0 ? (
        <EmptyState description="Взносов нет." inline title="Пусто" />
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Год</Th>
              <Th numeric>Сумма</Th>
              <Th>Цель</Th>
            </tr>
          </thead>
          <tbody>
            {contributions.map((row) => (
              <tr key={row.id}>
                <Td>{row.tax_year}</Td>
                <Td numeric>{formatMoney(moneyAmount(row.amount))}</Td>
                <Td>{row.is_target_reached ? "достигнута" : "—"}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <form className="form-stack asset-form" onSubmit={addContribution}>
        <div className="editor-grid">
          <Field htmlFor="account-iis-contribution-year" label="Налоговый год взноса">
            <Input
              id="account-iis-contribution-year"
              onChange={(event) => setContributionYear(event.target.value)}
              type="number"
              value={contributionYear}
            />
          </Field>
          <Field htmlFor="account-iis-contribution-amount" label="Сумма взноса">
            <Input
              className="input--money"
              id="account-iis-contribution-amount"
              onChange={(event) => setContributionAmount(event.target.value)}
              required
              value={contributionAmount}
            />
          </Field>
        </div>
        <Button disabled={busy} type="submit">
          Добавить взнос
        </Button>
      </form>

      <h3 className="section-subhead">Налоговые льготы (справочно)</h3>
      {benefits.length === 0 ? (
        <EmptyState description="Налоговых льгот нет." inline title="Пусто" />
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Год</Th>
              <Th>Тип</Th>
              <Th>Статус</Th>
              <Th numeric>Сумма</Th>
            </tr>
          </thead>
          <tbody>
            {benefits.map((row) => (
              <tr key={row.id}>
                <Td>{row.tax_year}</Td>
                <Td>{labelOf(IIS_TYPE_LABELS, row.benefit_type)}</Td>
                <Td>{labelOf(BENEFIT_STATUS_LABELS, row.status)}</Td>
                <Td numeric>{formatMoney(moneyAmount(row.amount))}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <form className="form-stack asset-form" onSubmit={addBenefit}>
        <div className="editor-grid">
          <Field htmlFor="account-iis-benefit-year" label="Налоговый год льготы">
            <Input
              id="account-iis-benefit-year"
              onChange={(event) => setBenefitYear(event.target.value)}
              type="number"
              value={benefitYear}
            />
          </Field>
          <Field htmlFor="account-iis-benefit-status" label="Статус льготы">
            <Select
              id="account-iis-benefit-status"
              onChange={(event) => setBenefitStatus(event.target.value)}
              value={benefitStatus}
            >
              <option value="planned">Запланировано</option>
              <option value="submitted">Подано</option>
              <option value="received">Получено</option>
              <option value="rejected">Отклонено</option>
            </Select>
          </Field>
          <Field htmlFor="account-iis-benefit-amount" label="Сумма льготы">
            <Input
              className="input--money"
              id="account-iis-benefit-amount"
              onChange={(event) => setBenefitAmount(event.target.value)}
              required
              value={benefitAmount}
            />
          </Field>
        </div>
        <Button disabled={busy} type="submit">
          Добавить льготу
        </Button>
      </form>
    </Panel>
  );
}
