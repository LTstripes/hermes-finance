import { useEffect, useState } from "react";

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
  },
  unavailable: {
    title: "Backend недоступен",
    detail: "Запусти API на 127.0.0.1:8000",
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
      ? { title: "Backend подключён", detail: `API v${state.version}` }
      : statusCopy[state.kind];

  return (
    <section
      aria-labelledby="backend-status-title"
      className="panel status-panel"
    >
      <div className="panel__heading">
        <div>
          <p className="panel__label">Состояние системы</p>
          <h2 id="backend-status-title">Локальный API</h2>
        </div>
        <span className={`status-chip status-chip--${state.kind}`}>
          {state.kind === "connected" ? "Онлайн" : "Статус"}
        </span>
      </div>

      <div aria-live="polite" className="status-line" role="status">
        <span
          aria-hidden="true"
          className={`status-line__dot status-line__dot--${state.kind}`}
        />
        <span className="status-line__copy">
          <strong>{copy.title}</strong>
          <span>{copy.detail}</span>
        </span>
      </div>
    </section>
  );
}
