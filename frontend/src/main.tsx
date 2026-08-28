import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import "./styles/global.css";
import "./styles/sticky-sidebar.css";
import "./styles/ui-primitives.css";
import "./styles/app-shell-v03.css";
import "./styles/dashboard-v03.css";
import "./styles/fact-forecast-goal-v03.css";
import "./styles/goals-v03.css";
import "./styles/month-workspace-v03.css";
import "./styles/analytics-v03.css";
import "./styles/risk-allocation.css";
import "./styles/tax-iis-planner.css";
import "./styles/reconciliation-center.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Root element not found");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
