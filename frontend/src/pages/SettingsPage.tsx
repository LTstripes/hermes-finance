import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router";

import { ApiClientError, formatApiError } from "../api/client";
import {
  type AppSettings,
  type AppSettingsUpdate,
  getSettings,
  updateSettings,
} from "../api/settings";
import { BrokerIdentityMappingsPanel } from "../components/BrokerIdentityMappingsPanel";
import { DiagnosticsPanel } from "../components/RuntimeStatus";
import { TaxBracketsPanel } from "../components/TaxBracketsPanel";
import { Badge, Button, ErrorState, Field, Input, LoadingState, Panel } from "../components/ui";
import { formatMoney } from "../lib/format";

export function SettingsPage() {
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
  const dirty =
    settings !== null &&
    (normalizedLocale !== settings.locale ||
      normalizedTimezone !== settings.timezone ||
      historyStartMonth !== (settings.passive_income_history_start_month ?? ""));

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
    if (historyStartMonth !== (settings.passive_income_history_start_month ?? "")) {
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
      if (error instanceof ApiClientError && error.details.length > 0) {
        const serverFieldErrors: Record<string, string> = {};
        for (const detail of error.details) {
          if (detail.field === "locale") {
            serverFieldErrors.locale = "Некорректная локаль.";
          }
          if (detail.field === "timezone") {
            serverFieldErrors.timezone = "Некорректный часовой пояс.";
          }
        }
        setFieldErrors(serverFieldErrors);
      }
      setSaveError(formatApiError(error));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <LoadingState description="Загружаем настройки…" title="Настройки" />;
  }

  if (loadError || !settings) {
    return (
      <div className="stack-18">
        <ErrorState
          description={loadError ?? "Настройки недоступны"}
          title="Не удалось загрузить настройки"
        />
        <Button onClick={() => void load()}>Повторить</Button>
      </div>
    );
  }

  return (
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">Система</p>
        <h1>Настройки</h1>
        <p className="page-header__description">
          Основные параметры приложения, налоговые правила и диагностика.
        </p>
      </header>

      <form className="stack-18" onSubmit={handleSubmit}>
        <Panel
          action={<Link to="/goals">Открыть цели →</Link>}
          label="Цели"
          title="Цель пассивного дохода"
        >
          <div className="stack-8">
            <p>
              <strong>{formatMoney(settings.passive_income_goal.amount)}</strong>{" "}
              <Badge tone="info">{settings.passive_income_goal.currency}</Badge>
            </p>
            <p className="muted">
              Здесь показана текущая цель пассивного дохода. Изменить её можно в разделе «Цели».
            </p>
          </div>
        </Panel>

        <Panel
          action={
            <Button disabled={!dirty || saving} type="submit" variant="primary">
              {saving ? "Сохраняем…" : "Сохранить"}
            </Button>
          }
          label="Локальные"
          title="Приложение"
        >
          <div className="form-stack">
            <div className="form-row-2">
              <Field htmlFor="settings-locale" label="Локаль">
                <Input
                  id="settings-locale"
                  maxLength={32}
                  onChange={(event) => {
                    setLocale(event.target.value);
                    setSuccess(null);
                  }}
                  value={locale}
                />
              </Field>
              <Field htmlFor="settings-timezone" label="Часовой пояс">
                <Input
                  id="settings-timezone"
                  maxLength={64}
                  onChange={(event) => {
                    setTimezone(event.target.value);
                    setSuccess(null);
                  }}
                  value={timezone}
                />
              </Field>
            </div>
            {fieldErrors.locale ? (
              <p className="inline-alert inline-alert--error">{fieldErrors.locale}</p>
            ) : null}
            {fieldErrors.timezone ? (
              <p className="inline-alert inline-alert--error">{fieldErrors.timezone}</p>
            ) : null}
            <div className="field-row">
              <Field
                htmlFor="settings-history-start-month"
                label="Учитывать пассивный доход начиная с"
              >
                <Input
                  id="settings-history-start-month"
                  max="9999-12"
                  min="0001-01"
                  onChange={(event) => {
                    setHistoryStartMonth(event.target.value);
                    setSuccess(null);
                  }}
                  type="month"
                  value={historyStartMonth}
                />
              </Field>
              <Button
                disabled={historyStartMonth === "" || saving}
                onClick={() => {
                  setHistoryStartMonth("");
                  setSuccess(null);
                }}
                type="button"
                variant="ghost"
              >
                Сбросить
              </Button>
            </div>
            <p className="muted">
              Пустое значение учитывает всю доступную историю. Граница включается в расчёт.
            </p>
            {fieldErrors.historyStartMonth ? (
              <p className="inline-alert inline-alert--error">{fieldErrors.historyStartMonth}</p>
            ) : null}
            <div className="form-row-2">
              <div className="field">
                <span className="field__label">Базовая валюта</span>
                <p>
                  <Badge tone="neutral">{settings.base_currency}</Badge>
                </p>
                <p className="muted tiny">Поддерживается только RUB.</p>
              </div>
              <div className="field">
                <span className="field__label">Валюта расчётов</span>
                <p>Российский рубль</p>
                <p className="muted tiny">Все суммы в приложении показываются в RUB.</p>
              </div>
            </div>
            {saveError ? (
              <div className="inline-alert inline-alert--error" role="alert">
                {saveError}
              </div>
            ) : null}
            {success ? (
              <div className="inline-alert inline-alert--ok" role="status">
                {success}
              </div>
            ) : null}
          </div>
        </Panel>
      </form>

      <BrokerIdentityMappingsPanel />

      <TaxBracketsPanel />

      <div id="diagnostics">
        <DiagnosticsPanel />
      </div>
    </section>
  );
}
