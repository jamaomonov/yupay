import { Home, Clock, Settings } from "lucide-react";
import { Link, useLocation } from "wouter";

import { cn } from "@/lib/utils";

export function BottomNav() {
  const [location] = useLocation();

  const navItems = [
    { href: "/", label: "Главная", icon: Home },
    { href: "/history", label: "История", icon: Clock },
    { href: "/settings", label: "Настройки", icon: Settings },
  ];

  return (
    <nav
      aria-label="Основная навигация"
      className="fixed bottom-4 left-0 right-0 z-50 mx-auto flex max-w-[430px] justify-center px-6"
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
