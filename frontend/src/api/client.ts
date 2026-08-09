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

/**
 * Fetch wrapper for `/api/*` via Vite proxy.
 * Parses D08 error shape into ApiClientError; 204 returns undefined.
 */
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

export function formatApiError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.details.length > 0) {
      const fields = error.details.map((d) => `${d.field}: ${d.message}`).join("; ");
      return `${error.message} (${fields})`;
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Неизвестная ошибка";
}
