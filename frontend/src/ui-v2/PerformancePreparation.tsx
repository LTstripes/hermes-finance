import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { ApiClientError } from "../api/client";
import { getPerformanceReadiness } from "../api/performance";
import {
  type BoundaryCoverage,
  type ExternalFlow,
  getPreparation,
  type Preparation,
  savePreparation,
} from "../api/performancePreparation";
import type { Account } from "../api/types";
import { queryKeys } from "../queryClient";
import { isReadinessFresh } from "./CapitalPerformanceSummary";
import { type PerformanceContext, performanceDetailHref } from "./capitalPerformanceContext";
import { diagnosticCopy } from "./capitalPerformanceCopy";
import { HistoricalMembership } from "./HistoricalMembership";
import styles from "./UiV2CapitalPerformance.module.css";

type Save = (path: string, method: "POST" | "PATCH", body: unknown) => Promise<void>;

function evidenceLabel(value: string): string {
  const labels: Record<string, string> = {
    complete: "подтверждено",
    unknown: "не подтверждено",
    resolved: "согласован",
    unresolved: "не согласован",
    draft: "черновик",
    closed: "закрыт",
    external_contribution: "пополнение",
    external_withdrawal: "вывод",
    internal_transfer: "внутренний перевод",
    not_authoritative: "нет достаточного подтверждения",
    not_in_scope: "вне расчёта",
    stable_in_scope: "участие подтверждено",
    stable_out_of_scope: "исключение подтверждено",
    external_in: "внешнее поступление",
    external_out: "внешнее выбытие",
  };
  return labels[value] ?? "требуется проверка";
}

function CoverageForm({
  kind,
  data,
  locked,
  save,
}: {
  kind: "cash" | "in-kind";
  data: Preparation;
  locked: boolean;
  save: Save;
}) {
  const [attested, setAttested] = useState(false);
  const [complete, setComplete] = useState(false);
  const rows = kind === "cash" ? data.cash_coverages : data.in_kind_coverages;
  const exact = rows.filter(
    (r) => r.covered_from === data.start_date && r.covered_to === data.end_date,
  );
  const target: BoundaryCoverage | undefined =
    rows.length === 1 && exact.length === 1 ? exact[0] : undefined;
  const conflicting = rows.length > 0 && !target;
  const empty = kind === "cash" ? data.flows.length === 0 : data.movements.length === 0;
  const closed = data.months.some(
    (m) =>
      m.status === "closed" && m.period_start <= data.end_date && m.period_end >= data.start_date,
  );
  const name = kind === "cash" ? "Денежная история" : "Неденежная история";
  return (
    <fieldset disabled={locked || closed || conflicting} className={styles.compositionBlock}>
      <legend>{name}</legend>
      <p>
        {data.start_date} — {data.end_date}. Текущее подтверждение:{" "}
        {evidenceLabel(target?.coverage_state ?? "unknown")}.
      </p>
      {rows.map((r) => (
        <p key={r.id}>
          Запись {r.id}: {r.covered_from} — {r.covered_to}, {evidenceLabel(r.coverage_state)}
        </p>
      ))}
      {conflicting ? (
        <p role="alert">
          Есть другие пересекающиеся интервалы. Выберите точные границы одной записи для её
          проверки; перекрытия нельзя подтвердить этим действием.
        </p>
      ) : null}
      {closed ? (
        <p>
          Закрытый месяц: сначала явно откройте затронутые отчёты, затем перечитайте данные. После
          исправления закройте их заново.
        </p>
      ) : null}
      <label>
        <input
          type="checkbox"
          checked={complete}
          onChange={(e) => {
            setComplete(e.target.checked);
            setAttested(false);
          }}
        />{" "}
        История сверена полностью за весь указанный период
      </label>
      <p>
        {kind === "cash"
          ? "Денежное подтверждение не подтверждает неденежные движения и историю участия."
          : "Известные неденежные движения остаются отдельным ограничением: подтверждение не создаёт их оценку."}
      </p>
      <label>
        <input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} />
        {complete
          ? empty
            ? `Я проверил(а) источники: ${kind === "cash" ? "денежных пересечений" : "неденежных движений"} за этот период не было`
            : "Я проверил(а) показанные записи и источники: все движения за этот период учтены"
          : "Подтверждаю: история неполна или ещё не проверена; оставить её неподтверждённой"}
      </label>
      <p>Пустой список сам по себе не доказывает отсутствие операций.</p>
      <button
        type="button"
        className={styles.inlineButton}
        disabled={!attested}
        onClick={() =>
          void save(
            `/api/${kind}-boundary-coverages${target ? `/${target.id}` : ""}`,
            target ? "PATCH" : "POST",
            {
              account_id: data.account_id,
              covered_from: data.start_date,
              covered_to: data.end_date,
              coverage_state: complete ? "complete" : "unknown",
              provenance_kind: "owner_attestation",
            },
          )
        }
      >
        Сохранить: {name.toLowerCase()}
      </button>
    </fieldset>
  );
}

function FlowForm({
  data,
  accounts,
  flow,
  locked,
  save,
  cancel,
}: {
  data: Preparation;
  accounts: Account[];
  flow: ExternalFlow | null;
  locked: boolean;
  save: Save;
  cancel: () => void;
}) {
  const [account, setAccount] = useState(String(flow?.account_id ?? ""));
  const [eventDate, setEventDate] = useState(flow?.event_date ?? "");
  const [month, setMonth] = useState(String(flow?.reporting_month_id ?? ""));
  const [amount, setAmount] = useState(flow?.boundary_amount.amount ?? "");
  const [direction, setDirection] = useState(flow?.direction ?? "contribution");
  const [membership, setMembership] = useState(flow?.scope_membership ?? "unknown");
  const [source, setSource] = useState(flow?.source ?? "manual");
  const [transfer, setTransfer] = useState(flow?.transfer_link_id != null);
  const [link, setLink] = useState(String(flow?.transfer_link_id ?? ""));
  const [attested, setAttested] = useState(false);
  const chosen = data.months.find((m) => m.id === Number(month));
  const valid =
    accounts.some((a) => String(a.id) === account) &&
    chosen?.status === "draft" &&
    eventDate >= data.start_date &&
    eventDate <= data.end_date &&
    /^\d+(\.\d{1,2})?$/.test(amount) &&
    source.trim() &&
    (!transfer || /^[1-9]\d*$/.test(link));
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid || !attested || locked) return;
        void save(`/api/external-flows${flow ? `/${flow.id}` : ""}`, flow ? "PATCH" : "POST", {
          ...(flow ? {} : { reporting_month_id: Number(month) }),
          account_id: Number(account),
          event_date: eventDate,
          boundary_amount: { amount, currency: "RUB" },
          direction,
          kind: direction === "contribution" ? "external_contribution" : "external_withdrawal",
          scope_membership: membership,
          source,
          transfer_link_id: transfer ? Number(link) : null,
        });
      }}
    >
      <fieldset disabled={locked} className={styles.compositionBlock}>
        <legend>{flow ? `Исправление операции ${flow.id}` : "Новая операция"}</legend>
        <div className={styles.controls} onChange={() => setAttested(false)}>
          <label>
            Счёт
            <select
              aria-label="Счёт операции"
              value={account}
              onChange={(e) => setAccount(e.target.value)}
            >
              <option value="">Выберите счёт</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Отчёт
            <select
              aria-label="Отчёт операции"
              disabled={flow !== null}
              value={month}
              onChange={(e) => setMonth(e.target.value)}
            >
              <option value="">Выберите отчёт</option>
              {data.months.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.period_start} — {m.period_end} · {evidenceLabel(m.status)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Дата
            <input
              type="date"
              aria-label="Дата операции"
              value={eventDate}
              min={data.start_date}
              max={data.end_date}
              onChange={(e) => setEventDate(e.target.value)}
            />
          </label>
          <label>
            Точная сумма, RUB
            <input
              inputMode="decimal"
              aria-label="Сумма операции"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </label>
          <label>
            Направление и вид
            <select
              aria-label="Вид операции"
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
            >
              <option value="contribution">Пополнение</option>
              <option value="withdrawal">Вывод</option>
            </select>
          </label>
          <label>
            Участие для этой операции
            <select
              aria-label="Участие операции"
              value={membership}
              onChange={(e) => setMembership(e.target.value)}
            >
              <option value="unknown">Не подтверждено</option>
              <option value="stable_in_scope">Подтверждено участие</option>
              <option value="stable_out_of_scope">Подтверждено исключение</option>
            </select>
          </label>
          <label>
            Источник
            <input
              aria-label="Источник операции"
              maxLength={64}
              value={source}
              onChange={(e) => setSource(e.target.value)}
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={transfer}
              onChange={(e) => setTransfer(e.target.checked)}
            />{" "}
            Это перевод между счетами
          </label>
          {transfer ? (
            <label>
              Связь перевода
              <select
                aria-label="Связь перевода"
                value={link}
                onChange={(e) => setLink(e.target.value)}
              >
                <option value="">Выберите связь</option>
                {data.transfer_links.map((t) => (
                  <option key={t.id} value={t.id}>
                    Связь {t.id} · {evidenceLabel(t.status)} · операции{" "}
                    {t.flow_ids.join(", ") || "не добавлены"}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        <p>
          Участие операции не заполняет исторический состав счетов. Перевод требует явной
          существующей связи; неполный или конфликтующий перевод не считается внешним потоком
          портфеля автоматически.
        </p>
        <label>
          <input
            type="checkbox"
            checked={attested}
            onChange={(e) => setAttested(e.target.checked)}
          />{" "}
          Я проверил(а) дату, счёт, сумму, вид операции и связь перевода по источнику
        </label>
        {chosen?.status === "closed" ? (
          <p role="alert">
            Закрытый отчёт: требуется явное повторное открытие и последующее повторное закрытие.
          </p>
        ) : null}
        <p>Изменение операции может отменить подтверждение денежной истории и наблюдения TWRR.</p>
        <button type="submit" className={styles.inlineButton} disabled={!valid || !attested}>
          Сохранить операцию
        </button>{" "}
        <button type="button" className={styles.inlineButton} onClick={cancel}>
          Отменить ввод
        </button>
      </fieldset>
    </form>
  );
}

function PreparationForms({
  data,
  accounts,
  locked,
  save,
}: {
  data: Preparation;
  accounts: Account[];
  locked: boolean;
  save: Save;
}) {
  const [editing, setEditing] = useState<ExternalFlow | null | undefined>(undefined);
  return (
    <>
      <h4>Известные денежные операции</h4>
      <p>
        Отчёты периода:{" "}
        {data.months.map((m) => (
          <span key={m.id}>
            <Link to={`/months/${m.id}`}>
              {m.period_start} — {m.period_end} ({evidenceLabel(m.status)})
            </Link>
            {"; "}
          </span>
        ))}
        . Открытие и закрытие выполняются явно в отчёте. Вернитесь назад и перечитайте данные для
        проверки.
      </p>
      <p>
        Перевод между счетами: создайте связь, затем явно укажите её у обеих операций на
        соответствующих счетах. Пока обе стороны не согласованы, перевод остаётся неподтверждённым.
        Конфликты и подтверждения сверки обрабатываются сервером; автоматического сопоставления нет.
      </p>
      <button
        type="button"
        className={styles.inlineButton}
        disabled={locked}
        onClick={() => void save("/api/transfer-links", "POST", { flow_ids: [] })}
      >
        Создать связь перевода
      </button>
      <p>Включая начальную дату для проверки источников; границы расчёта определяет сервер.</p>
      {data.flows.length === 0 ? (
        <p>Записей нет. Это не подтверждение нулевой активности.</p>
      ) : (
        <ul className={styles.diagnosticList}>
          {data.flows.map((f) => (
            <li key={f.id} className={styles.diagnosticItem}>
              <p>
                {f.event_date} · {f.boundary_amount.amount} {f.boundary_amount.currency} ·{" "}
                {evidenceLabel(f.kind)} · источник: {f.source}
              </p>
              <p>
                Участие: {evidenceLabel(f.scope_membership)}. Портфель:{" "}
                {evidenceLabel(f.portfolio_scope_classification)}; счёт:{" "}
                {evidenceLabel(f.account_scope_classification)}. Связь перевода:{" "}
                {f.transfer_link_id ?? "нет"} (
                {f.transfer_status ? evidenceLabel(f.transfer_status) : "—"}).
              </p>
              <button
                type="button"
                className={styles.inlineButton}
                disabled={locked}
                onClick={() => setEditing(f)}
              >
                Исправить операцию {f.id}
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        className={styles.inlineButton}
        disabled={locked}
        onClick={() => setEditing(null)}
      >
        Добавить операцию
      </button>
      {editing !== undefined ? (
        <FlowForm
          key={editing?.id ?? "new"}
          data={data}
          accounts={accounts}
          flow={editing}
          locked={locked}
          save={save}
          cancel={() => setEditing(undefined)}
        />
      ) : null}
      <CoverageForm kind="cash" data={data} locked={locked} save={save} />
      <h4>Известные неденежные движения</h4>
      {data.movements.length === 0 ? (
        <p>Записей нет; проверьте источник отдельно от денежных операций.</p>
      ) : (
        <ul>
          {data.movements.map((m) => (
            <li key={m.id}>
              {m.event_date} · {evidenceLabel(m.movement_kind)} · количество:{" "}
              {m.quantity ?? "не задано"} · со счёта {m.source_account_id ?? "—"} на{" "}
              {m.destination_account_id ?? "—"}
            </li>
          ))}
        </ul>
      )}
      <CoverageForm kind="in-kind" data={data} locked={locked} save={save} />
      <h4>Привязка денежных остатков</h4>
      {data.cash_balances.map((c) => (
        <div key={c.id} className={styles.compositionBlock}>
          <p>
            {c.name} · отчёт {c.reporting_month_id} · {c.amount.amount} {c.amount.currency} ·{" "}
            {c.account_id === null ? "счёт не подтверждён" : `счёт ${c.account_id}`}
          </p>
          {c.account_id === null ? (
            <button
              type="button"
              className={styles.inlineButton}
              disabled={
                locked || data.months.find((m) => m.id === c.reporting_month_id)?.status !== "draft"
              }
              onClick={() =>
                void save(`/api/cash-balances/${c.id}`, "PATCH", { account_id: data.account_id })
              }
            >
              Подтверждаю: этот остаток относится к выбранному счёту
            </button>
          ) : null}
        </div>
      ))}
      <p>
        Наблюдения стоимости до и после операции вводятся в разделе{" "}
        <a href="#performance-capture">«Наблюдения PRE/POST»</a>. Здесь они не рассчитываются из
        потоков или месячных итогов.
      </p>
    </>
  );
}

function AccountPreparation({
  accountId,
  accounts,
  context,
}: {
  accountId: number;
  accounts: Account[];
  context: PerformanceContext;
}) {
  const client = useQueryClient();
  const busy = useRef(false);
  const [locked, setLocked] = useState(false);
  const [notice, setNotice] = useState("");
  const query = useQuery({
    queryKey: ["performance-preparation", accountId, context.start, context.end],
    queryFn: ({ signal }) => getPreparation(accountId, context.start, context.end, signal),
    retry: false,
  });
  const data = query.data;
  const fresh =
    data?.account_id === accountId &&
    data.start_date === context.start &&
    data.end_date === context.end;
  const save: Save = async (path, method, body) => {
    if (busy.current || locked || !data || !fresh || query.isFetching || query.isError) return;
    busy.current = true;
    setLocked(true);
    setNotice("Сохраняем и перечитываем данные…");
    let writeAcknowledged = false;
    try {
      const saved = (await savePreparation(path, method, body, data.evidence_token)) as {
        id: number;
      };
      writeAcknowledged = true;
      // Readiness includes both canonical final solvers. Invalidate all consumers,
      // including inactive summaries and legacy metric queries after any write.
      await client.invalidateQueries();
      const result = await query.refetch();
      const reread = result.data;
      if (
        result.isError ||
        !reread ||
        reread.account_id !== accountId ||
        reread.start_date !== context.start ||
        reread.end_date !== context.end
      )
        throw new Error("readback");
      const flowWrite = path.startsWith("/api/external-flows");
      const destinationId = flowWrite ? (body as { account_id: number }).account_id : accountId;
      let destination = reread;
      if (destinationId !== accountId) {
        destination = await client.fetchQuery({
          queryKey: ["performance-preparation", destinationId, context.start, context.end],
          queryFn: ({ signal }) =>
            getPreparation(destinationId, context.start, context.end, signal),
          staleTime: 0,
          retry: false,
        });
        // A moved flow must leave the original ledger and appear in the selected
        // destination at the same evidence version; never confirm a partial read.
        if (
          destination.account_id !== destinationId ||
          destination.start_date !== context.start ||
          destination.end_date !== context.end ||
          destination.evidence_token !== reread.evidence_token ||
          reread.flows.some((r) => r.id === saved.id)
        )
          throw new Error("readback");
      }
      const collection = flowWrite
        ? destination.flows
        : path.startsWith("/api/cash-boundary-coverages")
          ? reread?.cash_coverages
          : path.startsWith("/api/in-kind-boundary-coverages")
            ? reread?.in_kind_coverages
            : path.startsWith("/api/transfer-links")
              ? reread?.transfer_links
              : reread?.cash_balances;
      const row = collection?.find((r) => r.id === saved.id);
      if (
        !row ||
        (flowWrite && (row as ExternalFlow).account_id !== destinationId) ||
        Object.entries(body as Record<string, unknown>).some(([key, value]) => {
          const actual = (row as unknown as Record<string, unknown>)[key];
          // Compare authoritative response for canonical amount formatting and fields
          // absent from the compact coverage DTO; never declare a mismatched row saved.
          return (
            actual !== undefined &&
            JSON.stringify(actual) !==
              JSON.stringify((saved as unknown as Record<string, unknown>)[key] ?? value)
          );
        })
      )
        throw new Error("readback");
      const readiness = await client.fetchQuery({
        queryKey: queryKeys.performanceReadiness(
          context.start,
          context.end,
          context.scope,
          context.accountId,
        ),
        queryFn: ({ signal }) =>
          getPerformanceReadiness(
            context.start,
            context.end,
            context.scope,
            context.accountId,
            signal,
          ),
        staleTime: 0,
      });
      if (!isReadinessFresh(readiness, context)) throw new Error("readback");
      setNotice(
        "Запись подтверждена. Данные перечитаны; проверьте готовность XIRR/TWRR выше. Сохранение не означает доступность расчёта.",
      );
      setLocked(false);
    } catch (error) {
      await client.invalidateQueries();
      setNotice(
        writeAcknowledged
          ? "Сервер принял запись, но повторная проверка не завершилась. Перечитайте данные и проверьте результат перед следующим действием."
          : error instanceof ApiClientError && error.status === 409
            ? "Данные изменились или месяц закрыт. Форма устарела: перечитайте и проверьте её заново."
            : error instanceof ApiClientError && error.status >= 400 && error.status < 500
              ? `Запись отклонена: ${error.message}. Перечитайте данные и исправьте причину; автоматического изменения связей или свидетельств сверки нет.`
              : "Результат записи или повторного чтения не подтверждён. Не повторяйте запись вслепую: перечитайте данные и проверьте наличие изменений.",
      );
    } finally {
      busy.current = false;
    }
  };
  return (
    <>
      {notice ? <p role="status">{notice}</p> : null}
      <button
        type="button"
        className={styles.inlineButton}
        disabled={busy.current || query.isFetching}
        onClick={() =>
          void query.refetch().then((r) => {
            if (!r.isError) {
              setLocked(false);
              setNotice(
                "Данные перечитаны. Сверьте результат предыдущей записи перед новым подтверждением.",
              );
            }
          })
        }
      >
        Перечитать данные для ввода
      </button>
      {query.isError ? (
        <p role="alert">Не удалось прочитать данные. Запись недоступна.</p>
      ) : query.isFetching ? (
        <p>Читаем данные…</p>
      ) : fresh && data ? (
        <PreparationForms
          key={data.evidence_token}
          data={data}
          accounts={accounts}
          locked={locked}
          save={save}
        />
      ) : (
        <p role="alert">Ответ не соответствует выбранному счёту и интервалу.</p>
      )}
    </>
  );
}

export function PerformancePreparation({
  accounts,
  context,
}: {
  accounts: Account[] | undefined;
  context: PerformanceContext;
}) {
  const [params, setParams] = useSearchParams();
  const raw =
    params.get("prepare_account") ??
    (context.accountId === null ? null : String(context.accountId));
  const selected =
    raw && /^[1-9]\d*$/.test(raw) && params.getAll("prepare_account").length <= 1
      ? Number(raw)
      : null;
  const account = accounts?.find((a) => a.id === selected);
  return (
    <section
      id="performance-preparation"
      aria-label="Подготовка данных"
      className={`${styles.composition} ${styles.preparation}`}
    >
      <h3>Подготовка данных</h3>
      {params.get("prepare_reason") ? (
        <p>Проверяем: {diagnosticCopy(params.get("prepare_reason") ?? "unknown_reason").title}</p>
      ) : null}
      <p>
        Сверьте операции и отдельно подтвердите полноту каждого вида истории. Интервал:{" "}
        {context.start} — {context.end}.
      </p>
      <label>
        Счёт для проверки
        <select
          aria-label="Счёт для проверки"
          value={selected ?? ""}
          onChange={(e) => {
            const next = new URLSearchParams(params);
            if (e.target.value) next.set("prepare_account", e.target.value);
            else next.delete("prepare_account");
            void setParams(next);
          }}
        >
          <option value="">Выберите счёт</option>
          {accounts
            ?.filter((a) => context.scope === "portfolio" || a.id === context.accountId)
            .map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
        </select>
      </label>
      {raw && (!account || (context.scope === "account" && selected !== context.accountId)) ? (
        <p role="alert">Счёт подготовки не соответствует контексту. Выберите его явно.</p>
      ) : account ? (
        <>
          <HistoricalMembership
            key={`membership:${account.id}:${context.start}:${context.end}:${context.scope}`}
            accountId={account.id}
            context={context}
          />
          <AccountPreparation
            key={`${account.id}:${context.start}:${context.end}`}
            accountId={account.id}
            accounts={accounts ?? []}
            context={context}
          />
        </>
      ) : null}
      <p>
        <Link to={performanceDetailHref(context)}>
          Вернуться к доходности с тем же периодом и охватом
        </Link>
      </p>
    </section>
  );
}
