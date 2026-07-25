import { Home, Clock, Settings, ShoppingCart } from "lucide-react";
import { Link, useLocation } from "wouter";

import { useT } from "@/lib/i18n";
import { useKeyboardOpen } from "@/lib/use-keyboard-open";
import { cn } from "@/lib/utils";

export function BottomNav() {
  const [location] = useLocation();
  const { t } = useT();
  const keyboardOpen = useKeyboardOpen();

  const navItems = [
    { href: "/", label: t("nav.home"), icon: Home },
    { href: "/cs2-market", label: "Market", icon: ShoppingCart },
    { href: "/history", label: t("nav.history"), icon: Clock },
    { href: "/settings", label: t("nav.settings"), icon: Settings },
  ];

  // Nobody navigates mid-typing, and on a phone with the keyboard up this bar
  // plus the pay button swallow most of the remaining screen. `--app-nav-h`
  // collapses in step (lib/telegram.ts), so the layout closes the gap.
  if (keyboardOpen) return null;

  return (
    <nav
      aria-label={t("nav.primary")}
      className="fixed bottom-[calc(var(--app-inset-bottom)_+_var(--app-nav-gap))] left-0 right-0 z-50 mx-auto flex max-w-[430px] justify-center px-6"
    >
      <div className="bg-card/80 border-border/60 flex w-full items-center justify-around rounded-[22px] border px-3 py-2 shadow-[0_8px_32px_rgba(0,0,0,0.45)] backdrop-blur-2xl">
        {navItems.map((item) => {
          const isActive = location === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              aria-label={item.label}
              className="flex min-w-[56px] flex-col items-center gap-0.5"
              data-testid={`nav-${item.href.replace("/", "") || "home"}`}
            >
              <div
                className={cn(
                  "rounded-xl p-1.5 transition-all duration-200",
                  isActive ? "text-primary" : "text-muted-foreground",
                )}
              >
                <Icon
                  size={20}
                  aria-hidden="true"
                  className={cn("transition-transform duration-200", isActive && "scale-110")}
                />
              </div>
              <span
                className={cn(
                  "text-[10px] font-medium transition-colors",
                  isActive ? "text-primary" : "text-muted-foreground",
                )}
              >
                {item.label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
