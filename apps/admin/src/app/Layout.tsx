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

interface NavItem {
  to: string;
  label: string;
  icon: typeof Gauge;
  end?: boolean;
}
interface NavGroup {
  /** Section header label. `null` = pinned items rendered without a heading. */
  label: string | null;
  items: NavItem[];
}

/**
 * Sidebar layout — 18 entries packed into 6 semantic groups so the operator
 * doesn't scan through a flat list. The "Главное" group at the top stays
 * unlabelled and houses the dashboard pin.
 */
const NAV_GROUPS: NavGroup[] = [
  {
    label: null,
    items: [{ to: "/", label: "Обзор", icon: Gauge, end: true }],
  },
  {
    label: "Каталог",
    items: [
      { to: "/categories", label: "Категории", icon: LayoutGrid },
      { to: "/brands", label: "Бренды", icon: Tag },
      { to: "/products", label: "Продукты", icon: Package },
      { to: "/skus", label: "SKU", icon: Boxes },
    ],
  },
  {
    label: "Операции",
    items: [
      { to: "/orders", label: "Заказы", icon: Receipt },
      { to: "/payments", label: "Платежи", icon: CreditCard, end: true },
      { to: "/payments/triage", label: "Триаж платежей", icon: AlertTriangle },
      { to: "/webhooks", label: "Webhooks", icon: Radio },
      { to: "/fulfillment", label: "Fulfilment Inbox", icon: Truck },
    ],
  },
  {
    label: "Поддержка",
    items: [
      { to: "/users", label: "Пользователи", icon: UsersIcon },
      { to: "/wallet", label: "Кошелёк", icon: Wallet },
    ],
  },
  {
    label: "Аудит",
    items: [
      { to: "/audit", label: "Activity log", icon: Activity, end: true },
      { to: "/audit?admin_only=true", label: "Действия админов", icon: ShieldCheck },
    ],
  },
  {
    label: "Системное",
    items: [
      { to: "/inventory", label: "Склад", icon: Warehouse },
      { to: "/sourcing", label: "Sourcing", icon: RouteIcon },
      { to: "/fx", label: "Курсы", icon: Coins },
      { to: "/settings", label: "Настройки", icon: Settings },
    ],
  },
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
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:bg-[var(--accent)] focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-[var(--text-on-accent)] focus:shadow-[var(--shadow-md)]"
      >
        Перейти к содержимому
      </a>

      {/* Sidebar: static on md+, off-canvas drawer on <md. */}
      <aside
        aria-label="Основная навигация"
        className={[
          "fixed inset-y-0 left-0 z-40 flex h-screen flex-col border-r border-[var(--border-default)] bg-[var(--bg-sidebar)]",
          "transition-transform duration-200 ease-out",
          "md:static md:translate-x-0",
          drawerOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
        ].join(" ")}
        style={{ width: "var(--sidebar-width)" }}
      >
        <div className="flex h-[var(--topbar-height)] items-center justify-between gap-2 border-b px-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="size-5 text-[var(--accent)]" />
            <span className="text-lg font-semibold">YuPay Admin</span>
          </div>
          <button
            type="button"
            onClick={() => { setDrawerOpen(false); }}
            className="md:hidden rounded-md p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-muted)]"
            aria-label="Закрыть меню"
          >
            <X className="size-4" />
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto p-3">
          {NAV_GROUPS.map((group, idx) => (
            <div
              key={group.label ?? `pinned-${idx.toString()}`}
              className={idx > 0 ? "mt-3 border-t border-[var(--border-subtle)] pt-3" : ""}
            >
              {group.label && (
                <p className="mb-1 px-3 text-[10px] font-medium uppercase tracking-wider text-[var(--text-tertiary)]">
                  {group.label}
                </p>
              )}
              {group.items.map((item) => (
                // Active item gets the indigo accent-soft pair so the operator can
                // see at a glance where they are — neutral subtle on hover stays
                // distinct so it isn't mistaken for the active marker.
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end ?? false}
                  className={({ isActive }) =>
                    [
                      "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                      isActive
                        ? "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]"
                        : "text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] hover:text-[var(--text-primary)]",
                    ].join(" ")
                  }
                >
                  <item.icon className="size-4" aria-hidden />
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
          <SavedSegmentsNav />
        </nav>
        <div className="border-t p-3 text-xs text-[var(--text-secondary)]">v0.0.1</div>
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
        <header className="sticky top-0 z-20 flex h-[var(--topbar-height)] items-center justify-between border-b bg-[var(--bg-surface)] px-4 md:px-6">
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              onClick={() => { setDrawerOpen(true); }}
              className="rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] md:hidden"
              aria-label="Открыть меню"
            >
              <Menu className="size-5" />
            </button>
            <span className="truncate text-sm text-[var(--text-secondary)]">
              {me?.display_name ?? me?.email ?? ""}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={openSearch}
              className="hidden items-center gap-2 rounded-md border border-[var(--border-default)] px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] sm:flex"
              aria-label="Открыть поиск"
              data-search-trigger
            >
              <Search className="size-4" />
              <span>Поиск</span>
              <kbd className="ml-2 rounded border border-[var(--border-default)] px-1 py-0.5 text-[10px] uppercase">
                ⌘K
              </kbd>
            </button>
            <button
              type="button"
              onClick={openSearch}
              className="rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] sm:hidden"
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
