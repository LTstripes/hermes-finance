import { useEffect, useState } from "react";

import { Panel } from "./ui";

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
    detail: "Связываемся с локальным приложением",
    chip: "Статус",
  },
  unavailable: {
    title: "Приложение недоступно",
    detail: "Запусти Hermes Finance и обнови страницу",
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
          title: "Приложение работает",
          detail: `Версия ${state.version}`,
          chip: "Онлайн",
        }
      : statusCopy[state.kind];

  return (
    <Panel
      action={<span className={`status-chip status-chip--${state.kind}`}>{copy.chip}</span>}
      label="Состояние системы"
      title="Локальное приложение"
      titleId="backend-status-title"
    >
      <div aria-live="polite" className="status-line" role="status">
        <span aria-hidden="true" className={`status-line__dot status-line__dot--${state.kind}`} />
        <span className="status-line__copy">
          <strong>{copy.title}</strong>
          <span>{copy.detail}</span>
        </span>
      </div>
    </Panel>
  );
}
