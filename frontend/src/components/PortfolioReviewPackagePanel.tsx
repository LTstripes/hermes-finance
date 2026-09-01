import { useState } from "react";

import { formatApiError } from "../api/client";
import {
  downloadPortfolioReviewPackage,
  getPortfolioReviewPackage,
  type PortfolioReviewPackage,
  type PortfolioReviewProfile,
  type PortfolioReviewSectionId,
  type PortfolioReviewSectionStatus,
} from "../api/portfolioReviewPackage";
import { Badge, Button, Field, Panel, Select } from "./ui";

const SECTION_LABELS: Record<PortfolioReviewSectionId, string> = {
  capital: "Капитал",
  positions: "Позиции",
  dynamics: "Динамика",
  passive_income: "Пассивный доход",
  future_cash_flows: "Будущие денежные потоки",
  freshness: "Актуальность данных",
  allocation: "Распределение и концентрация",
  context: "Контекст целей, долгов и налогов",
  deterministic_insights: "Детерминированные сигналы",
};

const STATUS_LABELS: Record<PortfolioReviewSectionStatus, string> = {
  included: "Включён",
  partial: "Частично",
  unavailable: "Недоступен",
  omitted: "Опущен профилем",
};

function statusTone(status: PortfolioReviewSectionStatus) {
  if (status === "included") return "ok" as const;
  if (status === "partial") return "stale" as const;
  if (status === "unavailable") return "missing" as const;
  return "neutral" as const;
}

function periodLabel(period: { year: number; month: number }): string {
  return `${period.year}-${String(period.month).padStart(2, "0")}`;
}

function packageSummary(packageData: PortfolioReviewPackage): string[] {
  const summary = [`Срез ${periodLabel(packageData.scope.reporting_period)}`];
  const positions = packageData.sections.positions.data?.items;
  if (Array.isArray(positions)) summary.push(`${positions.length} позиций`);
  const history = packageData.sections.dynamics.data?.history;
  if (Array.isArray(history)) summary.push(`${history.length} периодов истории`);
  const warnings = packageData.warnings.length;
  if (warnings > 0) summary.push(`${warnings} предупреждений`);
  return summary;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function PortfolioReviewPackagePanel() {
  const [profile, setProfile] = useState<PortfolioReviewProfile>("concise");
  const [packageData, setPackageData] = useState<PortfolioReviewPackage | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [downloading, setDownloading] = useState<"json" | "markdown" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function prepare() {
    setPreparing(true);
    setError(null);
    setSuccess(null);
    try {
      setPackageData(await getPortfolioReviewPackage(profile));
    } catch (cause) {
      setPackageData(null);
      setError(formatApiError(cause));
    } finally {
      setPreparing(false);
    }
  }

  async function download(format: "json" | "markdown") {
    setDownloading(format);
    setError(null);
    setSuccess(null);
    try {
      const file = await downloadPortfolioReviewPackage(profile, format);
      triggerDownload(file.blob, file.filename);
      setSuccess(`Файл ${file.filename} скачан.`);
    } catch (cause) {
      setError(formatApiError(cause));
    } finally {
      setDownloading(null);
    }
  }

  const unavailableOrOmitted = packageData
    ? (
        Object.entries(packageData.sections) as Array<
          [PortfolioReviewSectionId, PortfolioReviewPackage["sections"][PortfolioReviewSectionId]]
        >
      ).filter(([, section]) => section.status === "unavailable" || section.status === "omitted")
    : [];

  return (
    <Panel label="Локальная передача" title="Подготовить пакет для анализа">
      <div className="portfolio-review-package stack-12">
        <p>
          Сформируй безопасный срез из локальных данных Hermes без изменения учёта. Пакет не
          загружается в облако и не отправляется ассистенту автоматически.
        </p>
        <div className="portfolio-review-package__controls">
          <Field htmlFor="portfolio-review-profile" label="Профиль пакета">
            <Select
              id="portfolio-review-profile"
              onChange={(event) => {
                setProfile(event.target.value as PortfolioReviewProfile);
                setPackageData(null);
                setError(null);
                setSuccess(null);
              }}
              value={profile}
            >
              <option value="concise">Concise — основные ответы</option>
              <option value="full">Full — расширенный контекст</option>
            </Select>
          </Field>
          <Button
            disabled={preparing || downloading !== null}
            onClick={() => void prepare()}
            variant="primary"
          >
            {preparing ? "Готовим предпросмотр…" : "Подготовить пакет для анализа"}
          </Button>
        </div>

        <div className="inline-alert inline-alert--warn">
          Пакет содержит финансовые данные. Перед ручной передачей проверь состав файла и профиль.
        </div>

        {error ? (
          <div className="inline-alert inline-alert--error" role="alert">
            {error}
          </div>
        ) : null}
        {success ? (
          <div className="inline-alert inline-alert--ok" role="status">
            {success}
          </div>
        ) : null}

        {packageData ? (
          <section
            aria-label="Предпросмотр пакета для анализа"
            className="portfolio-review-package__preview"
          >
            <div className="portfolio-review-package__summary">
              <strong>{packageData.profile === "full" ? "Full" : "Concise"}</strong>
              {packageSummary(packageData).map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>

            <div className="portfolio-review-package__sections">
              {(
                Object.entries(packageData.sections) as Array<
                  [
                    PortfolioReviewSectionId,
                    PortfolioReviewPackage["sections"][PortfolioReviewSectionId],
                  ]
                >
              ).map(([id, section]) => (
                <div className="portfolio-review-package__section" key={id}>
                  <span>{SECTION_LABELS[id]}</span>
                  <Badge tone={statusTone(section.status)}>{STATUS_LABELS[section.status]}</Badge>
                </div>
              ))}
            </div>

            {unavailableOrOmitted.length > 0 ? (
              <details className="portfolio-review-package__details">
                <summary>Что недоступно или опущено</summary>
                <ul>
                  {unavailableOrOmitted.map(([id, section]) => (
                    <li key={id}>
                      <strong>{SECTION_LABELS[id]}</strong>: {STATUS_LABELS[section.status]}
                    </li>
                  ))}
                </ul>
              </details>
            ) : (
              <p className="muted">Все разделы выбранного профиля включены.</p>
            )}

            <div className="portfolio-review-package__downloads">
              <Button
                disabled={preparing || downloading !== null}
                onClick={() => void download("json")}
                variant="primary"
              >
                {downloading === "json" ? "Готовим JSON-пакет…" : "Скачать пакет JSON"}
              </Button>
              <Button
                disabled={preparing || downloading !== null}
                onClick={() => void download("markdown")}
              >
                {downloading === "markdown" ? "Готовим Markdown-пакет…" : "Скачать пакет Markdown"}
              </Button>
            </div>
          </section>
        ) : (
          <p className="muted">Предпросмотр появится после явного нажатия кнопки.</p>
        )}
      </div>
    </Panel>
  );
}
