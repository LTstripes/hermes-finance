import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { spendingApi, type SpendingOperation, type SpendingSource } from "../../api/spending";
import { paymentApi, type PaymentRule } from "../../api/spendingPayments";
import { PaymentRuleDialog } from "./PaymentRuleDialog";
import { Badge, Button, HelpTip, Table, Td, Th } from "../../components/ui";
import { pluralRu } from "../../lib/format";
import sheet from "../ReportSheet.module.css";
import { UiV2Loading, UiV2WidgetState } from "../UiV2StateBlocks";
import { Money, shortDate, sourceLabels } from "./common";
import styles from "./Spending.module.css";

export const operationForms = ["операция", "операции", "операций"] as const;

export function OperationTable({
  items,
  rules,
  select,
}: {
  items: SpendingOperation[];
  rules: PaymentRule[];
  select: (item: SpendingOperation) => void;
}) {
  if (!items.length) return <UiV2WidgetState title="Операций нет" />;
  return (
    <Table className={styles.dataTable}>
      <thead>
        <tr>
          {["Дата", "Описание", "Категория", "Источник", "Сумма"].map((label) => (
            <Th key={label} numeric={label === "Сумма"}>
              {label}
            </Th>
          ))}
        </tr>
      </thead>
      <tbody>
        {items.map((item) => {
          const rule = rules.find(
            (r) => !r.needs_review && r.source === item.source && r.operation_id === item.id,
          );
          const metadata = [
            rule?.note,
            rule?.repeat && "Повторяется",
            rule?.mandatory_override === true && "Обязательная",
            item.is_month_entry && "из отчёта месяца",
          ]
            .filter(Boolean)
            .join(" · ");
          return (
            <tr key={`${item.source}:${item.id}`}>
              <Td>{shortDate(item.date)}</Td>
              <Td>
                <div className={styles.operationTitle}>
                  {item.kind === "purchase" && !/^0(?:\.0+)?$/.test(item.amount.amount) ? (
                    <button
                      type="button"
                      className={styles.paymentLink}
                      onClick={() => select(item)}
                    >
                      {item.description}
                    </button>
                  ) : (
                    item.description
                  )}{" "}
                  {item.processing && <Badge>в обработке</Badge>}{" "}
                  {item.kind === "refund" && <Badge>возврат</Badge>}
                </div>
                {(metadata || item.linked_entry) && (
                  <div className={styles.operationMeta}>
                    {metadata}
                    {item.linked_entry && (
                      <HelpTip label="Связь с записью месяца">
                        Связана с записью месяца „{item.linked_entry.category}“ (
                        <Money value={item.linked_entry.amount} />)
                      </HelpTip>
                    )}
                  </div>
                )}
              </Td>
              <Td>{item.category_name}</Td>
              <Td>{item.is_month_entry ? "Запись месяца" : sourceLabels[item.source]}</Td>
              <Td numeric>
                <Money value={item.amount} />
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

export function Operations({
  month,
  category,
  source,
  inline = false,
}: {
  month: string;
  category?: number;
  source?: SpendingSource;
  inline?: boolean;
}) {
  const [limit, setLimit] = useState(50);
  const [selected, setSelected] = useState<SpendingOperation | null>(null);
  const rules = useQuery({
    queryKey: ["spending", "payment-rules", month],
    queryFn: ({ signal }) => paymentApi.list(month, signal),
  });
  const cache = useQueryClient();
  const archive = useMutation({
    mutationFn: async (rule: PaymentRule) => {
      await paymentApi.archive(month, rule);
      const read = await paymentApi.list(month);
      if (!read.find((r) => r.id === rule.id && r.archived))
        throw new Error("Не удалось подтвердить архивирование");
    },
    onSettled: async () => {
      await cache.invalidateQueries({ queryKey: ["spending", "payment-rules", month] });
      await cache.invalidateQueries({ queryKey: ["spending", "reserve"] });
    },
  });
  const detached = rules.data?.filter((r) => r.needs_review) ?? [];
  const query = useQuery({
    queryKey: ["spending", "operations", month, category, source, limit],
    queryFn: ({ signal }) => spendingApi.operations(month, category, source, limit, signal),
  });
  if (query.isError) return <UiV2WidgetState retry={() => void query.refetch()} />;
  if (!query.data) return <UiV2Loading label="Загружаем операции" />;
  const { items, total_count, filtered_total } = query.data;
  return (
    <>
      {!inline && total_count > 0 && (
        <p className={sheet.figureDetail} style={{ textAlign: "end" }}>
          Показано {total_count} {pluralRu(total_count, ["операция", "операции", "операций"])} на{" "}
          <Money value={filtered_total} />
        </p>
      )}
      {rules.isError && (
        <p role="alert">
          Не удалось загрузить пометки.{" "}
          <Button onClick={() => void rules.refetch()}>Повторить</Button>
        </p>
      )}
      {!inline && detached.length > 0 && (
        <details className={styles.detachedNotes}>
          <summary>Пометки без покупки · {detached.length}</summary>
          <p>Выберите покупку в ленте и восстановите связь с прежней пометкой.</p>
          <ul>
            {detached.map((rule) => (
              <li key={rule.id}>
                {rule.title} · {rule.note || "Без заметки"}{" "}
                {rule.archived ? (
                  "В архиве"
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={archive.isPending}
                    onClick={() => archive.mutate(rule)}
                  >
                    В архив
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {archive.isError && (
        <p role="alert">Не удалось подтвердить архивирование. Обновите список пометок.</p>
      )}
      <OperationTable items={items} rules={rules.data ?? []} select={setSelected} />
      {selected && (
        <PaymentRuleDialog
          purchase={{ month, source: selected.source, id: selected.id }}
          detached={detached}
          onClose={() => setSelected(null)}
        />
      )}
      {items.length < total_count && (
        <Button onClick={() => setLimit(total_count)}>Показать все {total_count}</Button>
      )}
    </>
  );
}
