import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { CalendarPage } from "./pages/CalendarPage";
import { ChatWidgetPage } from "./pages/ChatWidgetPage";
import { InboxPage } from "./pages/InboxPage";
import { LoginPage } from "./pages/LoginPage";
import { ProspectDetailPage } from "./pages/ProspectDetailPage";
import { ProspectsPage } from "./pages/ProspectsPage";
import { UnitsPage } from "./pages/UnitsPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/chat/:propertyId" element={<ChatWidgetPage />} />
      <Route element={<Layout />}>
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/prospects" element={<ProspectsPage />} />
        <Route path="/prospects/:id" element={<ProspectDetailPage />} />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/units" element={<UnitsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/inbox" replace />} />
    </Routes>
  );
}
