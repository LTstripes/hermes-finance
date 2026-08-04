import { BrowserRouter, Route, Routes } from "react-router";

import { AppLayout } from "../components/AppLayout";
import { DashboardPage } from "../pages/DashboardPage";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
