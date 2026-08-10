import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiClientError, formatApiError } from "../api/client";
import {
  getSettings,
  updateSettings,
  type AppSettings,
  type AppSettingsUpdate,
} from "../api/settings";
import { Badge, Button, ErrorState, Field, Input, LoadingState, Panel } from "../components/ui";

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [locale, setLocale] = useState("");
  const [timezone, setTimezone] = useState("");
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
    (normalizedLocale !== settings.locale || normalizedTimezone !== settings.timezone);

  function validate(): boolean {
    const nextErrors: Record<string, string> = {};
    if (normalizedLocale.length < 2 || normalizedLocale.length > 32) {
      nextErrors.locale = "Локаль должна содержать от 2 до 32 символов.";
    }
    if (normalizedTimezone.length < 1 || normalizedTimezone.length > 64) {
      nextErrors.timezone = "Часовой пояс должен содержать от 1 до 64 символов.";
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

    setSaving(true);
    setSaveError(null);
    setSuccess(null);
    setFieldErrors({});
    try {
      const saved = await updateSettings(payload);
      setSettings(saved);
      setLocale(saved.locale);
      setTimezone(saved.timezone);
      setSuccess("Настройки сохранены.");
    } catch (error) {
      if (error instanceof ApiClientError && error.details.length > 0) {
        const serverFieldErrors: Record<string, string> = {};
        for (const detail of error.details) {
          if (detail.field === "locale" || detail.field === "timezone") {
            serverFieldErrors[detail.field] = detail.message;
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
    return <LoadingState description="Загружаем /api/settings…" title="Настройки" />;
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
          Только локальные настройки с подтверждённым backend-контрактом. Финансовые правила здесь
          не редактируются.
        </p>
      </header>

      <form className="stack-18" onSubmit={handleSubmit}>
        <Panel label="Цели" title="Цель пассивного дохода">
          <div className="stack-8">
            <p>
              <strong>{settings.passive_income_goal.amount}</strong>{" "}
              <Badge tone="info">{settings.passive_income_goal.currency}</Badge>
            </p>
            <p className="muted">
              Сейчас только для просмотра. Управление основной целью будет перенесено в раздел
              «Цели» после R02-11, чтобы не создавать два source of truth.
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
            <p className="muted">
              Локаль и часовой пояс сохраняются backend, но пока не управляют всем форматированием
              интерфейса.
            </p>
            <div className="form-row-2">
              <div className="field">
                <span className="field__label">Базовая валюта</span>
                <p>
                  <Badge tone="neutral">{settings.base_currency}</Badge>
                </p>
                <p className="muted tiny">Поддерживается только RUB.</p>
              </div>
              <div className="field">
                <span className="field__label">Версия формул</span>
                <p>
                  <code>{settings.formula_version}</code>
                </p>
                <p className="muted tiny">Служебное значение; вручную не редактируется.</p>
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

      <Panel empty label="Ограничения" title="Пока недоступно">
        <div className="stack-8">
          <p>
            <Badge tone="info">R02-11</Badge> Редактирование основной финансовой цели.
          </p>
          <p>
            <Badge tone="info">R02-17</Badge> Управление налоговыми ставками.
          </p>
          <p className="muted">
            Путь резервных копий и настройки экспорта пока не имеют отдельного settings
            API-контракта.
          </p>
        </div>
      </Panel>
    </section>
  );
}
