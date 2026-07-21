/** Top-level route table for the admin SPA. */

import { createBrowserRouter, Navigate } from "react-router-dom";

import { Layout } from "./Layout";

import { AnalyticsPage } from "@/features/analytics/AnalyticsPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { AuthGuard } from "@/features/auth/AuthGuard";
import { LoginPage } from "@/features/auth/LoginPage";
import { BroadcastComposerPage } from "@/features/broadcasts/BroadcastComposerPage";
import { BroadcastDetailPage } from "@/features/broadcasts/BroadcastDetailPage";
import { BroadcastsListPage } from "@/features/broadcasts/BroadcastsListPage";
import { BrandEditPage } from "@/features/catalog/brands/BrandEditPage";
import { BrandFaqsPage } from "@/features/catalog/brands/BrandFaqsPage";
import { BrandsListPage } from "@/features/catalog/brands/BrandsListPage";
import { CategoriesListPage } from "@/features/catalog/categories/CategoriesListPage";
import { CategoryEditPage } from "@/features/catalog/categories/CategoryEditPage";
import { ProductEditPage } from "@/features/catalog/products/ProductEditPage";
import { ProductsListPage } from "@/features/catalog/products/ProductsListPage";
import { SkuEditPage } from "@/features/catalog/skus/SkuEditPage";
import { SkusListPage } from "@/features/catalog/skus/SkusListPage";
import { CustomerPage } from "@/features/customers/CustomerPage";
import { InboxPage } from "@/features/fulfillment/InboxPage";
import { FxPage } from "@/features/fx/FxPage";
import { G2bDetailPage } from "@/features/integrations/G2bDetailPage";
import { GameImportPage } from "@/features/integrations/GameImportPage";
import { IntegrationsPage } from "@/features/integrations/IntegrationsPage";
import { MappingEditPage } from "@/features/integrations/MappingEditPage";
import { MappingsPage } from "@/features/integrations/MappingsPage";
import { SupplierCatalogPage } from "@/features/integrations/SupplierCatalogPage";
import { InventoryPage } from "@/features/inventory/InventoryPage";
import { OrderDetailPage } from "@/features/orders/OrderDetailPage";
import { OrdersListPage } from "@/features/orders/OrdersListPage";
import { PaymentsPage } from "@/features/payments/PaymentsPage";
import { TriagePage } from "@/features/payments-triage/TriagePage";
import { PromoPage } from "@/features/promo/PromoPage";
import { SourcingPage } from "@/features/sourcing/SourcingPage";
import { UsersListPage } from "@/features/users/UsersListPage";
import { WalletPage } from "@/features/wallet/WalletPage";
import { WebhooksPage } from "@/features/webhooks/WebhooksPage";
import { DashboardPage } from "@/routes/Dashboard";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <AuthGuard />,
    children: [
      {
        element: <Layout />,
        children: [
          { path: "/", element: <DashboardPage /> },
          { path: "/analytics", element: <AnalyticsPage /> },
          { path: "/categories", element: <CategoriesListPage /> },
          { path: "/categories/new", element: <CategoryEditPage /> },
          { path: "/categories/:id", element: <CategoryEditPage /> },
          { path: "/brands", element: <BrandsListPage /> },
          { path: "/brands/new", element: <BrandEditPage /> },
          { path: "/brands/:id", element: <BrandEditPage /> },
          { path: "/brands/:id/faqs", element: <BrandFaqsPage /> },
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
          { path: "/payments/triage", element: <TriagePage /> },
          { path: "/webhooks", element: <WebhooksPage /> },
          { path: "/fulfillment", element: <InboxPage /> },
          {
            path: "/manual-fulfillment",
            element: <Navigate to="/fulfillment?tab=manual" replace />,
          },
          { path: "/wallet", element: <WalletPage /> },
          { path: "/audit", element: <AuditPage /> },
          { path: "/fx", element: <FxPage /> },
          { path: "/promo", element: <PromoPage /> },
          { path: "/broadcasts", element: <BroadcastsListPage /> },
          { path: "/broadcasts/new", element: <BroadcastComposerPage /> },
          { path: "/broadcasts/:id/edit", element: <BroadcastComposerPage /> },
          { path: "/broadcasts/:id", element: <BroadcastDetailPage /> },
          { path: "/users", element: <UsersListPage /> },
          { path: "/customers/:id", element: <CustomerPage /> },
          { path: "/integrations", element: <IntegrationsPage /> },
          { path: "/integrations/mappings", element: <MappingsPage /> },
          { path: "/integrations/mappings/new", element: <MappingEditPage /> },
          {
            path: "/integrations/mappings/:supplier/:sku/edit",
            element: <MappingEditPage />,
          },
          { path: "/integrations/:slug/catalog", element: <SupplierCatalogPage /> },
          { path: "/integrations/:slug/catalog/:gameCode", element: <GameImportPage /> },
          { path: "/integrations/:slug", element: <G2bDetailPage /> },
          // Legacy stub route — operators may still have bookmarks.
          { path: "/settings", element: <Navigate to="/integrations" replace /> },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);
