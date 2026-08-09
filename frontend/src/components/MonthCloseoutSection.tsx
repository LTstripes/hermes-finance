import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { listAccounts } from "../api/accounts";
import { formatApiError } from "../api/client";
import { createComment, deleteComment, listComments, moveComment } from "../api/comments";
import { getDashboard } from "../api/dashboard";
import {
  createIisContribution,
  createTaxBenefit,
  getIisProfile,
  listIisContributions,
  listTaxBenefits,
  upsertIisProfile,
} from "../api/iis";
import { closeMonth, reopenMonth } from "../api/months";
import { getMonthSummary } from "../api/summary";
import type {
  Account,
  DashboardKpis,
  IisContribution,
  IisProfile,
  MonthlyComment,
  MoneyValue,
  TaxBenefit,
} from "../api/types";
import {
  Badge,
  Button,
  ConfirmDialog,
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
import { moneyAmount, normalizeMoneyInput, rub } from "../lib/money";

type Props = {
  monthId: number;
  readOnly: boolean;
  year: number;
  status: "draft" | "closed";
  onStatusChanged: () => void;
};

export function MonthCloseoutSection({ monthId, readOnly, year, status, onStatusChanged }: Props) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [iisAccountId, setIisAccountId] = useState("");
  const [profile, setProfile] = useState<IisProfile | null>(null);
  const [contributions, setContributions] = useState<IisContribution[]>([]);
  const [benefits, setBenefits] = useState<TaxBenefit[]>([]);
  const [comments, setComments] = useState<MonthlyComment[]>([]);
  const [goalTarget, setGoalTarget] = useState<MoneyValue | null>(null);
  const [goalProgress, setGoalProgress] = useState<string | null>(null);
  const [previewKpis, setPreviewKpis] = useState<DashboardKpis | null>(null);
  const [previewWarnings, setPreviewWarnings] = useState<string[]>([]);
  const [pendingAction, setPendingAction] = useState<"close" | "reopen" | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [iisType, setIisType] = useState("type_a");
  const [openedAt, setOpenedAt] = useState(`${year}-01-01`);
  const [contribAmount, setContribAmount] = useState("");
  const [contribYear, setContribYear] = useState(String(year));
  const [benefitAmount, setBenefitAmount] = useState("");
  const [benefitYear, setBenefitYear] = useState(String(year));
  const [benefitStatus, setBenefitStatus] = useState("planned");
  const [commentText, setCommentText] = useState("");
  const [delComment, setDelComment] = useState<MonthlyComment | null>(null);

  const iisAccounts = useMemo(
    () => accounts.filter((a) => a.account_type === "iis" && a.status === "active"),
    [accounts],
  );

  const loadBase = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const [accs, comms, summary, dashboard] = await Promise.all([
          listAccounts(signal),
          listComments(monthId, signal),
          getMonthSummary(monthId, signal).catch(() => null),
          getDashboard(monthId, signal).catch(() => null),
        ]);
        if (signal?.aborted) return;
        setAccounts(accs);
        setComments(comms);
        setGoalTarget(summary?.coverage?.goal_target ?? null);
        setGoalProgress(summary?.coverage?.goal_progress_pct ?? null);
        setPreviewKpis(dashboard?.kpis ?? null);
        setPreviewWarnings(dashboard?.warnings ?? []);
        const firstIis = accs.find((a) => a.account_type === "iis" && a.status === "active");
        if (firstIis && !iisAccountId) {
          setIisAccountId(String(firstIis.id));
        }
      } catch (err) {
        if (!signal?.aborted) setError(formatApiError(err));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [iisAccountId, monthId],
  );

  const loadIis = useCallback(
    async (signal?: AbortSignal) => {
      const accountId = Number(iisAccountId);
      if (!Number.isInteger(accountId) || accountId < 1) {
        setProfile(null);
        setContributions([]);
        setBenefits([]);
        return;
      }
      try {
        const [p, c, b] = await Promise.all([
          getIisProfile(accountId, signal).catch(() => null),
          listIisContributions(accountId, signal).catch(() => []),
          listTaxBenefits(accountId, signal).catch(() => []),
        ]);
        if (signal?.aborted) return;
        setProfile(p);
        if (p) {
          setIisType(p.iis_type);
          setOpenedAt(p.opened_at);
        }
        setContributions(c);
        setBenefits(b);
      } catch (err) {
        if (!signal?.aborted) setActionError(formatApiError(err));
      }
    },
    [iisAccountId],
  );

  useEffect(() => {
    const c = new AbortController();
    void loadBase(c.signal);
    return () => c.abort();
  }, [loadBase]);

  useEffect(() => {
    const c = new AbortController();
    void loadIis(c.signal);
    return () => c.abort();
  }, [loadIis]);

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    const accountId = Number(iisAccountId);
    if (!accountId) {
      setActionError("Выбери IIS-счёт");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      const p = await upsertIisProfile(accountId, {
        iis_type: iisType,
        opened_at: openedAt,
      });
      setProfile(p);
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addContribution(event: FormEvent) {
    event.preventDefault();
    const accountId = Number(iisAccountId);
    setBusy(true);
    setActionError(null);
    try {
      if (!accountId || !normalizeMoneyInput(contribAmount)) {
        throw new Error("IIS account и сумма обязательны");
      }
      await createIisContribution(accountId, {
        tax_year: Number(contribYear),
        amount: rub(contribAmount),
      });
      setContribAmount("");
      await loadIis();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addBenefit(event: FormEvent) {
    event.preventDefault();
    const accountId = Number(iisAccountId);
    setBusy(true);
    setActionError(null);
    try {
      if (!accountId || !normalizeMoneyInput(benefitAmount)) {
        throw new Error("IIS account и сумма benefit обязательны");
      }
      await createTaxBenefit(accountId, {
        tax_year: Number(benefitYear),
        benefit_type: "type_a",
        status: benefitStatus,
        amount: rub(benefitAmount),
      });
      setBenefitAmount("");
      await loadIis();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function addComment(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    try {
      if (!commentText.trim()) throw new Error("Текст комментария пуст");
      await createComment({ reporting_month_id: monthId, text: commentText.trim() });
      setCommentText("");
      await loadBase();
    } catch (err) {
      setActionError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState description="Загружаем ИИС и комментарии…" inline />;
  if (error) return <EmptyState description={error} inline title="Ошибка" />;

  return (
    <div className="stack-18">
      {actionError ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {actionError}
        </div>
      ) : null}

      <Panel
        action={
          status === "closed" ? (
            <Badge tone="closed">closed</Badge>
          ) : (
            <Badge tone="draft">draft</Badge>
          )
        }
        label="Закрытие ввода"
        title="Закрытие месяца"
      >
        {previewKpis ? (
          <div className="totals-bar">
            <span>
              Liquid capital:{" "}
              <strong>{formatMoney(moneyAmount(previewKpis.liquid_capital_net))}</strong>
            </span>
            <span>
              Passive avg:{" "}
              <strong>{formatMoney(moneyAmount(previewKpis.passive_income_average))}</strong>
            </span>
            <span>
              Passive forecast:{" "}
              <strong>
                {formatMoney(moneyAmount(previewKpis.forecast_monthly_passive_income))}
              </strong>
            </span>
            <span>
              Goal:{" "}
              <strong>
                {previewKpis.goal_progress_pct != null ? `${previewKpis.goal_progress_pct}%` : "—"}
              </strong>
            </span>
          </div>
        ) : (
          <p className="muted">KPI недоступны (dashboard не ответил).</p>
        )}

        {previewWarnings.length > 0 ? (
          <ul className="closeout-warnings">
            {previewWarnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">Предупреждений нет.</p>
        )}

        {status === "closed" ? (
          <p className="muted">
            Месяц закрыт — данные зафиксированы. Изменения возможны только после reopen.
          </p>
        ) : (
          <p className="muted">
            Закрытие фиксирует KPI и snapshots. Открыть заново можно в любой момент.
          </p>
        )}

        {status === "closed" ? (
          <Button disabled={busy} onClick={() => setPendingAction("reopen")} type="button">
            Открыть заново
          </Button>
        ) : (
          <Button
            disabled={busy || readOnly}
            onClick={() => setPendingAction("close")}
            type="button"
            variant="primary"
          >
            Закрыть месяц
          </Button>
        )}
      </Panel>

      <Panel label="Закрытие ввода" title="ИИС">
        <div className="inline-alert inline-alert--warn" role="status">
          Налоговые данные (benefits/status) — информационные. Это не налоговый расчёт и не замена
          декларации.
        </div>
        {iisAccounts.length === 0 ? (
          <EmptyState
            description="Нет счетов account_type=iis. Создай IIS-счёт в словаре accounts."
            inline
            title="Нет IIS"
          />
        ) : (
          <>
            <div className="editor-grid filter-grid">
              <Field htmlFor="iis-acc" label="IIS account">
                <Select
                  id="iis-acc"
                  onChange={(e) => setIisAccountId(e.target.value)}
                  value={iisAccountId}
                >
                  <option value="">—</option>
                  {iisAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            {!readOnly ? (
              <form className="form-stack asset-form" onSubmit={saveProfile}>
                <div className="editor-grid">
                  <Field htmlFor="iis-type" label="Тип ИИС">
                    <Select
                      id="iis-type"
                      onChange={(e) => setIisType(e.target.value)}
                      value={iisType}
                    >
                      <option value="type_a">type_a</option>
                      <option value="type_b">type_b</option>
                      <option value="type_3">type_3</option>
                    </Select>
                  </Field>
                  <Field htmlFor="iis-opened" label="Дата открытия">
                    <Input
                      id="iis-opened"
                      onChange={(e) => setOpenedAt(e.target.value)}
                      required
                      type="date"
                      value={openedAt}
                    />
                  </Field>
                </div>
                <Button disabled={busy || !iisAccountId} type="submit" variant="primary">
                  Сохранить профиль ИИС
                </Button>
                {profile ? (
                  <p className="muted field-hint">
                    Профиль id={profile.id}, opened {profile.opened_at}
                  </p>
                ) : null}
              </form>
            ) : null}

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
            {!readOnly ? (
              <form className="form-stack asset-form" onSubmit={addContribution}>
                <div className="editor-grid">
                  <Field htmlFor="c-year" label="Tax year взноса">
                    <Input
                      id="c-year"
                      onChange={(e) => setContribYear(e.target.value)}
                      type="number"
                      value={contribYear}
                    />
                  </Field>
                  <Field htmlFor="c-amt" label="Сумма взноса">
                    <Input
                      className="input--money"
                      id="c-amt"
                      onChange={(e) => setContribAmount(e.target.value)}
                      required
                      value={contribAmount}
                    />
                  </Field>
                </div>
                <Button disabled={busy || !iisAccountId} type="submit">
                  Добавить взнос
                </Button>
              </form>
            ) : null}

            <h3 className="section-subhead">Tax benefits (info)</h3>
            {benefits.length === 0 ? (
              <EmptyState description="Benefits нет." inline title="Пусто" />
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
                      <Td>{row.benefit_type}</Td>
                      <Td>{row.status}</Td>
                      <Td numeric>{formatMoney(moneyAmount(row.amount))}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            {!readOnly ? (
              <form className="form-stack asset-form" onSubmit={addBenefit}>
                <div className="editor-grid">
                  <Field htmlFor="b-year" label="Tax year benefit">
                    <Input
                      id="b-year"
                      onChange={(e) => setBenefitYear(e.target.value)}
                      type="number"
                      value={benefitYear}
                    />
                  </Field>
                  <Field htmlFor="b-status" label="Статус benefit">
                    <Select
                      id="b-status"
                      onChange={(e) => setBenefitStatus(e.target.value)}
                      value={benefitStatus}
                    >
                      <option value="planned">planned</option>
                      <option value="submitted">submitted</option>
                      <option value="received">received</option>
                      <option value="rejected">rejected</option>
                    </Select>
                  </Field>
                  <Field htmlFor="b-amt" label="Сумма benefit">
                    <Input
                      className="input--money"
                      id="b-amt"
                      onChange={(e) => setBenefitAmount(e.target.value)}
                      required
                      value={benefitAmount}
                    />
                  </Field>
                </div>
                <Button disabled={busy || !iisAccountId} type="submit">
                  Добавить benefit
                </Button>
              </form>
            ) : null}
          </>
        )}
      </Panel>

      <Panel
        action={<Badge>goal {goalProgress != null ? `${goalProgress}%` : "—"}</Badge>}
        label="Закрытие ввода"
        title="Основная цель"
      >
        <div className="inline-alert inline-alert--warn" role="status">
          API <code>/api/goals</code> отсутствует (gap). Ниже — progress из month summary coverage,
          если backend его отдаёт. CRUD целей в E-фазе не чиним.
        </div>
        <div className="totals-bar">
          <span>
            Goal target: <strong>{goalTarget ? formatMoney(moneyAmount(goalTarget)) : "—"}</strong>
          </span>
          <span>
            Progress: <strong>{goalProgress != null ? `${goalProgress}%` : "—"}</strong>
          </span>
        </div>
      </Panel>

      <Panel
        action={<Badge>{comments.length} шт.</Badge>}
        label="Закрытие ввода"
        title="Комментарии"
      >
        {comments.length === 0 ? (
          <EmptyState description="Комментариев нет." inline title="Пусто" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>#</Th>
                <Th>Текст</Th>
                <Th>Порядок</Th>
              </tr>
            </thead>
            <tbody>
              {comments.map((row, index) => (
                <tr key={row.id}>
                  <Td>{row.position}</Td>
                  <Td>{row.text}</Td>
                  <Td>
                    <div className="row-actions">
                      <Button
                        aria-label="Переместить комментарий выше"
                        disabled={busy || readOnly || index === 0}
                        onClick={() => {
                          setBusy(true);
                          void moveComment(row.id, Math.max(1, row.position - 1))
                            .then(() => loadBase())
                            .catch((err) => setActionError(formatApiError(err)))
                            .finally(() => setBusy(false));
                        }}
                        size="sm"
                        type="button"
                      >
                        ↑
                      </Button>
                      <Button
                        aria-label="Переместить комментарий ниже"
                        disabled={busy || readOnly || index === comments.length - 1}
                        onClick={() => {
                          setBusy(true);
                          void moveComment(row.id, row.position + 1)
                            .then(() => loadBase())
                            .catch((err) => setActionError(formatApiError(err)))
                            .finally(() => setBusy(false));
                        }}
                        size="sm"
                        type="button"
                      >
                        ↓
                      </Button>
                      <Button
                        disabled={busy || readOnly}
                        onClick={() => setDelComment(row)}
                        size="sm"
                        type="button"
                        variant="danger"
                      >
                        Удал.
                      </Button>
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {!readOnly ? (
          <form className="form-stack asset-form" onSubmit={addComment}>
            <Field htmlFor="cmt" label="Новый комментарий">
              <Input
                id="cmt"
                onChange={(e) => setCommentText(e.target.value)}
                required
                value={commentText}
              />
            </Field>
            <Button disabled={busy} type="submit" variant="primary">
              Добавить комментарий
            </Button>
          </form>
        ) : null}
      </Panel>

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel={pendingAction === "close" ? "Закрыть" : "Открыть заново"}
        danger={pendingAction === "close"}
        description={
          pendingAction === "close"
            ? "Закрыть месяц? KPI и snapshots будут зафиксированы; редактирование заблокируется до reopen."
            : "Открыть месяц заново? Данные снова станут редактируемыми."
        }
        onCancel={() => setPendingAction(null)}
        onConfirm={() => {
          if (!pendingAction) return;
          setBusy(true);
          const request = pendingAction === "close" ? closeMonth(monthId) : reopenMonth(monthId);
          void request
            .then(() => {
              setPendingAction(null);
              onStatusChanged();
            })
            .catch((err) => setActionError(formatApiError(err)))
            .finally(() => setBusy(false));
        }}
        open={pendingAction !== null}
        title={pendingAction === "close" ? "Закрыть месяц?" : "Открыть месяц заново?"}
      />

      <ConfirmDialog
        busy={busy}
        cancelLabel="Отмена"
        confirmLabel="Удалить"
        danger
        description={delComment ? `Удалить комментарий #${delComment.position}?` : ""}
        onCancel={() => setDelComment(null)}
        onConfirm={() => {
          if (!delComment) return;
          setBusy(true);
          void deleteComment(delComment.id)
            .then(() => loadBase())
            .catch((err) => setActionError(formatApiError(err)))
            .finally(() => {
              setBusy(false);
              setDelComment(null);
            });
        }}
        open={delComment !== null}
        title="Удалить комментарий?"
      />
    </div>
  );
}
