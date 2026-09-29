import { QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router";

import { createQueryClient } from "../../src/queryClient";
import UiV2CapitalAllocationPage from "../../src/ui-v2/UiV2CapitalAllocationPage";
import "../../src/styles/global.css";
import "../../src/styles/ui-primitives.css";

const root = document.getElementById("root");
if (!root) throw new Error("Preview root missing");

createRoot(root).render(
  <QueryClientProvider client={createQueryClient()}>
    <MemoryRouter initialEntries={[`/v2/capital/allocation${window.location.search}`]}>
      <Routes>
        <Route path="v2/capital/allocation" element={<UiV2CapitalAllocationPage />} />
      </Routes>
    </MemoryRouter>
  </QueryClientProvider>,
);
