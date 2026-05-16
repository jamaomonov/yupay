/** Top-level route table for the admin SPA. */

import { createBrowserRouter, Navigate } from "react-router-dom";

import { AuthGuard } from "@/features/auth/AuthGuard";
import { LoginPage } from "@/features/auth/LoginPage";
import { BrandsListPage } from "@/features/catalog/brands/BrandsListPage";
import { BrandEditPage } from "@/features/catalog/brands/BrandEditPage";
import { CategoriesListPage } from "@/features/catalog/categories/CategoriesListPage";
import { ProductsListPage } from "@/features/catalog/products/ProductsListPage";
import { ProductEditPage } from "@/features/catalog/products/ProductEditPage";
import { SkusListPage } from "@/features/catalog/skus/SkusListPage";
import { FulfillmentPage } from "@/features/fulfillment/FulfillmentPage";
import { InventoryPage } from "@/features/inventory/InventoryPage";
import { PaymentsPage } from "@/features/payments/PaymentsPage";
import { SourcingPage } from "@/features/sourcing/SourcingPage";
import { WalletPage } from "@/features/wallet/WalletPage";
import { DashboardPage } from "@/routes/Dashboard";

import { Layout } from "./Layout";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <AuthGuard />,
    children: [
      {
        element: <Layout />,
        children: [
          { path: "/", element: <DashboardPage /> },
          { path: "/categories", element: <CategoriesListPage /> },
          { path: "/brands", element: <BrandsListPage /> },
          { path: "/brands/new", element: <BrandEditPage /> },
          { path: "/brands/:id", element: <BrandEditPage /> },
          { path: "/products", element: <ProductsListPage /> },
          { path: "/products/new", element: <ProductEditPage /> },
          { path: "/products/:id", element: <ProductEditPage /> },
          { path: "/skus", element: <SkusListPage /> },
          { path: "/inventory", element: <InventoryPage /> },
          { path: "/sourcing", element: <SourcingPage /> },
          { path: "/payments", element: <PaymentsPage /> },
          { path: "/fulfillment", element: <FulfillmentPage /> },
          { path: "/wallet", element: <WalletPage /> },
          { path: "/fx", element: <FxStub /> },
          { path: "/users", element: <UsersStub /> },
          { path: "/settings", element: <SettingsStub /> },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);

function FxStub() {
  return (
    <Stub
      title="Курсы"
      hint="Здесь будет таблица FX-кэша + кнопка форс-рефреша."
    />
  );
}
function UsersStub() {
  return <Stub title="Пользователи" hint="Список юзеров, грант ролей, soft-delete." />;
}
function SettingsStub() {
  return <Stub title="Настройки" hint="Feature-flags, поставщики, секреты." />;
}

function Stub({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="text-sm text-[--color-muted]">{hint}</p>
    </div>
  );
}
