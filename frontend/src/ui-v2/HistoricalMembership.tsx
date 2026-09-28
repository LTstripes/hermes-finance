import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiClientError, apiRequest } from "../api/client";
import type { PerformanceReadiness } from "../api/types";
import { isReadinessFresh } from "./CapitalPerformanceSummary";
import type { PerformanceContext } from "./capitalPerformanceContext";
import styles from "./UiV2CapitalPerformance.module.css";

type Interval = { effective_from: string; effective_to: string; include_in_returns: boolean };
type Row = Omit<Interval, "effective_to"> & { id: number; effective_to: string | null };
type History = {
  account_id: number;
  start_date: string;
  end_date: string;
  scope: string;
  rows: Row[];
  identity: string;
  form_token: string;
  readiness: PerformanceReadiness;
};
type Draft = { key: number; effective_from: string; effective_to: string; inclusion: string };

function label(row: Omit<Row, "id">) {
  return `${row.effective_from} — ${row.effective_to ?? "без конечной даты"}: ${row.include_in_returns ? "участвует" : "исключён"}`;
}

function Editor({
  data,
  locked,
  save,
}: {
  data: History;
  locked: boolean;
  save: (ids: number[], replacements: Interval[]) => Promise<void>;
}) {
  const [ids, setIds] = useState<number[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const nextKey = useRef(0);
  const [attested, setAttested] = useState(false);
  const replacements = drafts.map((d) => ({
    effective_from: d.effective_from,
    effective_to: d.effective_to,
    include_in_returns: d.inclusion === "included",
  }));
  const remaining = data.rows.filter((r) => !ids.includes(r.id));
  const displayed = replacements.map((r, i) => ({
    ...r,
    draftKey: drafts[i].key,
    pending: drafts[i].inclusion === "",
  }));
  const after = [...remaining, ...displayed];
  const sorted = [...after].sort((a, b) => a.effective_from.localeCompare(b.effective_from));
  const overlap = sorted.some(
    (r, i) =>
      i > 0 &&
      (sorted[i - 1].effective_to === null ||
        (sorted[i - 1].effective_to ?? "") >= r.effective_from),
  );
  const valid =
    (ids.length > 0 || drafts.length > 0) &&
    !overlap &&
    drafts.every(
      (d) =>
        d.effective_from &&
        d.effective_to &&
        d.effective_from <= d.effective_to &&
        ["included", "excluded"].includes(d.inclusion),
    );
  const affected = [...data.rows.filter((r) => ids.includes(r.id)), ...displayed];
  return (
    <fieldset disabled={locked} className={styles.compositionBlock}>
      <legend>Историческое участие счёта</legend>
      <p>
        Текущий флажок счёта не подтверждает прошлое. Пробелы остаются неизвестными. Выберите все
        записи для замены или отзыва; затем явно задайте новые интервалы.
      </p>
      <h4>Полная история до изменения</h4>
      {data.rows.length === 0 ? (
        <p>История отсутствует.</p>
      ) : (
        data.rows.map((row) => (
          <label key={row.id}>
            <input
              type="checkbox"
              disabled={row.effective_to === null}
              checked={ids.includes(row.id)}
              onChange={(e) => {
                setIds(e.target.checked ? [...ids, row.id] : ids.filter((i) => i !== row.id));
                setAttested(false);
              }}
            />
            Запись {row.id}: {label(row)}
            {row.effective_to === null
              ? "; только чтение, пересекающиеся изменения заблокированы"
              : ""}
          </label>
        ))
      )}
      <h4>Новые явные интервалы</h4>
      {drafts.map((draft, index) => (
        <fieldset key={draft.key}>
          <legend>Интервал {index + 1}</legend>
          <label>
            Начало{" "}
            <input
              type="date"
              value={draft.effective_from}
              onChange={(e) => {
                setDrafts(
                  drafts.map((d, i) =>
                    i === index ? { ...d, effective_from: e.target.value } : d,
                  ),
                );
                setAttested(false);
              }}
            />
          </label>
          <label>
            Конец включительно{" "}
            <input
              type="date"
              value={draft.effective_to}
              onChange={(e) => {
                setDrafts(
                  drafts.map((d, i) => (i === index ? { ...d, effective_to: e.target.value } : d)),
                );
                setAttested(false);
              }}
            />
          </label>
          <label>
            Участие{" "}
            <select
              value={draft.inclusion}
              onChange={(e) => {
                setDrafts(
                  drafts.map((d, i) => (i === index ? { ...d, inclusion: e.target.value } : d)),
                );
                setAttested(false);
              }}
            >
              <option value="">Выберите явно</option>
              <option value="included">Участвует</option>
              <option value="excluded">Исключён</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => {
              setDrafts(drafts.filter((_, i) => i !== index));
              setAttested(false);
            }}
          >
            Убрать интервал {index + 1}
          </button>
        </fieldset>
      ))}
      <button
        type="button"
        onClick={() => {
          setDrafts([
            ...drafts,
            { key: nextKey.current++, effective_from: "", effective_to: "", inclusion: "" },
          ]);
          setAttested(false);
        }}
      >
        Добавить явный интервал
      </button>
      <h4>Полная история после изменения</h4>
      {after.length === 0 ? (
        <p>История будет неизвестной.</p>
      ) : (
        after.map((row) => (
          <p key={"id" in row ? `row-${row.id}` : `draft-${row.draftKey}`}>
            {"id" in row ? `Запись ${row.id}: ` : "Новая запись: "}
            {"pending" in row && row.pending
              ? `${row.effective_from || "начало не выбрано"} — ${row.effective_to || "конец не выбран"}: участие не выбрано`
              : label(row)}
          </p>
        ))
      )}
      <h4>Затронутые старые и новые интервалы</h4>
      {affected.map((r) => (
        <p key={"id" in r ? `row-${r.id}` : `draft-${r.draftKey}`}>
          {r.effective_from} — {r.effective_to}
        </p>
      ))}
      {overlap ? (
        <p role="alert">
          Пересечения недопустимы, даже при одинаковом участии. Выберите весь неоднозначный набор
          для исправления.
        </p>
      ) : null}
      <p>
        Подтверждения денежной и неденежной истории в затронутых интервалах будут отозваны;
        зависимые оценки до/после потоков потребуют нового подтверждения. Закрытые отчёты нужно явно
        открыть, затем после исправления закрыть заново.
      </p>
      <label>
        <input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} />
        Я проверил(а) источники, полный набор до/после и все затронутые интервалы; подтверждаю
        изменение истории
      </label>
      <button
        type="button"
        disabled={!valid || !attested}
        onClick={() => void save(ids, replacements)}
      >
        Подтвердить изменение участия
      </button>
    </fieldset>
  );
}

export function HistoricalMembership({
  accountId,
  context,
}: {
  accountId: number;
  context: PerformanceContext;
}) {
  const client = useQueryClient();
  const busy = useRef(false);
  const [locked, setLocked] = useState(false);
  const [notice, setNotice] = useState("");
  const params = new URLSearchParams({
    account_id: String(accountId),
    start_date: context.start,
    end_date: context.end,
    scope: context.scope,
  });
  const read = () => apiRequest<History>(`/api/performance/membership?${params}`);
  const fresh = (h: History) =>
    h.account_id === accountId &&
    h.start_date === context.start &&
    h.end_date === context.end &&
    h.scope === context.scope &&
    isReadinessFresh(h.readiness, context);
  const query = useQuery({
    queryKey: ["historical-membership", accountId, context.start, context.end, context.scope],
    queryFn: read,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const save = async (ids: number[], replacements: Interval[]) => {
    const before = query.data;
    if (busy.current || locked || query.isFetching || query.isError || !before || !fresh(before))
      return;
    busy.current = true;
    setLocked(true);
    setNotice("Сохраняем и проверяем историю и расчёты…");
    try {
      const saved = await apiRequest<History>("/api/performance/membership", {
        method: "POST",
        body: {
          account_id: accountId,
          start_date: context.start,
          end_date: context.end,
          scope: context.scope,
          form_token: before.form_token,
          replaced_ids: ids,
          replacements,
          attested: true,
        },
      });
      await client.invalidateQueries();
      const result = await query.refetch();
      const reread = result.data;
      if (result.isError || !reread) throw new Error("readback");
      const expected = [...before.rows.filter((r) => !ids.includes(r.id)), ...replacements];
      const material = (rows: Omit<Row, "id">[]) => rows.map(label).sort();
      if (
        !fresh(saved) ||
        !fresh(reread) ||
        reread.identity !== saved.identity ||
        JSON.stringify(saved.rows) !== JSON.stringify(reread.rows) ||
        JSON.stringify(material(expected)) !== JSON.stringify(material(reread.rows)) ||
        before.rows.some(
          (r) =>
            !ids.includes(r.id) && !reread.rows.some((n) => n.id === r.id && label(n) === label(r)),
        )
      ) {
        throw new Error("readback");
      }
      setNotice(
        "История подтверждена. Готовность и итоговые XIRR/TWRR перечитаны. Сохранение не означает доступность расчёта.",
      );
      setLocked(false);
    } catch (error) {
      await client.invalidateQueries();
      setNotice(
        `${error instanceof ApiClientError && error.status === 409 ? `Запись отклонена: ${error.message}. ` : ""}Изменение не подтверждено: форма устарела, запись отклонена или результат неизвестен. Не повторяйте её вслепую. Перечитайте и проверьте историю перед новым подтверждением.`,
      );
    } finally {
      busy.current = false;
    }
  };
  return (
    <section aria-label="Историческое участие">
      {notice ? <p role="status">{notice}</p> : null}
      <button
        type="button"
        disabled={busy.current || query.isFetching}
        onClick={() =>
          void query.refetch().then((r) => {
            if (!r.isError && r.data && fresh(r.data)) {
              setLocked(false);
              setNotice(
                "История перечитана. Проверьте результат предыдущей записи и подтвердите новый набор явно.",
              );
            }
          })
        }
      >
        Перечитать историю участия
      </button>
      {query.isError ? (
        <p role="alert">История или расчёты не прочитаны. Запись недоступна.</p>
      ) : query.data && fresh(query.data) ? (
        <Editor
          key={query.data.form_token}
          data={query.data}
          locked={locked || query.isFetching}
          save={save}
        />
      ) : (
        <p>Читаем историю и расчёты…</p>
      )}
    </section>
  );
}
