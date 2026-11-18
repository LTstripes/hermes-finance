import type { FileProblem, SpendingPreview } from "../../api/spending";
import { Button, Table, Td, Th } from "../../components/ui";
import { pluralRu } from "../../lib/format";
import sheet from "../ReportSheet.module.css";
import { UiV2Notice } from "../UiV2StateBlocks";
import { spendingMonthForm } from "../uiV2Copy";
import { Money, rangeText } from "./common";
import { PreviewRowText } from "./SpendingExceptions";
import { previewProblem, unreadableReason } from "./previewCopy";
import styles from "./Spending.module.css";

export function TotalChange({ preview }: { preview: SpendingPreview }) {
  return (
    <>
      Траты за {spendingMonthForm(preview.month, "accusative")}:{" "}
      <Money value={preview.total_before} empty="не загружено" /> →{" "}
      <Money value={preview.total_after} empty="Недоступно" />
    </>
  );
}

export function FormatErrors({ preview }: { preview: SpendingPreview }) {
  const statementRows = preview.file_errors.filter(
    (error) => error.file === "statement" && error.line !== undefined,
  );
  const fileErrors = preview.file_errors.filter((error) => error.line === undefined);
  if (statementRows.length) fileErrors.push(statementRows[0]);
  return fileErrors.map((error) => {
    const problem = previewProblem(error, preview.month, statementRows.length);
    return (
      <div key={`${error.file}:${error.code}`}>
        <UiV2Notice title={problem.title} alert>
          {problem.text}
        </UiV2Notice>
        {error.line !== undefined && (
          <ul>
            {statementRows.map((row) => (
              <li key={row.line}>Строка {row.line}</li>
            ))}
          </ul>
        )}
      </div>
    );
  });
}
export function UnreadableRows({
  rows,
  skipped,
  disabled,
  onSkip,
}: {
  rows: FileProblem[];
  skipped: boolean;
  disabled: boolean;
  onSkip: (next: boolean) => void;
}) {
  if (!rows.length) return null;
  return (
    <div className={styles.group}>
      <h3>Строки, которые не удалось прочитать</h3>
      <ul>
        {rows.map((row) => (
          <li key={row.line}>
            Строка {row.line}: {unreadableReason(row.code)}
          </li>
        ))}
      </ul>
      <label>
        <input
          type="checkbox"
          checked={skipped}
          disabled={disabled}
          onChange={(event) => onSkip(event.target.checked)}
        />{" "}
        Пропустить эти строки и применить остальное
      </label>
    </div>
  );
}

export function PreviewDetails({
  preview,
  confirmed,
  setConfirmed,
  disabled,
  onSeparate,
}: {
  preview: SpendingPreview;
  confirmed: boolean;
  setConfirmed: (confirmed: boolean) => void;
  disabled: boolean;
  onSeparate: (entryId: number) => void;
}) {
  const removed = preview.sets.flatMap((set) => set.removed_items);
  const range = rangeText(preview.coverage);
  const outside = rangeText(preview.out_of_month);
  const automatic = preview.entry_links.filter((link) => link.automatic);
  return (
    <>
      <strong>
        <TotalChange preview={preview} />
      </strong>
      <Table className={styles.dataTable}>
        <thead>
          <tr>
            {["Набор", "Добавится", "Изменится", "Исчезнет", "Траты набора"].map((label, index) => (
              <Th key={label} numeric={index > 0}>
                {label}
              </Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.sets.map((set, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: The API returns sets in stable account order, with masked labels that may coincide.
            <tr key={`${set.label}:${index}`}>
              <Td>{set.label}</Td>
              <Td numeric>{set.added || "—"}</Td>
              <Td numeric>
                {set.changed ? (
                  <details>
                    <summary>{set.changed}</summary>
                    <ul>
                      {set.changed_items.map((row) => (
                        <li key={`${row.fingerprint}:${row.ordinal}`}>
                          <PreviewRowText row={row} />
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : (
                  "—"
                )}
              </Td>
              <Td numeric>{set.removed || "—"}</Td>
              <Td numeric>
                {set.total_before && (
                  <>
                    <Money value={set.total_before} /> →{" "}
                  </>
                )}
                <Money value={set.total_after} />
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {preview.out_of_month.count > 0 && (
        <details className={sheet.muted}>
          <summary>
            Вне {spendingMonthForm(preview.month, "genitive")}: {preview.out_of_month.count}{" "}
            {pluralRu(preview.out_of_month.count, ["строка", "строки", "строк"])} — не записываются
          </summary>
          {outside}
        </details>
      )}
      {preview.technical.count > 0 && (
        <details className={sheet.muted}>
          <summary>
            Технические операции: {preview.technical.count} — не траты (переводы между своими
            счетами, погашение кредита, проценты на остаток)
          </summary>
          <ul>
            {preview.technical.items.map((row) => (
              <li key={row.id}>
                <PreviewRowText row={row} /> ·{" "}
                {row.kind === "interest"
                  ? "Проценты на остаток"
                  : row.kind === "repayment"
                    ? "Погашение кредита"
                    : "Перевод между своими счетами"}
              </li>
            ))}
          </ul>
        </details>
      )}
      {preview.processing.count > 0 && (
        <p className={sheet.muted}>
          В обработке: {preview.processing.count}{" "}
          {pluralRu(preview.processing.count, ["операция", "операции", "операций"])} на{" "}
          <Money value={preview.processing.amount} /> — войдут в траты; после проводки банк может
          изменить описание
        </p>
      )}
      {!preview.coverage.full && range && (
        <p className={styles.coverageWarning}>
          Файл покрывает {range}: месяц будет помечен „частично“
        </p>
      )}
      {automatic.length > 0 && (
        <details className={sheet.muted}>
          <summary>Связано автоматически: {automatic.length}</summary>
          {automatic.map((link) => (
            <div className={styles.actions} key={link.expense_entry_id}>
              {link.entry_category} · <Money value={link.month_amount} /> ·{" "}
              <Money value={link.diary_amount} />
              <Button
                variant="ghost"
                disabled={disabled}
                onClick={() => onSeparate(link.expense_entry_id)}
              >
                Отменить связь
              </Button>
            </div>
          ))}
        </details>
      )}
      {preview.blocking.needs_removal_confirmation && (
        <div className={styles.warning}>
          <strong>
            <span className={styles.warningIcon} aria-hidden="true">
              ⚠{" "}
            </span>
            {preview.removed === 1
              ? "Исчезнет 1 ранее загруженная операция"
              : `Исчезнут ${preview.removed} ранее загруженные операции`}
            {preview.removed === 1 ? " — её нет в новом файле." : " — их нет в новом файле."}
          </strong>
          <ul>
            {removed.slice(0, 20).map((row) => (
              <li key={`${row.fingerprint}:${row.ordinal}`}>
                <PreviewRowText row={row} />
              </li>
            ))}
          </ul>
          {removed.length > 20 && <p>и ещё {removed.length - 20}</p>}
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              disabled={disabled}
              onChange={(event) => setConfirmed(event.target.checked)}
            />{" "}
            Понимаю, эти операции будут удалены из трат
          </label>
        </div>
      )}
    </>
  );
}
