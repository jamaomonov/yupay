/** Top-level route table for the admin SPA. */

import { createBrowserRouter, Navigate } from "react-router-dom";

import { AuthGuard } from "@/features/auth/AuthGuard";
import { LoginPage } from "@/features/auth/LoginPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { BrandsListPage } from "@/features/catalog/brands/BrandsListPage";
import { BrandEditPage } from "@/features/catalog/brands/BrandEditPage";
import { CategoriesListPage } from "@/features/catalog/categories/CategoriesListPage";
import { CategoryEditPage } from "@/features/catalog/categories/CategoryEditPage";
import { ProductsListPage } from "@/features/catalog/products/ProductsListPage";
import { ProductEditPage } from "@/features/catalog/products/ProductEditPage";
import { SkuEditPage } from "@/features/catalog/skus/SkuEditPage";
import { SkusListPage } from "@/features/catalog/skus/SkusListPage";
import { FulfillmentPage } from "@/features/fulfillment/FulfillmentPage";
import { FxPage } from "@/features/fx/FxPage";
import { InventoryPage } from "@/features/inventory/InventoryPage";
import { OrderDetailPage } from "@/features/orders/OrderDetailPage";
import { OrdersListPage } from "@/features/orders/OrdersListPage";
import { PaymentsPage } from "@/features/payments/PaymentsPage";
import { SourcingPage } from "@/features/sourcing/SourcingPage";
import { UsersListPage } from "@/features/users/UsersListPage";
import { WalletPage } from "@/features/wallet/WalletPage";
import { WebhooksPage } from "@/features/webhooks/WebhooksPage";
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
          { path: "/categories/new", element: <CategoryEditPage /> },
          { path: "/categories/:id", element: <CategoryEditPage /> },
          { path: "/brands", element: <BrandsListPage /> },
          { path: "/brands/new", element: <BrandEditPage /> },
          { path: "/brands/:id", element: <BrandEditPage /> },
          { path: "/products", element: <ProductsListPage /> },
          { path: "/products/new", element: <ProductEditPage /> },
          { path: "/products/:id", element: <ProductEditPage /> },
          { path: "/skus", element: <SkusListPage /> },
          { path: "/skus/new", element: <SkuEditPage /> },
          { path: "/skus/:id", element: <SkuEditPage /> },
          { path: "/inventory", element: <InventoryPage /> },
          { path: "/sourcing", element: <SourcingPage /> },
          { path: "/orders", element: <OrdersListPage /> },
          { path: "/orders/:id", element: <OrderDetailPage /> },
          { path: "/payments", element: <PaymentsPage /> },
          { path: "/webhooks", element: <WebhooksPage /> },
          { path: "/fulfillment", element: <FulfillmentPage /> },
          { path: "/wallet", element: <WalletPage /> },
          { path: "/audit", element: <AuditPage /> },
          { path: "/fx", element: <FxPage /> },
          { path: "/users", element: <UsersListPage /> },
          { path: "/settings", element: <SettingsStub /> },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);

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
