import "@testing-library/jest-dom/vitest";
import { createElement } from "react";
import { Link } from "react-router";
import { vi } from "vitest";

// Page tests pin their exact request lists, so the shell plate does not add its
// own read there. UiV2Shell.test.tsx unmocks it and covers the real component.
vi.mock("../ui-v2/UiV2MonthPlate", () => ({
  UiV2MonthPlate: () => createElement(Link, { to: "/v2/close" }, "Месяц"),
}));
