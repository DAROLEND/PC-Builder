import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { Empty, RequireAuth } from "./components/ui";
import { useI18n } from "./i18n/context";
import { AdvisorPage } from "./pages/AdvisorPage";
import { LoginPage, RegisterPage } from "./pages/AuthPages";
import { BuildDetailPage } from "./pages/BuildDetailPage";
import { BuildsPage } from "./pages/BuildsPage";
import { CatalogPage } from "./pages/CatalogPage";
import { ComponentDetailPage } from "./pages/ComponentDetailPage";
import { ConfiguratorPage } from "./pages/ConfiguratorPage";
import { HomePage } from "./pages/HomePage";
import { OrderDetailPage, OrdersPage } from "./pages/OrdersPage";
import { ProfilePage } from "./pages/ProfilePage";
import { StatsPage } from "./pages/StatsPage";

function NotFound() {
  const { t } = useI18n();
  return <Empty>{t("common.notFound")}</Empty>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="catalog/:slug" element={<ComponentDetailPage />} />
        <Route path="configurator" element={<ConfiguratorPage />} />
        <Route
          path="configurator/:id"
          element={
            <RequireAuth>
              <ConfiguratorPage />
            </RequireAuth>
          }
        />
        <Route path="builds" element={<BuildsPage />} />
        <Route path="builds/:id" element={<BuildDetailPage />} />
        <Route
          path="advisor"
          element={
            <RequireAuth>
              <AdvisorPage />
            </RequireAuth>
          }
        />
        <Route path="stats" element={<StatsPage />} />
        <Route
          path="orders"
          element={
            <RequireAuth>
              <OrdersPage />
            </RequireAuth>
          }
        />
        <Route
          path="orders/:id"
          element={
            <RequireAuth>
              <OrderDetailPage />
            </RequireAuth>
          }
        />
        <Route
          path="profile"
          element={
            <RequireAuth>
              <ProfilePage />
            </RequireAuth>
          }
        />
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
