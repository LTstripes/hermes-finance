import type { ApiErrorBody, ApiErrorResponse } from "./types";

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorBody["details"];

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? [];
  }
}

function isApiErrorResponse(value: unknown): value is ApiErrorResponse {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const error = (value as ApiErrorResponse).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof error.code === "string" &&
    typeof error.message === "string"
  );
}

async function parseJsonSafe(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

export type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  signal?: AbortSignal;
};

export type ApiDownload = {
  blob: Blob;
  filename: string;
};

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { body, headers, signal, ...rest } = options;
  const init: RequestInit = {
    ...rest,
    signal,
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (cause) {
    throw new ApiClientError(0, {
      code: "network_error",
      message: cause instanceof Error ? cause.message : "Network request failed",
      details: [],
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const payload = await parseJsonSafe(response);

  if (!response.ok) {
    if (isApiErrorResponse(payload)) {
      throw new ApiClientError(response.status, {
        code: payload.error.code,
        message: payload.error.message,
        details: Array.isArray(payload.error.details) ? payload.error.details : [],
      });
    }
    throw new ApiClientError(response.status, {
      code: "http_error",
      message: `Request failed with status ${response.status}`,
      details: [],
    });
  }

  return payload as T;
}

function filenameFromContentDisposition(value: string | null): string | null {
  const match = value?.match(/filename="([^"]+)"/i);
  return match?.[1] ?? null;
}

export async function apiDownload(
  path: string,
  options: Omit<RequestInit, "body"> = {},
): Promise<ApiDownload> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...options,
      headers: {
        Accept: "application/octet-stream",
        ...options.headers,
      },
    });
  } catch (cause) {
    throw new ApiClientError(0, {
      code: "network_error",
      message: cause instanceof Error ? cause.message : "Network request failed",
      details: [],
    });
  }

  if (!response.ok) {
    const payload = await parseJsonSafe(response);
    if (isApiErrorResponse(payload)) {
      throw new ApiClientError(response.status, {
        code: payload.error.code,
        message: payload.error.message,
        details: Array.isArray(payload.error.details) ? payload.error.details : [],
      });
    }
    throw new ApiClientError(response.status, {
      code: "http_error",
      message: `Request failed with status ${response.status}`,
      details: [],
    });
  }

  return {
    blob: await response.blob(),
    filename:
      filenameFromContentDisposition(response.headers.get("Content-Disposition")) ?? "export",
  };
}

const FIELD_LABELS: Record<string, string> = {
  year: "Год",
  month: "Месяц",
  snapshot_date: "Дата снимка",
  locale: "Локаль",
  timezone: "Часовой пояс",
  name: "Название",
  target_value: "Целевое значение",
  target_date: "Срок",
  closed_month: "Закрытый месяц",
  provider: "Провайдер",
  engine: "Движок",
  market: "Рынок",
  boardid: "Режим торгов",
  secid: "Код бумаги",
  provider_instrument_id: "Код бумаги",
  provider_venue_id: "Площадка",
};

const MONTH_NAMES = [
  "январь",
  "февраль",
  "март",
  "апрель",
  "май",
  "июнь",
  "июль",
  "август",
  "сентябрь",
  "октябрь",
  "ноябрь",
  "декабрь",
] as const;

function localizeMonthCode(value: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(value.trim());
  if (!match) return value.trim();
  const monthIndex = Number(match[2]) - 1;
  const monthName = MONTH_NAMES[monthIndex];
  return monthName ? `${monthName} ${match[1]}` : value.trim();
}

function salaryTaxHistoryMessage(message: string): string {
  const missing = /missing known month\(s\):\s*(.+)$/i.exec(message)?.[1];
  const months = missing?.split(",").map(localizeMonthCode).filter(Boolean);
  const suffix = months && months.length > 0 ? ` Не хватает данных за: ${months.join(", ")}.` : "";
  return `Не хватает истории для расчёта НДФЛ. Закрой предыдущие отчётные месяцы или задай начальный налоговый контекст.${suffix}`;
}

function isAsciiOnly(value: string): boolean {
  return Array.from(value).every((character) => character.charCodeAt(0) <= 127);
}

function localizeValidationMessage(message: string): string {
  if (/^Field required$/i.test(message)) return "Обязательное поле";
  const max = /^Input should be less than or equal to (.+)$/i.exec(message)?.[1];
  if (max) return `Значение должно быть не больше ${max}`;
  const min = /^Input should be greater than or equal to (.+)$/i.exec(message)?.[1];
  if (min) return `Значение должно быть не меньше ${min}`;
  if (isAsciiOnly(message)) return "Некорректное значение";
  return message;
}

function localizeApiMessage(error: ApiClientError): string {
  switch (error.code) {
    case "salary_tax_history_incomplete":
      return salaryTaxHistoryMessage(error.message);
    case "tax_brackets_year_locked":
      return "Налоговые ступени этого года зафиксированы закрытыми отчётными месяцами. Сначала открой их, если действительно хочешь пересчитать историю.";
    case "network_error":
      return "Не удалось подключиться к локальному приложению. Проверь, что Hermes Finance запущен.";
    case "http_error":
      return "Не удалось выполнить запрос к локальному приложению.";
    case "internal_error":
      return "Внутренняя ошибка приложения. Попробуй обновить данные.";
    case "not_found":
      return "Запрошенные данные не найдены.";
    case "preview_changed":
      return "Котировка изменилась после предпросмотра. Обнови предпросмотр и выбери строки заново.";
    case "payout_mapping_required":
      return "Для выбранного инструмента нет принятого источника T-Invest. Сохрани сопоставление в справочнике инструментов — после этого можно проверять автоматические выплаты.";
    case "conflict":
      return "Операцию нельзя выполнить в текущем состоянии данных.";
    case "unprocessable":
    case "validation_error":
      return "Проверь введённые данные.";
    default:
      return error.message;
  }
}

export function formatApiError(error: unknown): string {
  if (error instanceof ApiClientError) {
    const message = localizeApiMessage(error);
    if (error.details.length > 0) {
      const fields = error.details
        .map((detail) => {
          const field = FIELD_LABELS[detail.field] ?? detail.field;
          const detailMessage =
            detail.field === "closed_month"
              ? localizeMonthCode(detail.message)
              : localizeValidationMessage(detail.message);
          return `${field}: ${detailMessage}`;
        })
        .join("; ");
      return `${message} (${fields})`;
    }
    return message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Неизвестная ошибка";
}
