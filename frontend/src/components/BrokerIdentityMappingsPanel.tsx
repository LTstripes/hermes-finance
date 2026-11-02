import { useQuery } from "@tanstack/react-query";

import { listBrokerIdentityMappings } from "../api/brokerIdentityMappings";
import { SOURCE_LABELS } from "../lib/labels";

const STATUS_LABELS: Record<string, string> = {
  effective: "Действует",
  revoked: "Отозвано",
  superseded: "Заменено",
};
const KIND_LABELS: Record<string, string> = { account: "Счёт", instrument: "Инструмент" };

/** Retained registry history is readable independently of installed providers. */
export function BrokerIdentityMappingsPanel() {
  const mappings = useQuery({
    queryKey: ["broker-identity-mappings"],
    queryFn: ({ signal }) => listBrokerIdentityMappings(undefined, signal),
  });
  if (mappings.isPending) return <p role="status">Загружаем сопоставления…</p>;
  if (mappings.isError) return <p role="alert">Не удалось загрузить сопоставления.</p>;
  if (mappings.data.length === 0) return <p>Сохранённых сопоставлений нет.</p>;
  return (
    <section aria-label="Сохранённые сопоставления брокеров">
      <table>
        <thead>
          <tr>
            <th>Источник</th>
            <th>Идентификатор</th>
            <th>Объект Hermes</th>
            <th>Состояние</th>
          </tr>
        </thead>
        <tbody>
          {mappings.data.map((row) => (
            <tr key={row.mapping_id}>
              <td>{SOURCE_LABELS[row.provider] ?? row.provider}</td>
              <td>{row.provider_identity}</td>
              <td>
                {KIND_LABELS[row.subject_kind] ?? row.subject_kind} {row.hermes_target_id}
              </td>
              <td>{STATUS_LABELS[row.status] ?? row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
