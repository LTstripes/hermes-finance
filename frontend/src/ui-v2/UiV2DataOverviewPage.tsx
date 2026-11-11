import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useLocation } from "react-router";

import { listAccounts } from "../api/accounts";
import { createBackup, listBackups } from "../api/backups";
import { formatApiError } from "../api/client";
import { getHealth } from "../api/health";
import { listInstruments } from "../api/instruments";
import type { BackupMetadata } from "../api/types";
import { formatDate } from "../lib/format";
import { queryKeys } from "../queryClient";
import { dataAppPath } from "./monthSelection";
import styles from "./UiV2DataOverview.module.css";
import { UiV2DataFrame } from "./UiV2DataShell";
import { UiV2Panel } from "./UiV2Panel";
import { isQueryReady } from "./UiV2StateBlocks";

export default function UiV2DataOverviewPage() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const backups = useQuery({
    queryKey: queryKeys.backups,
    queryFn: ({ signal }) => listBackups(signal),
  });
  const accounts = useQuery({
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
  });
  const instruments = useQuery({
    queryKey: queryKeys.instruments,
    queryFn: ({ signal }) => listInstruments({}, signal),
  });
  const health = useQuery({ queryKey: ["health"], queryFn: ({ signal }) => getHealth(signal) });
  const creating = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const latestBackup = isQueryReady(backups)
    ? [...(backups.data ?? [])].sort(
        (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
      )[0]
    : undefined;
  const path = (section: Parameters<typeof dataAppPath>[0]) =>
    dataAppPath(section, undefined, location.search);

  async function makeBackup() {
    if (creating.current) return;
    creating.current = true;
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const backup = await createBackup();
      // The same operation and confirmed metadata as on Export and copies.
      queryClient.setQueryData<BackupMetadata[]>(queryKeys.backups, (current) => [
        backup,
        ...(current ?? []).filter((item) => item.id !== backup.id),
      ]);
      await backups.refetch();
      setSuccess(true);
    } catch (cause) {
      setError(formatApiError(cause));
    } finally {
      creating.current = false;
      setSaving(false);
    }
  }

  return (
    <UiV2DataFrame active="overview" title="Настройки" subtitle="Копии, справочники и приложение.">
      <div className={styles.cards}>
        <UiV2Panel
          eyebrow="Сохранность данных"
          id="settings-backup"
          testIdPrefix="settings"
          title="Резервная копия"
        >
          <p>
            {!isQueryReady(backups) ? (
              backups.isError ? (
                "Сведения о копиях недоступны"
              ) : (
                "Проверяем копии…"
              )
            ) : latestBackup ? (
              <>
                Последняя копия:{" "}
                <time dateTime={latestBackup.created_at}>
                  {formatDate(latestBackup.created_at)}
                </time>
              </>
            ) : (
              "Резервных копий пока нет"
            )}
          </p>
          <div className={styles.actions}>
            <button
              className="btn btn--primary"
              disabled={saving}
              onClick={() => void makeBackup()}
              type="button"
            >
              {saving ? "Создаём копию…" : "Создать копию"}
            </button>
            <Link to={`${path("files")}#files-backups-title`}>Все копии →</Link>
          </div>
          {error ? <p role="alert">{error}</p> : null}
          {success ? <p role="status">Резервная копия создана.</p> : null}
        </UiV2Panel>
        <UiV2Panel
          eyebrow="Справочники"
          id="settings-catalogs"
          testIdPrefix="settings"
          title="Счета и инструменты"
        >
          <p>
            {isQueryReady(accounts) && isQueryReady(instruments)
              ? `Счетов: ${accounts.data?.length} · инструментов: ${instruments.data?.length}`
              : accounts.isError || instruments.isError
                ? "Справочники недоступны"
                : "Загружаем справочники…"}
          </p>
          <Link to={path("catalogs")}>Открыть справочники →</Link>
        </UiV2Panel>
        <UiV2Panel
          eyebrow="Актуальность"
          id="settings-sources"
          testIdPrefix="settings"
          title="Источники данных"
        >
          <Link to={path("sources")}>Проверить выписки и прогноз выплат →</Link>
        </UiV2Panel>
        <UiV2Panel eyebrow="Экспорт" id="settings-ai" testIdPrefix="settings" title="Отчёт для AI">
          <Link to={`${path("files")}#files-exports-title`}>Подготовить отчёт →</Link>
        </UiV2Panel>
        <UiV2Panel eyebrow="Локально" id="settings-app" testIdPrefix="settings" title="Приложение">
          <p>
            {isQueryReady(health)
              ? `Версия ${health.data?.version}`
              : health.isError
                ? "Версия недоступна"
                : "Проверяем версию…"}
          </p>
          <Link to={path("app")}>Параметры и диагностика →</Link>
        </UiV2Panel>
      </div>
    </UiV2DataFrame>
  );
}
