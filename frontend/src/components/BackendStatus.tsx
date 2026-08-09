import { useEffect, useState } from "react";

import { Badge, Panel } from "./ui";

type HealthResponse = {
  status: "ok";
  version: string;
};

type HealthState =
  | { kind: "checking" }
  | { kind: "connected"; version: string }
  | { kind: "unavailable" };

const statusCopy = {
  checking: {
    title: "Проверяем подключение…",
    detail: "Запрашиваем локальный API",
    chip: "Статус",
  },
  unavailable: {
    title: "Сервер недоступен",
    detail: "Запусти API на 127.0.0.1:8000",
    chip: "Офлайн",
  },
} as const;

export function BackendStatus() {
  const [state, setState] = useState<HealthState>({ kind: "checking" });

  useEffect(() => {
    const controller = new AbortController();

    async function checkBackend() {
      try {
        const response = await fetch("/api/health", {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Health check failed with status ${response.status}`);
        }

        const health = (await response.json()) as HealthResponse;
        if (health.status !== "ok") {
          throw new Error("Backend returned an invalid health status");
        }

        setState({ kind: "connected", version: health.version });
      } catch {
        if (!controller.signal.aborted) {
          setState({ kind: "unavailable" });
        }
      }
    }

    void checkBackend();

    return () => controller.abort();
  }, []);

  const copy =
    state.kind === "connected"
      ? {
          title: "Сервер подключён",
          detail: `API v${state.version}`,
          chip: "Онлайн",
        }
      : statusCopy[state.kind];

  return (
    <Panel
      action={<span className={`status-chip status-chip--${state.kind}`}>{copy.chip}</span>}
      label="Состояние системы"
      title="Локальный API"
      titleId="backend-status-title"
    >
      <div aria-live="polite" className="status-line" role="status">
        <span aria-hidden="true" className={`status-line__dot status-line__dot--${state.kind}`} />
        <span className="status-line__copy">
          <strong>{copy.title}</strong>
          <span>{copy.detail}</span>
        </span>
      </div>
      {state.kind === "connected" ? (
        <p className="muted" style={{ margin: "14px 0 0", fontSize: "0.8rem" }}>
          Health-check через Vite proxy → <Badge tone="info">/api/health</Badge>
        </p>
      ) : null}
    </Panel>
  );
}
