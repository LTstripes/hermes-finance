import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router";

import { ApiClientError, formatApiError } from "../api/client";
import {
  type AppSettings,
  type AppSettingsUpdate,
  getSettings,
  updateSettings,
} from "../api/settings";
import { DiagnosticsPanel } from "../components/RuntimeStatus";
import { TaxBracketsPanel } from "../components/TaxBracketsPanel";
import { formatMoney } from "../lib/format";
import dataStyles from "./UiV2Data.module.css";
import styles from "./UiV2DataApp.module.css";
import { UiV2DataFrame } from "./UiV2DataShell";
import { UiV2Panel } from "./UiV2Panel";
import { UiV2Loading, UiV2Notice } from "./UiV2StateBlocks";

function settingsFieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiClientError)) return {};

  const result: Record<string, string> = {};
  for (const detail of error.details) {
    if (detail.field === "locale") result.locale = "Некорректная локаль.";
    if (detail.field === "timezone") result.timezone = "Некорректный часовой пояс.";
    if (detail.field === "passive_income_history_start_month") {
      result.historyStartMonth = "Укажи месяц в формате ГГГГ-ММ.";
    }
  }
  return result;
}

function SettingsPanel() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [locale, setLocale] = useState("");
  const [timezone, setTimezone] = useState("");
  const [historyStartMonth, setHistoryStartMonth] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setLoadError(null);
    try {
      const value = await getSettings(signal);
      if (signal?.aborted) return;
      setSettings(value);
      setLocale(value.locale);
      setTimezone(value.timezone);
      setHistoryStartMonth(value.passive_income_history_start_month ?? "");
      setSaveError(null);
      setSuccess(null);
      setFieldErrors({});
    } catch (error) {
      if (!signal?.aborted) {
        setSettings(null);
        setLoadError(formatApiError(error));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const normalizedLocale = locale.trim();
  const normalizedTimezone = timezone.trim();
  const savedHistoryStartMonth = settings?.passive_income_history_start_month ?? "";
  const dirty =
    settings !== null &&
    (normalizedLocale !== settings.locale ||
      normalizedTimezone !== settings.timezone ||
      historyStartMonth !== savedHistoryStartMonth);

  function validate(): boolean {
    const nextErrors: Record<string, string> = {};
    if (normalizedLocale.length < 2 || normalizedLocale.length > 32) {
      nextErrors.locale = "Локаль должна содержать от 2 до 32 символов.";
    }
    if (normalizedTimezone.length < 1 || normalizedTimezone.length > 64) {
      nextErrors.timezone = "Часовой пояс должен содержать от 1 до 64 символов.";
    }
    if (historyStartMonth !== "" && !/^\d{4}-(0[1-9]|1[0-2])$/.test(historyStartMonth)) {
      nextErrors.historyStartMonth = "Укажи месяц в формате ГГГГ-ММ.";
    }
    setFieldErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!settings || !dirty || saving || !validate()) return;

    const payload: AppSettingsUpdate = {};
    if (normalizedLocale !== settings.locale) payload.locale = normalizedLocale;
    if (normalizedTimezone !== settings.timezone) payload.timezone = normalizedTimezone;
    if (historyStartMonth !== savedHistoryStartMonth) {
      payload.passive_income_history_start_month = historyStartMonth || null;
    }

    setSaving(true);
    setSaveError(null);
    setSuccess(null);
    setFieldErrors({});
    try {
      const saved = await updateSettings(payload);
      setSettings(saved);
      setLocale(saved.locale);
      setTimezone(saved.timezone);
      setHistoryStartMonth(saved.passive_income_history_start_month ?? "");
      setSuccess("Настройки сохранены.");
    } catch (error) {
      setFieldErrors(settingsFieldErrors(error));
      setSaveError(formatApiError(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <UiV2Panel
      action={
        <span className={`${dataStyles.modeBadge} ${dataStyles.modeBadgeMutate}`}>
          Изменяет данные
        </span>
      }
      eyebrow="Локальная конфигурация"
      id="data-app-settings-title"
      testIdPrefix="data-app"
      title="Параметры приложения"
      wide
    >
      {loading ? (
        <UiV2Loading label="Читаем настройки приложения…" />
      ) : loadError || !settings ? (
        <UiV2Notice retry={() => void load()} title="Не удалось загрузить настройки">
          {loadError ?? "Настройки недоступны."}
        </UiV2Notice>
      ) : (
        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.fieldGrid}>
            <div className={styles.field}>
              <label htmlFor="v2-data-app-locale">Локаль</label>
              <input
                className={styles.input}
                id="v2-data-app-locale"
                maxLength={32}
                onChange={(event) => {
                  setLocale(event.target.value);
                  setSuccess(null);
                }}
                value={locale}
              />
              {fieldErrors.locale ? (
                <p className={styles.fieldError}>{fieldErrors.locale}</p>
              ) : null}
            </div>
            <div className={styles.field}>
              <label htmlFor="v2-data-app-timezone">Часовой пояс</label>
              <input
                className={styles.input}
                id="v2-data-app-timezone"
                maxLength={64}
                onChange={(event) => {
                  setTimezone(event.target.value);
                  setSuccess(null);
                }}
                value={timezone}
              />
              {fieldErrors.timezone ? (
                <p className={styles.fieldError}>{fieldErrors.timezone}</p>
              ) : null}
            </div>
          </div>

          <div className={styles.field}>
            <label htmlFor="v2-data-app-history-start-month">
              Учитывать пассивный доход начиная с
            </label>
            <div className={styles.fieldActions}>
              <input
                className={styles.input}
                id="v2-data-app-history-start-month"
                max="9999-12"
                min="0001-01"
                onChange={(event) => {
                  setHistoryStartMonth(event.target.value);
                  setSuccess(null);
                }}
                type="month"
                value={historyStartMonth}
              />
              <button
                className={styles.ghostButton}
                disabled={historyStartMonth === "" || saving}
                onClick={() => {
                  setHistoryStartMonth("");
                  setSuccess(null);
                }}
                type="button"
              >
                Сбросить
              </button>
            </div>
            <p className={styles.fieldHint}>
              Пустое значение учитывает всю доступную историю. Граница включается в расчёт.
            </p>
            {fieldErrors.historyStartMonth ? (
              <p className={styles.fieldError}>{fieldErrors.historyStartMonth}</p>
            ) : null}
          </div>

          <div className={dataStyles.badgeRow}>
            <span className={dataStyles.readOnlyBadge}>Только чтение</span>
            <span className={styles.note}>Валютный контекст не редактируется на этом экране.</span>
          </div>
          <dl className={styles.readOnlyGrid} aria-label="Контекст расчётов">
            <div className={styles.readOnlyItem}>
              <dt>Базовая валюта</dt>
              <dd>{settings.base_currency}</dd>
            </div>
            <div className={styles.readOnlyItem}>
              <dt>Валюта расчётов</dt>
              <dd>Российский рубль</dd>
            </div>
            <div className={styles.readOnlyItem}>
              <dt>Режим</dt>
              <dd>Только локально</dd>
            </div>
          </dl>

          <div className={styles.goalNote}>
            <strong>
              Цель пассивного дохода: {formatMoney(settings.passive_income_goal.amount)}
            </strong>
            <span className={styles.note}>
              Цель не редактируется в разделе «Данные и приложение», чтобы не создавать второй
              редактор.
            </span>
            <div className={styles.goalActions}>
              <Link to="/v2/income">Открыть «Доход и планы» →</Link>
              <Link to="/goals">Цели в текущем интерфейсе ↗</Link>
            </div>
          </div>

          {saveError ? (
            <div className={styles.error} role="alert">
              {saveError}
            </div>
          ) : null}
          {success ? (
            <div className={styles.success} role="status">
              {success}
            </div>
          ) : null}

          <div className={styles.actions}>
            <p className={styles.note}>
              Без cloud, auth и telemetry. Сохраняются только изменённые поля.
            </p>
            <button className={styles.primaryButton} disabled={!dirty || saving} type="submit">
              {saving ? "Сохраняем…" : "Сохранить настройки"}
            </button>
          </div>
        </form>
      )}
    </UiV2Panel>
  );
}

export default function UiV2DataAppPage() {
  return (
    <UiV2DataFrame
      active="app"
      subtitle="Локальные настройки, налоговые правила и сведения о текущей среде исполнения."
      title="Приложение"
      v1ReturnPath="/settings"
    >
      <div className={styles.stack}>
        <SettingsPanel />

        <div className={styles.compatPanel} data-testid="data-app-tax">
          <div className={dataStyles.badgeRow}>
            <span className={`${dataStyles.modeBadge} ${dataStyles.modeBadgeMutate}`}>
              Изменяет данные
            </span>
            <span className={styles.note}>Полная шкала сохраняется одной атомарной операцией.</span>
          </div>
          <TaxBracketsPanel />
        </div>

        <div className={styles.compatPanel} data-testid="data-app-diagnostics">
          <div className={dataStyles.badgeRow}>
            <span className={dataStyles.readOnlyBadge}>Только чтение</span>
            <span className={styles.note}>
              Проверка не изменяет настройки или финансовые данные.
            </span>
          </div>
          <div className={styles.diagnosticsAnchor} id="diagnostics">
            <DiagnosticsPanel />
          </div>
        </div>
      </div>
    </UiV2DataFrame>
  );
}
