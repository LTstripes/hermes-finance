import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import "./styles/global.css";
import "./styles/ui-primitives.css";
import "./styles/app-shell-v03.css";
import "./styles/broker-snapshot.css";
import "./styles/goals-v03.css";
import "./styles/month-edit-support.css";
import "./styles/analytics-v03.css";
import "./styles/scenario-lab.css";
import "./styles/portfolio-review-package.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Root element not found");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
