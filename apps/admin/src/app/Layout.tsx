/** App-shell: collapsible sidebar + topbar + outlet.
 *
 * - md+: sidebar is a fixed-width column, always visible.
 * - <md: sidebar slides in over the content as a drawer, toggled by the
 *   hamburger button in the topbar. The drawer auto-closes on route change.
 */

import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  Boxes,
  Coins,
  CreditCard,
  Gauge,
  Hand,
  LayoutGrid,
  LogOut,
  Menu,
  Package,
  Radio,
  Receipt,
  Route as RouteIcon,
  Settings,
  ShieldCheck,
  Tag,
  Truck,
  Users as UsersIcon,
  Wallet,
  Warehouse,
  X,
} from "lucide-react";

import { Button } from "@yupay/ui";

import { useAuthStore } from "@/features/auth/authStore";

const NAV: { to: string; label: string; icon: typeof Gauge; end?: boolean }[] = [
  { to: "/", label: "Обзор", icon: Gauge, end: true },
  { to: "/categories", label: "Категории", icon: LayoutGrid },
  { to: "/brands", label: "Бренды", icon: Tag },
  { to: "/products", label: "Продукты", icon: Package },
  { to: "/skus", label: "SKU", icon: Boxes },
  { to: "/inventory", label: "Склад", icon: Warehouse },
  { to: "/sourcing", label: "Sourcing", icon: RouteIcon },
  { to: "/orders", label: "Заказы", icon: Receipt },
  { to: "/payments", label: "Платежи", icon: CreditCard },
  { to: "/webhooks", label: "Webhooks", icon: Radio },
  { to: "/fulfillment", label: "Fulfilment", icon: Truck },
  { to: "/manual-fulfillment", label: "Ручная выдача", icon: Hand },
  { to: "/wallet", label: "Кошелёк", icon: Wallet },
  { to: "/audit", label: "Activity log", icon: Activity },
  { to: "/fx", label: "Курсы", icon: Coins },
  { to: "/users", label: "Пользователи", icon: UsersIcon },
  { to: "/settings", label: "Настройки", icon: Settings },
];

export function Layout() {
  const me = useAuthStore((s) => s.me);
  const logout = useAuthStore((s) => s.logout);
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  // Keep body from scrolling under the drawer on small screens.
  useEffect(() => {
    if (drawerOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [drawerOpen]);

  return (
    <div className="flex min-h-screen">
      {/* Sidebar: static on md+, off-canvas drawer on <md. */}
      <aside
        className={[
          "fixed inset-y-0 left-0 z-40 flex h-screen flex-col border-r bg-[--color-bg]",
          "transition-transform duration-200 ease-out",
          "md:static md:translate-x-0",
          drawerOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
        ].join(" ")}
        style={{ width: "var(--sidebar-width)" }}
      >
        <div className="flex h-[var(--topbar-height)] items-center justify-between gap-2 border-b px-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="size-5 text-[--color-brand]" />
            <span className="text-lg font-semibold">YuPay Admin</span>
          </div>
          <button
            type="button"
            onClick={() => setDrawerOpen(false)}
            className="md:hidden rounded-md p-1 text-[--color-muted] hover:bg-[--color-subtle]"
            aria-label="Закрыть меню"
          >
            <X className="size-4" />
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto p-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end ?? false}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-[--color-subtle] text-[--color-fg]"
                    : "text-[--color-muted] hover:bg-[--color-subtle]/60 hover:text-[--color-fg]",
                ].join(" ")
              }
            >
              <item.icon className="size-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t p-3 text-xs text-[--color-muted]">v0.0.1</div>
      </aside>

      {/* Drawer backdrop (mobile only). */}
      {drawerOpen && (
        <button
          type="button"
          onClick={() => setDrawerOpen(false)}
          aria-label="Закрыть меню"
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-[var(--topbar-height)] items-center justify-between border-b bg-[--color-bg] px-4 md:px-6">
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              className="rounded-md p-1.5 text-[--color-muted] hover:bg-[--color-subtle] md:hidden"
              aria-label="Открыть меню"
            >
              <Menu className="size-5" />
            </button>
            <span className="truncate text-sm text-[--color-muted]">
              {me?.display_name ?? me?.email ?? ""}
            </span>
          </div>
          <Button variant="ghost" size="sm" onClick={logout}>
            <LogOut className="size-4" />
            <span className="hidden sm:inline">Выйти</span>
          </Button>
        </header>
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
