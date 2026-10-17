import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { InstrumentUatPage } from "./ui-v2/InstrumentUatPage";
import "./styles/global.css";
import "./styles/ui-primitives.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element not found");
const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
createRoot(root).render(
  <QueryClientProvider client={client}>
    <InstrumentUatPage />
  </QueryClientProvider>,
);
