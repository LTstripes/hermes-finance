import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { spendingApi, type SpendingOperation, type SpendingSource } from "../../api/spending";
import { Badge, Button, HelpTip, Table, Td, Th } from "../../components/ui";
import { pluralRu } from "../../lib/format";
import sheet from "../ReportSheet.module.css";
import { UiV2Loading, UiV2WidgetState } from "../UiV2StateBlocks";
import { Money, shortDate, sourceLabels } from "./common";
import styles from "./Spending.module.css";

export const operationForms = ["операция", "операции", "операций"] as const;

export function OperationTable({ items }: { items: SpendingOperation[] }) {
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
        {items.map((item) => (
          <tr key={`${item.source}:${item.id}`}>
            <Td>{shortDate(item.date)}</Td>
            <Td>
              {item.description} {item.processing && <Badge>в обработке</Badge>}{" "}
              {item.kind === "refund" && <Badge>возврат</Badge>}
              {item.is_month_entry && <small className={sheet.muted}>из отчёта месяца</small>}
              {item.linked_entry && (
                <HelpTip label="Связь с записью месяца">
                  Связана с записью месяца „{item.linked_entry.category}“ (
                  <Money value={item.linked_entry.amount} />)
                </HelpTip>
              )}
            </Td>
            <Td>{item.category_name}</Td>
            <Td>{item.is_month_entry ? "Запись месяца" : sourceLabels[item.source]}</Td>
            <Td numeric>
              <Money value={item.amount} />
            </Td>
          </tr>
        ))}
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
  const query = useQuery({
    queryKey: ["spending", "operations", month, category, source, limit],
    queryFn: ({ signal }) => spendingApi.operations(month, category, source, limit, signal),
  });
  if (query.isError) return <UiV2WidgetState retry={() => void query.refetch()} />;
  if (!query.data) return <UiV2Loading label="Загружаем операции" />;
  const { items, total_count, filtered_total } = query.data;
  return (
    <>
      {!inline && (
        <p className={sheet.figureDetail} style={{ textAlign: "end" }}>
          Показано {total_count} {pluralRu(total_count, ["операция", "операции", "операций"])} на{" "}
          <Money value={filtered_total} />
        </p>
      )}
      <OperationTable items={items} />
      {items.length < total_count && (
        <Button onClick={() => setLimit(total_count)}>Показать все {total_count}</Button>
      )}
    </>
  );
}
