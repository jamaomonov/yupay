/** App-shell: sidebar + topbar + outlet. */

import { NavLink, Outlet } from "react-router-dom";
import {
  Boxes,
  Coins,
  CreditCard,
  Gauge,
  LayoutGrid,
  LogOut,
  Package,
  Receipt,
  Route as RouteIcon,
  Settings,
  ShieldCheck,
  Tag,
  Truck,
  Users as UsersIcon,
  Wallet,
  Warehouse,
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
  { to: "/fulfillment", label: "Fulfilment", icon: Truck },
  { to: "/wallet", label: "Кошелёк", icon: Wallet },
  { to: "/fx", label: "Курсы", icon: Coins },
  { to: "/users", label: "Пользователи", icon: UsersIcon },
  { to: "/settings", label: "Настройки", icon: Settings },
];

export function Layout() {
  const me = useAuthStore((s) => s.me);
  const logout = useAuthStore((s) => s.logout);

  return (
    <div className="flex min-h-screen">
      <aside
        className="flex h-screen flex-col border-r"
        style={{ width: "var(--sidebar-width)" }}
      >
        <div className="flex h-[var(--topbar-height)] items-center gap-2 border-b px-4">
          <ShieldCheck className="size-5 text-[--color-brand]" />
          <span className="text-lg font-semibold">YuPay Admin</span>
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
        <div className="border-t p-3 text-xs text-[--color-muted]">
          v0.0.1
        </div>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="flex h-[var(--topbar-height)] items-center justify-between border-b px-6">
          <span className="text-sm text-[--color-muted]">{me?.display_name ?? me?.email ?? ""}</span>
          <Button variant="ghost" size="sm" onClick={logout}>
            <LogOut className="size-4" />
            Выйти
          </Button>
        </header>
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
