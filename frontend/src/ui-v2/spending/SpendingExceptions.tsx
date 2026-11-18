import { useId, useState, type ReactNode } from "react";
import type {
  PreviewRow,
  Resolution,
  SpendingCategory,
  SpendingException,
} from "../../api/spending";
import { Badge, Button, ConfirmDialog, HelpTip } from "../../components/ui";
import { normalizeMoneyInput } from "../../lib/money";
import sheet from "../ReportSheet.module.css";
import { spendingMonthForm } from "../uiV2Copy";
import { Money, shortDate } from "./common";
import styles from "./Spending.module.css";

const groups = [
  ["transfer", "Переводы", "Перевод — не трата, пока вы не решите иначе."],
  [
    "possible_duplicate",
    "Может быть, это одна трата",
    "Сумма совпала с операцией в выписке. Одинаковая сумма ещё не значит, что это та же покупка.",
  ],
  ["refund", "Возвраты и входящие деньги"],
  ["entry_link", "Записи из отчёта месяца"],
  ["foreign_currency", "Не в рублях"],
  ["unknown_debit", "Незнакомые списания"],
  ["new_category", "Новые категории"],
  ["uncategorized", "Без категории"],
] as const;

const labels: Record<Resolution["action"], string> = {
  expense: "Трата…",
  refund: "Возврат…",
  not_spending: "Не трата",
  separate: "Отдельная трата",
  duplicate: "Та же трата",
  link: "Это она",
  unlink: "Отменить связь",
  acknowledge: "Подтвердить",
};
type Action = Resolution["action"];
export type ResolvedException = { item: SpendingException; decision: Resolution };

export function needsDecision(item: SpendingException) {
  return item.group !== "foreign_currency" && item.group !== "uncategorized";
}
function actionsFor(item: SpendingException, saved: boolean): Action[] {
  if (item.group === "foreign_currency") return [];
  if (item.review_id) return saved ? ["acknowledge"] : [];
  if (item.link_id) return saved ? ["unlink"] : [];
  switch (item.group) {
    case "transfer":
      return ["not_spending", "expense"];
    case "possible_duplicate":
      return ["duplicate", "separate"];
    case "refund":
      return ["refund", "not_spending"];
    case "entry_link":
      return item.candidates.length ? ["link", "separate"] : ["separate"];
    case "uncategorized":
    case "new_category":
      return ["expense"];
    default:
      return item.kind_hint === "cash_withdrawal" ? ["not_spending"] : ["expense", "not_spending"];
  }
}
export function PreviewRowText({ row }: { row: PreviewRow }) {
  const amount = Number.isSafeInteger(row.amount_kopecks)
    ? normalizeMoneyInput(
        `${row.amount_kopecks < 0 ? "-" : ""}${String(Math.abs(row.amount_kopecks))
          .padStart(3, "0")
          .replace(/(\d{2})$/, ".$1")}`,
      )
    : null;
  return (
    <>
      {shortDate(row.operation_date)} · {row.description}
      {row.category ? ` · ${row.category}` : ""} ·{" "}
      <Money
        value={
          amount === null
            ? null
            : { amount, currency: row.currency === "RUR" ? "RUB" : row.currency }
        }
      />
    </>
  );
}

function CategoryPicker({
  categories,
  category,
  setCategory,
  disabled,
}: {
  categories: SpendingCategory[];
  category: string;
  setCategory: (name: string) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const id = useId();
  return (
    <>
      <label className={sheet.select}>
        Категория{" "}
        <select
          disabled={disabled}
          value={category}
          onChange={(event) => {
            if (event.target.value === id) {
              setName("");
              setOpen(true);
            } else setCategory(event.target.value);
          }}
        >
          <option value="">Выберите категорию</option>
          {category && !categories.some((item) => item.name === category) && (
            <option>{category}</option>
          )}
          {categories.map((item) => (
            <option key={item.id}>{item.name}</option>
          ))}
          <option value={id}>Новая категория…</option>
        </select>
      </label>
      <ConfirmDialog
        open={open}
        title="Новая категория…"
        description="Введите имя категории."
        confirmLabel="Создать категорию"
        confirmDisabled={!name.trim()}
        onCancel={() => setOpen(false)}
        onConfirm={() => {
          setCategory(name.trim());
          setOpen(false);
        }}
      >
        <label>
          Категория{" "}
          <input maxLength={128} value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <p className={sheet.muted}>Тип: Прочие</p>
      </ConfirmDialog>
    </>
  );
}
function consequence(item: SpendingException) {
  switch (item.group) {
    case "possible_duplicate":
      return "Пока ручная строка не входит в траты";
    case "refund":
      return "Пока не учитывается";
    case "entry_link":
      return "Пока входит в итог — может быть посчитана дважды";
    case "new_category":
      return item.counted_now ? "Пока входит в итог" : "Пока не входит в траты";
    case "foreign_currency":
      return "Не входит в траты: суммы в другой валюте не складываются с рублями. Если это трата, запишите её в ручной файл в рублях.";
    default:
      return item.counted_now ? "Пока входит в итог" : "Пока не входит в траты";
  }
}

function ExceptionRow({
  item,
  resolved,
  categories,
  saved,
  month,
  disabled,
  onResolve,
}: {
  item: SpendingException;
  resolved?: Resolution;
  categories: SpendingCategory[];
  saved: boolean;
  month: string;
  disabled: boolean;
  onResolve: (item: SpendingException, decision: Resolution) => void;
}) {
  const [editing, setEditing] = useState(!resolved);
  const [action, setAction] = useState<Action | null>(null);
  const [category, setCategory] = useState("");
  const [candidate, setCandidate] = useState<number | undefined>();
  const [remember, setRemember] = useState(item.remember_default);
  const id = useId();
  const actions = actionsFor(item, saved);
  const directCategory = item.group === "uncategorized";
  const newCategory = item.group === "new_category";
  const needsCategory = action === "expense" || action === "refund";
  const needsCandidate = action === "duplicate" || action === "link";
  const selectedCandidate =
    candidate ?? (item.candidates.length === 1 ? item.candidates[0].id : undefined);
  const remembersKey = item.remember_key && (action === "not_spending" || needsCategory);
  const canRemember =
    remembersKey && (directCategory || Boolean(category && category !== item.bank_category));
  const previous =
    item.previous_decision ??
    (item.previous_decisions?.length === 1 ? item.previous_decisions[0] : undefined);
  const previousAction = previous?.action ?? previous?.decision;
  const decisionCategory = directCategory ? "expense" : action;
  if (!editing && resolved)
    return (
      <div className={styles.exception}>
        <div className={styles.actions}>
          <span>
            ✓ {labels[resolved.action]}
            {resolved.category ? ` · ${resolved.category}` : ""}
            {resolved.remember && item.remember_key
              ? ` · запомнится для „${item.remember_key}“`
              : ""}
          </span>
          {!saved && (
            <Button
              variant="ghost"
              disabled={disabled}
              onClick={() => {
                setAction(null);
                setEditing(true);
              }}
            >
              Изменить
            </Button>
          )}
        </div>
      </div>
    );

  function submit(chosen: Action | null = decisionCategory) {
    if (!chosen) return;
    onResolve(item, {
      id: item.id,
      action: chosen,
      ...(chosen === "expense" || chosen === "refund" ? { category } : {}),
      ...(chosen === "duplicate" ? { duplicate_of_id: selectedCandidate } : {}),
      ...(chosen === "link" && selectedCandidate !== undefined
        ? { operation_ids: [selectedCandidate] }
        : {}),
      remember:
        chosen === "link"
          ? item.recurring
          : chosen === "not_spending"
            ? Boolean(item.remember_key)
            : (chosen === "expense" || chosen === "refund") && Boolean(canRemember && remember),
    });
    setEditing(false);
  }

  return (
    <div className={styles.exception}>
      <div>
        {item.group === "entry_link" ? (
          <>
            Запись месяца: {item.category ?? previous?.description} · <Money value={item.amount} />
            {item.recurring ? " · повторяющаяся" : ""}
          </>
        ) : newCategory && item.category ? (
          <>
            „{item.category}“ · <Money value={item.amount} />
          </>
        ) : (
          <>
            {item.group === "possible_duplicate" && "Ручной файл: "}
            {shortDate(item.date)} · {item.group === "refund" && "Пополнение · "}
            {item.description ?? previous?.description} · <Money value={item.amount} />
            {item.bank_category && <small className={sheet.muted}> · {item.bank_category}</small>}
          </>
        )}
        {item.carried_over_failed && (
          <>
            {" "}
            <Badge>решение не перенесено</Badge>{" "}
            <HelpTip label="Предыдущее решение">
              {previousAction && labels[previousAction]
                ? `Раньше вы решили: „${labels[previousAction].toLowerCase()}“. Операция изменилась после проводки, проверьте ещё раз.`
                : "Операция изменилась после проводки, проверьте ещё раз."}
            </HelpTip>
          </>
        )}
      </div>
      {item.candidates.length > 0 && (
        <fieldset className={styles.candidates} aria-label="Операции из выписки">
          {item.candidates.map((row) => (
            <div key={row.id}>
              {item.candidates.length === 1 ? (
                <>
                  Выписка: <PreviewRowText row={row} />
                </>
              ) : (
                <label className={styles.radio}>
                  <input
                    type="radio"
                    name={`${id}-candidate`}
                    checked={candidate === row.id}
                    disabled={disabled}
                    onChange={() => setCandidate(row.id)}
                  />
                  Выписка: <PreviewRowText row={row} />
                </label>
              )}
            </div>
          ))}
        </fieldset>
      )}
      <p className={sheet.muted}>{consequence(item)}</p>
      {item.kind_hint === "cash_withdrawal" && (
        <p className={sheet.muted}>
          Похоже на снятие наличных. Снятие — не трата: наличные траты берутся из ручного файла.
        </p>
      )}
      {item.group === "transfer" && item.remember_key && (
        <p className={sheet.muted}>Запомнится для получателя „{item.remember_key}“</p>
      )}
      {item.group === "unknown_debit" && item.remember_key && (
        <p className={sheet.muted}>Запомнится для „{item.remember_key}“</p>
      )}
      {item.recurring && selectedCandidate !== undefined && (
        <p className={sheet.muted}>
          Связь запомнится: в следующих месяцах запись „{item.category}“ будет связываться с
          операциями „{item.candidates.find((row) => row.id === selectedCandidate)?.description}“
          сама, обе суммы останутся видны.
        </p>
      )}
      {actions.length > 0 && (
        <div className={styles.actions}>
          {!directCategory && (
            <div className={sheet.segmented} role="radiogroup" aria-label="Решение">
              {actions.map((value) => (
                <label className={styles.radio} key={value}>
                  <input
                    type="radio"
                    name={id}
                    checked={
                      action === value &&
                      (!newCategory || category !== item.category || !item.category)
                    }
                    disabled={disabled}
                    onChange={() => {
                      setAction(value);
                      setCategory(value === "refund" ? (item.bank_category ?? "") : "");
                      if (
                        value !== "expense" &&
                        value !== "refund" &&
                        (!(value === "link" || value === "duplicate") ||
                          selectedCandidate !== undefined)
                      ) {
                        submit(value);
                      }
                    }}
                  />
                  {newCategory ? "Отнести к…" : labels[value]}
                </label>
              ))}
              {newCategory && item.category && (
                <label className={styles.radio}>
                  <input
                    type="radio"
                    name={id}
                    checked={action === "expense" && category === item.category}
                    disabled={disabled}
                    onChange={() => {
                      setAction("expense");
                      setCategory(item.category ?? "");
                    }}
                  />
                  Создать категорию „{item.category}“
                </label>
              )}
            </div>
          )}
          {(needsCategory || directCategory) && (
            <CategoryPicker {...{ categories, category, setCategory, disabled }} />
          )}
          {canRemember && (
            <label>
              <input
                type="checkbox"
                checked={remember}
                disabled={disabled}
                onChange={(event) => setRemember(event.target.checked)}
              />{" "}
              {directCategory
                ? `Запомнить для „${item.remember_key}“`
                : `Всегда относить „${item.remember_key}“ к „${category}“`}
            </label>
          )}
          {(needsCategory || directCategory || needsCandidate) && (
            <Button
              variant="ghost"
              disabled={
                disabled ||
                !decisionCategory ||
                ((needsCategory || directCategory) && !category) ||
                (needsCandidate && selectedCandidate === undefined)
              }
              onClick={() => submit()}
            >
              Подтвердить
            </Button>
          )}
        </div>
      )}
      {action === "refund" && category && (
        <p className={sheet.muted}>
          Уменьшит траты категории „{category}“ в {spendingMonthForm(month, "prepositional")}.
        </p>
      )}
    </div>
  );
}

export function SpendingExceptions({
  items,
  resolved = [],
  categories,
  month,
  saved = false,
  disabled,
  onResolve,
  extra,
}: {
  items: SpendingException[];
  resolved?: ResolvedException[];
  categories: SpendingCategory[];
  month: string;
  saved?: boolean;
  disabled: boolean;
  onResolve: (item: SpendingException, decision: Resolution) => void;
  extra?: ReactNode;
}) {
  const outstanding = items.filter(needsDecision).length;
  const resolvedCount = resolved.filter(({ item }) => needsDecision(item)).length;
  if (!items.length && !resolved.length && !extra) return null;
  return (
    <div className={styles.exceptions}>
      <p className={sheet.muted}>
        осталось {outstanding} из {outstanding + resolvedCount}
      </p>
      {groups.map(([group, title, description]) => {
        const open = items.filter((item) => item.group === group);
        const closed = resolved.filter(({ item }) => item.group === group);
        if (!open.length && !closed.length) return null;
        const content = (
          <>
            {description && <p className={sheet.muted}>{description}</p>}
            {group === "entry_link" && (
              <p className={sheet.muted}>
                Эти расходы записаны в отчёте {spendingMonthForm(month, "genitive")}. Если выписка
                уже содержит тот же платёж, свяжите их, чтобы он не посчитался дважды.
              </p>
            )}
            {open.map((item) => (
              <ExceptionRow
                key={item.id}
                {...{ item, categories, saved, month, disabled, onResolve }}
              />
            ))}
            {closed.map(({ item, decision }) => (
              <ExceptionRow
                key={`${item.id}:${JSON.stringify(decision)}`}
                resolved={decision}
                {...{ item, categories, saved, month, disabled, onResolve }}
              />
            ))}
          </>
        );
        return (
          <div className={styles.group} key={group}>
            {group === "uncategorized" ? (
              <details>
                <summary>
                  {title} · {open.length}
                </summary>
                {content}
              </details>
            ) : (
              <>
                <h3>{title}</h3>
                {content}
              </>
            )}
          </div>
        );
      })}
      {extra}
    </div>
  );
}
