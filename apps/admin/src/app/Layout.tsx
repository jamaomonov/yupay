/** App-shell: collapsible sidebar + topbar + outlet.
 *
 * - md+: sidebar is a fixed-width column, always visible.
 * - <md: sidebar slides in over the content as a drawer, toggled by the
 *   hamburger button in the topbar. The drawer auto-closes on route change.
 */

import { Button } from "@yupay/ui";
import {
  Activity,
  AlertTriangle,
  Boxes,
  Coins,
  CreditCard,
  Gauge,
  LayoutGrid,
  LogOut,
  Menu,
  Package,
  Radio,
  Receipt,
  Route as RouteIcon,
  Search,
  Settings,
  ShieldCheck,
  Tag,
  Truck,
  Users as UsersIcon,
  Wallet,
  Warehouse,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";


import { ToastRegion } from "@/components/Toast";
import { useAuthStore } from "@/features/auth/authStore";
import { SearchPalette } from "@/features/search/SearchPalette";
import { useGlobalSearchHotkey } from "@/features/search/useGlobalSearchHotkey";
import { SavedSegmentsNav } from "@/features/segments/SavedSegmentsNav";
import { ThemeMenu } from "@/features/theme/ThemeMenu";
import { useSystemThemeSubscription } from "@/features/theme/themeStore";

const NAV: { to: string; label: string; icon: typeof Gauge; end?: boolean }[] = [
  { to: "/", label: "Обзор", icon: Gauge, end: true },
  { to: "/categories", label: "Категории", icon: LayoutGrid },
  { to: "/brands", label: "Бренды", icon: Tag },
  { to: "/products", label: "Продукты", icon: Package },
  { to: "/skus", label: "SKU", icon: Boxes },
  { to: "/inventory", label: "Склад", icon: Warehouse },
  { to: "/sourcing", label: "Sourcing", icon: RouteIcon },
  { to: "/orders", label: "Заказы", icon: Receipt },
  { to: "/payments", label: "Платежи", icon: CreditCard, end: true },
  { to: "/payments/triage", label: "Триаж платежей", icon: AlertTriangle },
  { to: "/webhooks", label: "Webhooks", icon: Radio },
  { to: "/fulfillment", label: "Fulfilment Inbox", icon: Truck },
  { to: "/wallet", label: "Кошелёк", icon: Wallet },
  { to: "/audit", label: "Activity log", icon: Activity, end: true },
  {
    to: "/audit?admin_only=true",
    label: "Действия админов",
    icon: ShieldCheck,
  },
  { to: "/fx", label: "Курсы", icon: Coins },
  { to: "/users", label: "Пользователи", icon: UsersIcon },
  { to: "/settings", label: "Настройки", icon: Settings },
];

export function Layout() {
  const me = useAuthStore((s) => s.me);
  const logout = useAuthStore((s) => s.logout);
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  const openSearch = useCallback(() => { setSearchOpen(true); }, []);
  const closeSearch = useCallback(() => { setSearchOpen(false); }, []);
  useGlobalSearchHotkey(openSearch);
  // Keep `system` mode reactive to OS-level theme flips for the lifetime of the shell.
  useSystemThemeSubscription();

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  // Close the search palette on navigation as well.
  useEffect(() => {
    setSearchOpen(false);
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
      {/* Skip-link — first focusable element on every page, lets keyboard users
          jump past the 17-entry sidebar straight into the content area
          (a11y-audit #13, WCAG 2.4.1). */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:bg-[--accent] focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-[--text-on-accent] focus:shadow-[var(--shadow-md)]"
      >
        Перейти к содержимому
      </a>

      {/* Sidebar: static on md+, off-canvas drawer on <md. */}
      <aside
        aria-label="Основная навигация"
        className={[
          "fixed inset-y-0 left-0 z-40 flex h-screen flex-col border-r border-[--border-default] bg-[--bg-sidebar]",
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
            onClick={() => { setDrawerOpen(false); }}
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
          <SavedSegmentsNav />
        </nav>
        <div className="border-t p-3 text-xs text-[--color-muted]">v0.0.1</div>
      </aside>

      {/* Drawer backdrop (mobile only). */}
      {drawerOpen && (
        <button
          type="button"
          onClick={() => { setDrawerOpen(false); }}
          aria-label="Закрыть меню"
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-[var(--topbar-height)] items-center justify-between border-b bg-[--color-bg] px-4 md:px-6">
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              onClick={() => { setDrawerOpen(true); }}
              className="rounded-md p-1.5 text-[--color-muted] hover:bg-[--color-subtle] md:hidden"
              aria-label="Открыть меню"
            >
              <Menu className="size-5" />
            </button>
            <span className="truncate text-sm text-[--color-muted]">
              {me?.display_name ?? me?.email ?? ""}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={openSearch}
              className="hidden items-center gap-2 rounded-md border border-[--color-border] px-3 py-1.5 text-sm text-[--color-muted] hover:bg-[--color-subtle] sm:flex"
              aria-label="Открыть поиск"
              data-search-trigger
            >
              <Search className="size-4" />
              <span>Поиск</span>
              <kbd className="ml-2 rounded border border-[--color-border] px-1 py-0.5 text-[10px] uppercase">
                ⌘K
              </kbd>
            </button>
            <button
              type="button"
              onClick={openSearch}
              className="rounded-md p-1.5 text-[--color-muted] hover:bg-[--color-subtle] sm:hidden"
              aria-label="Открыть поиск"
            >
              <Search className="size-5" />
            </button>
            <ThemeMenu />
            <Button variant="ghost" size="sm" onClick={logout} aria-label="Выйти">
              <LogOut className="size-4" aria-hidden />
              <span className="hidden sm:inline">Выйти</span>
            </Button>
          </div>
        </header>
        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 overflow-y-auto p-4 md:p-6 focus-visible:outline-none"
        >
          <Outlet />
        </main>
      </div>
      <SearchPalette open={searchOpen} onClose={closeSearch} />
      <ToastRegion />
    </div>
  );
}
