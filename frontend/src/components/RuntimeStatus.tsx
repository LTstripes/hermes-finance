import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";

import { getHealth } from "../api/health";
import { Badge, Button, DataValue, Panel } from "./ui";

type RuntimeState =
  | { kind: "checking" }
  | { kind: "connected"; version: string }
  | { kind: "unavailable" };

function useRuntimeHealth(): [RuntimeState, () => void] {
  const [state, setState] = useState<RuntimeState>({ kind: "checking" });
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "checking" });
    void getHealth(controller.signal)
      .then((health) => {
        if (!controller.signal.aborted) {
          setState({ kind: "connected", version: health.version });
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setState({ kind: "unavailable" });
        }
      });
    return () => controller.abort();
  }, [attempt]);

  return [state, retry];
}

export function RuntimeStatusBanner() {
  const [state] = useRuntimeHealth();

  if (state.kind === "checking") return null;

  if (state.kind === "connected") {
    return (
      <span className="sr-only" role="status">
        Сервер подключён · API v{state.version}
      </span>
    );
  }

  return (
    <div className="runtime-alert" role="alert">
      <div className="runtime-alert__inner">
        <span aria-hidden="true" className="runtime-alert__dot" />
        <div>
          <strong>Сервер недоступен</strong>
          <span>Проверь запуск Hermes Finance или открой диагностику.</span>
        </div>
        <Link className="runtime-alert__link" to="/settings#diagnostics">
          Диагностика →
        </Link>
      </div>
    </div>
  );
}

export function DiagnosticsPanel() {
  const [state, retry] = useRuntimeHealth();
  const connected = state.kind === "connected";

  return (
    <Panel
      action={
        <Badge
          className={state.kind === "unavailable" ? "diagnostics-badge--error" : ""}
          tone={connected ? "ok" : "neutral"}
        >
          {connected ? "Работает" : state.kind === "checking" ? "Проверяем" : "Недоступно"}
        </Badge>
      }
      label="Диагностика"
      title="Локальное приложение"
    >
      <div className="diagnostics-grid">
        <DataValue
          label="Версия"
          value={
            state.kind === "connected" ? state.version : state.kind === "checking" ? "…" : "—"
          }
        />
        <DataValue label="Адрес" value="127.0.0.1:8000" />
        <DataValue label="Режим" value="Только локально" />
      </div>
      <div className="diagnostics-actions">
        <p className="muted">
          Состояние системы и технические параметры собраны здесь, чтобы не занимать место на
          основном дашборде.
        </p>
        <Button onClick={retry} size="sm" type="button" variant="secondary">
          Проверить снова
        </Button>
      </div>
    </Panel>
  );
}
