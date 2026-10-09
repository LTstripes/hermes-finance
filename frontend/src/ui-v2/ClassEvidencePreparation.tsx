import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { listAccounts } from "../api/accounts";
import {
  type ClassCoverage,
  type ClassCoverageWrite,
  listClassCoverages,
  saveClassCoverage,
} from "../api/classEvidence";
import { ApiClientError } from "../api/client";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import { getClassReturns } from "../api/performance";
import { listPositions, updatePosition } from "../api/positions";
import type { HistoricalInstrumentType, PositionSnapshot, ReportingMonth } from "../api/types";
import { classReasonCopy, isClassReturnsFresh } from "./classReturnsCopy";
import styles from "./UiV2CapitalPerformance.module.css";
import { isQueryReady } from "./UiV2StateBlocks";

type AssetClass = ClassCoverage["asset_class"];
type Save = (write: () => Promise<unknown>) => void;
const labels: Record<HistoricalInstrumentType, string> = {
  stock: "Акции",
  bond: "Облигации",
  gold: "Золото",
  fund: "Фонд",
  currency: "Валюта",
};

// Only these accepted reasons have an evidence control on this surface.
const ownerReasons = new Set([
  "historical_class_unknown",
  "no_crossing_coverage_missing_or_ambiguous",
  "no_crossing_coverage_not_complete",
  "no_crossing_material_changed",
  "opening_class_inventory_not_complete",
  "closing_class_inventory_not_complete",
]);

// ReportingMonth periods are calendar months; snapshot dates may lie outside them.
function intersects(month: ReportingMonth, start: string, end: string) {
  const prefix = `${month.year}-${String(month.month).padStart(2, "0")}`;
  const last = new Date(Date.UTC(month.year, month.month, 0)).getUTCDate();
  return (
    (`${prefix}-01` <= end && `${prefix}-${last}` >= start) ||
    (month.snapshot_date >= start && month.snapshot_date <= end)
  );
}

function IdentityForm({
  row,
  closed,
  locked,
  save,
  description,
}: {
  row: PositionSnapshot;
  closed: boolean;
  locked: boolean;
  save: Save;
  description: string;
}) {
  const [identity, setIdentity] = useState(row.historical_instrument_type ?? "");
  const [attested, setAttested] = useState(false);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (closed || locked || !attested || identity === (row.historical_instrument_type ?? ""))
          return;
        save(() =>
          updatePosition(
            row.id,
            {
              historical_instrument_type:
                identity === "" ? null : (identity as HistoricalInstrumentType),
            },
            row.updated_at,
          ),
        );
      }}
    >
      <fieldset disabled={closed} className={styles.compositionBlock}>
        <legend>
          Позиция {row.id} · {description}
        </legend>
        <p>
          C1:{" "}
          {row.historical_instrument_type
            ? labels[row.historical_instrument_type]
            : "Не подтверждён / неизвестно"}
          . Месяц {row.reporting_month_id}.
        </p>
        <label>
          Исторический класс позиции {row.id}
          <select
            value={identity}
            onChange={(e) => {
              setIdentity(e.target.value);
              setAttested(false);
            }}
          >
            <option value="">Неизвестно / отозвать C1</option>
            {Object.entries(labels).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.attestation}>
          <input
            type="checkbox"
            checked={attested}
            onChange={(e) => setAttested(e.target.checked)}
          />
          Я сверил(а) исторический класс позиции {row.id} с источником
        </label>
        <button
          className={styles.inlineButton}
          type="submit"
          disabled={locked || !attested || identity === (row.historical_instrument_type ?? "")}
        >
          Сохранить C1 позиции {row.id}
        </button>
      </fieldset>
      {closed ? (
        <p>CLOSED — только чтение. Исправление C1 требует отдельного решения о Reopen.</p>
      ) : null}
    </form>
  );
}

function CoverageForm({
  assetClass,
  start,
  end,
  row,
  months,
  locked,
  save,
}: {
  assetClass: AssetClass;
  start: string;
  end: string;
  row?: ClassCoverage;
  months: ReportingMonth[];
  locked: boolean;
  save: Save;
}) {
  const [from, setFrom] = useState(row?.covered_from ?? start);
  const [to, setTo] = useState(row?.covered_to ?? end);
  const [state, setState] = useState<ClassCoverage["coverage_state"]>(
    row?.coverage_state ?? "unknown",
  );
  // Fresh explicit claims are required for every replacement, including reaffirmation.
  const [noCrossing, setNoCrossing] = useState(false);
  const [opening, setOpening] = useState(false);
  const [closing, setClosing] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const closed = months.some(
    (m) =>
      m.status === "closed" &&
      (intersects(m, from, to) || (row && intersects(m, row.covered_from, row.covered_to))),
  );
  const valid =
    /^\d{4}-\d{2}-\d{2}$/.test(from) &&
    /^\d{4}-\d{2}-\d{2}$/.test(to) &&
    from < to &&
    confirmed &&
    (state !== "complete" || noCrossing);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (locked || closed || !valid) return;
        const body: ClassCoverageWrite = {
          asset_class: assetClass,
          covered_from: from,
          covered_to: to,
          coverage_state: state,
          provenance_kind: "owner_attestation",
          provenance_reference: row?.provenance_reference ?? null,
          opening_inventory_complete: opening,
          closing_inventory_complete: closing,
        };
        save(() => saveClassCoverage(body, row));
      }}
    >
      <fieldset disabled={closed} className={styles.compositionBlock}>
        <legend>
          {row
            ? `Исправление / отзыв подтверждения ${row.id} · версия ${row.revision}`
            : "Новое подтверждение класса"}
        </legend>
        <div className={styles.controls} onChange={() => setConfirmed(false)}>
          <label>
            Начало подтверждения
            <input
              type="date"
              required
              value={from}
              onChange={(e) => {
                setFrom(e.target.value);
                setNoCrossing(false);
                setOpening(false);
                setClosing(false);
              }}
            />
          </label>
          <label>
            Конец подтверждения
            <input
              type="date"
              required
              value={to}
              onChange={(e) => {
                setTo(e.target.value);
                setNoCrossing(false);
                setOpening(false);
                setClosing(false);
              }}
            />
          </label>
          <label className={styles.controlsFull}>
            Состояние подтверждения
            <select
              value={state}
              onChange={(e) => {
                setState(e.target.value as ClassCoverage["coverage_state"]);
                setNoCrossing(false);
                setOpening(false);
                setClosing(false);
              }}
            >
              <option value="unknown">Не проверено</option>
              <option value="complete">Подтверждено</option>
              <option value="revoked">Отозвано</option>
            </select>
          </label>
        </div>
        <h4>Отсутствие пересечений за весь интервал</h4>
        <label className={styles.attestation}>
          <input
            type="checkbox"
            disabled={state !== "complete"}
            checked={noCrossing}
            onChange={(e) => {
              setNoCrossing(e.target.checked);
              setConfirmed(false);
            }}
          />
          Я проверил(а): пересечений границы класса за весь интервал не было
        </label>
        <h4>Независимые подтверждения состава на границах</h4>
        <p>
          Начало и конец подтверждаются отдельно. Их можно сохранить при состоянии «Не проверено»
          или «Отозвано»: это не подтверждает отсутствие пересечений и не делает доходность
          доступной.
        </p>
        <label className={styles.attestation}>
          <input
            type="checkbox"
            checked={opening}
            onChange={(e) => {
              setOpening(e.target.checked);
              setConfirmed(false);
            }}
          />
          Полный состав класса на начало {from} во всех исторически включённых счетах подтверждён
        </label>
        <label className={styles.attestation}>
          <input
            type="checkbox"
            checked={closing}
            onChange={(e) => {
              setClosing(e.target.checked);
              setConfirmed(false);
            }}
          />
          Полный состав класса на конец {to} во всех исторически включённых счетах подтверждён
        </label>
        <p>
          Проверка охватывает покупки, продажи, смену класса, выплаты дохода за границу класса,
          погашения, комиссии, налоги и внешние неденежные движения. Нулевой итог движений не
          означает их отсутствие. Пустой список и успешный импорт не доказывают полный состав.
        </p>
        <p>
          Текущие утверждения о составе: начало{" "}
          {row?.opening_inventory_complete ? "подтверждено" : "не подтверждено"}; конец{" "}
          {row?.closing_inventory_complete ? "подтверждено" : "не подтверждено"}. При сохранении они
          заменяются выбранными выше утверждениями.
        </p>
        <p aria-live="polite">
          Будет сохранено: интервал {from} — {to}; отсутствие пересечений —{" "}
          {state === "complete"
            ? "подтверждено"
            : state === "revoked"
              ? "отозвано"
              : "не проверено"}
          ; состав на начало — {opening ? "подтверждён" : "не подтверждён"}; состав на конец —{" "}
          {closing ? "подтверждён" : "не подтверждён"}. Доступность XIRR/TWRR определит
          перечитывание.
        </p>
        <label className={styles.attestation}>
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          Подтверждаю выбранное состояние и обе декларации состава
        </label>
        {closed ? (
          <p role="alert">
            CLOSED — только чтение: сохранение для затронутых закрытых месяцев заблокировано. Reopen
            требует отдельного решения об исправлении истории и не устраняет отсутствующие
            источники, ограничения расчёта или противоречия. Ссылки ниже открывают просмотр месяца.
          </p>
        ) : null}
        <ul>
          {months
            .filter(
              (m) =>
                intersects(m, from, to) || (row && intersects(m, row.covered_from, row.covered_to)),
            )
            .map((m) => (
              <li key={m.id}>
                <Link to={`/v2/data/months/${m.id}`}>
                  Месяц {m.year}-{String(m.month).padStart(2, "0")} · {m.status.toUpperCase()}
                </Link>
              </li>
            ))}
        </ul>
        <button type="submit" className={styles.inlineButton} disabled={locked || closed || !valid}>
          Сохранить подтверждение класса
        </button>
      </fieldset>
    </form>
  );
}

function Preparation({
  assetClass,
  start,
  end,
}: {
  assetClass: AssetClass;
  start: string;
  end: string;
}) {
  const client = useQueryClient();
  const busy = useRef(false);
  const [blocked, setBlocked] = useState(false);
  const [message, setMessage] = useState("");
  const notice = useRef<HTMLParagraphElement>(null);
  const focusNotice = useRef(false);
  const [readGeneration, setReadGeneration] = useState(0);
  useEffect(() => {
    if (message && !blocked && focusNotice.current) {
      notice.current?.focus({ preventScroll: true });
      focusNotice.current = false;
    }
  }, [message, blocked]);
  const [selected, setSelected] = useState("");
  const query = useQuery({
    queryKey: ["class-preparation", assetClass, start, end],
    refetchOnWindowFocus: true,
    queryFn: async ({ signal }) => {
      const [result, coverages, months, accounts, instruments] = await Promise.all([
        getClassReturns(assetClass, start, end, signal),
        listClassCoverages(signal),
        listMonths(signal),
        listAccounts(signal),
        listInstruments({}, signal),
      ]);
      if (!isClassReturnsFresh(result, assetClass, start, end))
        throw new Error("Ответ не соответствует классу, интервалу или валюте.");
      const observed = months.filter((m) => m.snapshot_date >= start && m.snapshot_date <= end);
      const positions = (
        await Promise.all(observed.map((m) => listPositions(m.id, undefined, signal)))
      ).flat();
      if (positions.some((p) => !observed.some((m) => m.id === p.reporting_month_id)))
        throw new Error("Ответ позиций не соответствует месяцам.");
      return {
        result,
        coverages: coverages.filter((c) => c.asset_class === assetClass),
        months,
        positions,
        accounts,
        instruments,
      };
    },
  });
  // Keep the last read mounted during a refetch/error, but never writable until settled.
  const data = query.data;
  // Bind drafts to evidence content, not fetch time. A benign focus read preserves DOM/focus.
  const evidence = JSON.stringify(data);
  const [snapshot, setSnapshot] = useState({ evidence, version: 0 });
  if (snapshot.evidence !== evidence) {
    setSnapshot({ evidence, version: snapshot.version + 1 });
  }
  const previousEvidence = useRef(evidence);
  useEffect(() => {
    if (previousEvidence.current && evidence !== previousEvidence.current && !busy.current) {
      setMessage(
        "Исходные данные изменились. Черновик сброшен; заново проверьте и выберите подтверждения.",
      );
    }
    previousEvidence.current = evidence;
  }, [evidence]);
  const targets = data?.coverages ?? [];
  const exact = targets.filter((c) => c.covered_from === start && c.covered_to === end);
  const chosenId = selected || (exact.length === 1 ? String(exact[0].id) : "new");
  const row = targets.find((c) => String(c.id) === chosenId);
  const locked = blocked || busy.current || !isQueryReady(query);
  const reread = async (resetDraft = blocked) => {
    if (busy.current) return;
    busy.current = true;
    setBlocked(true);
    try {
      await client.invalidateQueries({
        predicate: (q) =>
          [
            "class-returns",
            "months",
            "positions",
            "performance-readiness",
            "portfolio-xirr",
            "portfolio-twrr",
            "performance-attribution",
            "month-close-workflow",
          ].includes(String(q.queryKey[0])),
      });
      const fresh = await query.refetch();
      if (fresh.isError) throw fresh.error;
      previousEvidence.current = JSON.stringify(fresh.data);
      if (resetDraft) setReadGeneration((value) => value + 1);
      setBlocked(false);
      focusNotice.current = true;
      setMessage(
        resetDraft || JSON.stringify(fresh.data) !== evidence
          ? "Данные перечитаны. Черновик сброшен; проверьте актуальные строки и версии перед новым действием."
          : "Данные перечитаны. Черновик сохранён; проверьте актуальные строки и версии перед новым действием.",
      );
    } catch {
      setMessage("Не удалось перечитать данные. Запись заблокирована до успешного чтения.");
    } finally {
      busy.current = false;
    }
  };
  const save: Save = async (write) => {
    if (busy.current || blocked || !isQueryReady(query)) return;
    busy.current = true;
    setBlocked(true);
    try {
      await write();
      setMessage("Запись сохранена. Требуется авторитетное перечитывание.");
    } catch (error) {
      setMessage(
        error instanceof ApiClientError && [409, 412].includes(error.status)
          ? "Форма устарела: перечитайте ревизии. Запись не повторяется автоматически."
          : "Запись не подтверждена: проверьте данные перечитыванием. CLOSED блокирует исправления; противоречия нельзя устранить декларацией.",
      );
      busy.current = false;
      return;
    }
    busy.current = false;
    await reread(true);
  };
  return (
    <div className={styles.preparation}>
      <p>
        Весь исторический портфель · {labels[assetClass]} · {start} — {end}. Сначала проверьте
        ограничения ниже. Изменение исторического класса и Reopen обесценивают зависимые
        подтверждения. Выбор «Не проверено», галочки и импорт файлов не доказывают полноту и не
        открывают XIRR/TWRR.
      </p>
      <p>
        Депозиты, FX и истории с пересечениями границы класса здесь не поддерживаются. Декларация не
        заменяет отсутствующие операции и не снимает противоречия.
      </p>
      {message ? (
        <p role="status" tabIndex={-1} ref={notice}>
          {message}
        </p>
      ) : null}
      <button
        type="button"
        className={styles.inlineButton}
        disabled={query.isFetching}
        onClick={() => void reread()}
      >
        Перечитать подготовку класса
      </button>
      {query.isError ? (
        <p role="alert">Не удалось прочитать подготовку класса. {query.error.message}</p>
      ) : null}
      {!data && !query.isError ? <p role="status">Читаем подготовку…</p> : null}
      {data ? (
        <>
          <h4>
            Авторитетные ограничения: {labels[assetClass]} · {start} — {end}
          </h4>
          <p>
            Готовность по последнему успешному чтению; запись ниже не заменяет источники. Пока
            чтение идёт или завершилось ошибкой, сохранение заблокировано.
          </p>
          {[
            ["Можно подтвердить вручную после проверки источника", true],
            ["Требуется источник, отдельный процесс или поддержка расчёта", false],
          ].map(([title, owner]) => {
            const codes = [
              ...new Set([
                ...data.result.evidence_reason_codes,
                ...data.result.xirr.reason_codes,
                ...data.result.twrr.reason_codes,
              ]),
            ].filter((code) => ownerReasons.has(code) === owner);
            return codes.length ? (
              <div key={String(title)}>
                <h4>{title}</h4>
                <ul>
                  {codes.map((code) => (
                    <li key={code}>{classReasonCopy(code)}</li>
                  ))}
                </ul>
              </div>
            ) : null;
          })}
          <p>
            XIRR: {data.result.xirr.availability === "available" ? "доступен" : "недоступен"}; TWRR:{" "}
            {data.result.twrr.availability === "available" ? "доступен" : "недоступен"}. Итог
            определяется авторитетным ответом, а не состоянием формы.
          </p>
          <details>
            <summary>Технические причины недоступности</summary>
            <ul>
              {[
                ...new Set([
                  ...data.result.evidence_reason_codes,
                  ...data.result.xirr.reason_codes,
                  ...data.result.twrr.reason_codes,
                ]),
              ].map((code) => (
                <li key={code}>
                  <code>{code}</code>
                </li>
              ))}
            </ul>
          </details>
          <p>
            Исторически включённые счета:{" "}
            {data.result.historical_account_ids.join(", ") || "не подтверждены"}. Строки ниже
            показывают наблюдаемые позиции; они не доказывают полноту класса.
          </p>
          <h4>Месяцы и жизненный цикл</h4>
          <ul>
            {data.months
              .filter(
                (m) =>
                  intersects(m, start, end) ||
                  (row && intersects(m, row.covered_from, row.covered_to)),
              )
              .map((m) => (
                <li key={m.id}>
                  <Link to={`/v2/data/months/${m.id}`}>
                    Месяц {m.year}-{String(m.month).padStart(2, "0")} · снимок {m.snapshot_date} ·{" "}
                    {m.status === "closed"
                      ? "CLOSED — только чтение"
                      : "DRAFT — исправления доступны после проверки"}
                  </Link>
                </li>
              ))}
          </ul>
          <details>
            <summary>Исторический класс C1: все наблюдаемые строки интервала</summary>
            {data.positions.map((p) => (
              <IdentityForm
                key={`${p.id}:${snapshot.version}:${readGeneration}`}
                row={p}
                description={`${data.accounts.find((a) => a.id === p.account_id)?.name ?? `Счёт ${p.account_id}`} · ${data.instruments.find((i) => i.id === p.instrument_id)?.name ?? `Инструмент ${p.instrument_id}`} · ${data.months.find((m) => m.id === p.reporting_month_id)?.snapshot_date ?? "дата неизвестна"}`}
                closed={data.months.find((m) => m.id === p.reporting_month_id)?.status !== "draft"}
                locked={locked}
                save={save}
              />
            ))}
            {data.positions.length === 0 ? (
              <p>Наблюдаемых позиций нет; это не подтверждение нулевого состава.</p>
            ) : null}
          </details>
          <label>
            Запись подтверждения
            <select
              value={chosenId}
              disabled={blocked || query.isPending || query.isError}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="new">Создать для выбранного интервала</option>
              {targets.map((c) => (
                <option value={c.id} key={c.id}>
                  Запись {c.id} · {c.covered_from} — {c.covered_to} · {c.coverage_state} · версия{" "}
                  {c.revision}
                </option>
              ))}
            </select>
          </label>
          <CoverageForm
            key={`${chosenId}:${snapshot.version}:${readGeneration}`}
            assetClass={assetClass}
            start={start}
            end={end}
            row={row}
            months={data.months}
            locked={locked}
            save={save}
          />
        </>
      ) : null}
    </div>
  );
}

export function ClassEvidencePreparation({ start, end }: { start: string; end: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  // Existing history entry only: browser Back retains context without new query semantics.
  const context = location.state?.classPreparation;
  const samePeriod = context?.start === start && context?.end === end;
  const assetClass: AssetClass =
    samePeriod && ["stock", "bond", "gold"].includes(context.assetClass)
      ? context.assetClass
      : "stock";
  const open = samePeriod && context.open === true;
  const remember = (assetClass: AssetClass, open: boolean) =>
    navigate(location, {
      replace: true,
      preventScrollReset: true,
      state: { ...location.state, classPreparation: { assetClass, open, start, end } },
    });
  return (
    <details
      className={styles.compositionBlock}
      open={open}
      onToggle={(e) => {
        if (e.currentTarget.open !== open) remember(assetClass, e.currentTarget.open);
      }}
    >
      <summary>Подготовить подтверждения классов</summary>
      <label>
        Класс для подготовки
        <select value={assetClass} onChange={(e) => remember(e.target.value as AssetClass, open)}>
          {(["stock", "bond", "gold"] as const).map((key) => (
            <option value={key} key={key}>
              {labels[key]}
            </option>
          ))}
        </select>
      </label>
      {open ? (
        <Preparation
          key={`${assetClass}:${start}:${end}`}
          assetClass={assetClass}
          start={start}
          end={end}
        />
      ) : null}
    </details>
  );
}
