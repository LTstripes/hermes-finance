import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { formatApiError } from "../api/client";
import { listAllSourceIntakes, readSourceIntake } from "../api/sourceIntake";
import { BrokerProvisionalEstimate } from "../components/month-close/BrokerProvisionalEstimate";
import { formatDate } from "../lib/format";
import { UiV2DataFrame } from "./UiV2DataShell";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

/** Zero-metadata desktop entry for an existing unbound source-intake journal. */
export default function UiV2SourceIntakePage() {
  const list = useQuery({
    queryKey: ["source-intakes", "all"],
    queryFn: ({ signal }) => listAllSourceIntakes(signal),
    refetchOnWindowFocus: true,
  });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const detail = useQuery({
    queryKey: ["source-intake", "detail", selectedId],
    queryFn: ({ signal }) => readSourceIntake(selectedId as number, signal),
    enabled: selectedId !== null,
  });
  const selected = selectedId !== null ? (detail.data ?? null) : null;
  const intakes = list.data ?? [];

  let content: ReactNode;
  if (list.isPending) {
    content = <UiV2Loading label="Читаем сохранённые разборы источника…" />;
  } else if (list.isError) {
    content = (
      <UiV2Notice title="Не удалось прочитать разборы источника" retry={() => void list.refetch()}>
        {formatApiError(list.error)}
      </UiV2Notice>
    );
  } else if (intakes.length === 0) {
    content = (
      <UiV2Notice title="Сохранённых разборов нет">
        Журнал источника пока пуст. Сохранённый разбор можно подготовить в закрытии отчётного
        месяца; эта страница ничего не создаёт и не применяет.
      </UiV2Notice>
    );
  } else {
    content = (
      <>
        <p>
          Только чтение. Страница выбирает уже сохранённый журнал и заново прикладывает его точный
          оригинал. Она не создаёт счёт, отчётный месяц, инструмент или финансовую привязку и не
          выполняет финансовый Apply.
        </p>
        <label>
          Сохранённый разбор
          <select
            aria-label="Сохранённый разбор"
            value={selectedId ?? ""}
            onChange={(event) => {
              setSelectedId(event.target.value ? Number(event.target.value) : null);
              setFile(null);
            }}
          >
            <option value="">Выбери разбор</option>
            {intakes.map((intake) => (
              <option key={intake.id} value={intake.id}>
                #{intake.id} · {formatDate(intake.covered_from)} — {formatDate(intake.covered_to)} ·{" "}
                {intake.state.reporting_month_id === null ? "без привязки" : "привязан"} ·{" "}
                {intake.observations.length} наблюдений
              </option>
            ))}
          </select>
        </label>
        {selectedId !== null && detail.isPending && (
          <UiV2Loading label="Читаем выбранный разбор…" />
        )}
        {detail.isError && (
          <UiV2Notice
            title="Не удалось прочитать выбранный разбор"
            retry={() => void detail.refetch()}
          >
            {formatApiError(detail.error)}
          </UiV2Notice>
        )}
        {selected && (
          <>
            <p role="status">
              #{selected.id} · {formatDate(selected.covered_from)} —{" "}
              {formatDate(selected.covered_to)} ·{" "}
              {selected.state.reporting_month_id === null
                ? "без привязки к Hermes-счёту или отчётному месяцу"
                : `привязан к отчётному месяцу #${selected.state.reporting_month_id}`}{" "}
              · наблюдений: {selected.observations.length} · исключений:{" "}
              {selected.exceptions.length} · финансовая власть:{" "}
              {selected.financial_authority === "none" ? "нет" : selected.financial_authority}
            </p>
            <label>
              Точный оригинал XML
              <input
                aria-label="Точный оригинал XML"
                type="file"
                accept=".xml"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <p>
              Файл остаётся только в памяти страницы. После перезагрузки журнал хранит наблюдения,
              но не сами байты; выбери тот же неизменённый оригинал.
            </p>
            <BrokerProvisionalEstimate
              key={`${selected.id}:${selected.head_seq}:${selected.manifest_digest}`}
              intake={selected}
              file={file}
            />
          </>
        )}
      </>
    );
  }

  return (
    <UiV2DataFrame
      active="source-intake"
      subtitle="Сохранённый источник, его точный оригинал и read-only предварительная оценка без финансового Apply."
      title="Разбор источника"
      v1ReturnPath="/freshness"
    >
      {content}
    </UiV2DataFrame>
  );
}
