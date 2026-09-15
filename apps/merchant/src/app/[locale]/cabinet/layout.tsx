"use client";

import { LayoutGrid, LogOut, Receipt, Settings, ShoppingBag, Wallet } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { hasSession, signOut } from "@/lib/api";

export default function CabinetLayout({ children }: { children: React.ReactNode }) {
  const t = useTranslations("merchant.cabinet");
  const { locale } = useParams<{ locale: string }>();
  const pathname = usePathname();
  const router = useRouter();
  // `null` while unknown: `localStorage` is not readable during SSR, so
  // rendering the cabinet before the check would flash a signed-in shell at
  // somebody who is signed out.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  useEffect(() => {
    const present = hasSession();
    setSignedIn(present);
    if (!present) router.replace(`/${locale}/login`);
  }, [locale, router]);

  if (signedIn !== true) return null;

  const nav = [
    { href: `/${locale}/cabinet`, label: t("navDashboard"), icon: LayoutGrid },
    { href: `/${locale}/cabinet/catalog`, label: t("navCatalog"), icon: ShoppingBag },
    { href: `/${locale}/cabinet/orders`, label: t("navOrders"), icon: Receipt },
    { href: `/${locale}/cabinet/transactions`, label: t("navTransactions"), icon: Wallet },
    { href: `/${locale}/cabinet/settings`, label: t("navSettings"), icon: Settings },
  ];

  const leave = () => {
    void signOut().then(() => {
      router.replace(`/${locale}/login`);
    });
  };

  return (
    <div className="mx-auto flex w-full max-w-6xl gap-8 px-5 py-8">
      <aside className="hidden w-52 shrink-0 md:block">
        <nav aria-label={t("navLabel")} className="space-y-1">
          {nav.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={`rounded-btn flex items-center gap-2.5 px-3 py-2 text-sm ${
                  active ? "bg-card-2 font-semibold" : "text-tx-mute"
                }`}
              >
                <Icon size={16} />
                {label}
              </Link>
            );
          })}
        </nav>
        <button
          type="button"
          onClick={leave}
          className="text-tx-dim mt-6 flex items-center gap-2.5 px-3 py-2 text-sm"
        >
          <LogOut size={16} />
          {t("signOut")}
        </button>
      </aside>

      <div className="min-w-0 flex-1">
        {/* Below `md` the sidebar is gone, so the same five destinations —
            and the way out — ride above the content as a scrolling row. A
            drawer would be tidier and would also mean a phone user staring at
            a screen with no visible way off it until they find the button. */}
        <div className="mb-6 flex items-center gap-3">
          <nav
            aria-label={t("navLabel")}
            className="-mx-5 flex min-w-0 flex-1 gap-2 overflow-x-auto px-5 md:hidden"
          >
            {nav.map(({ href, label }) => {
              const active = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-btn shrink-0 whitespace-nowrap border px-3 py-1.5 text-xs ${
                    active
                      ? "border-border-2 bg-card-2 font-semibold"
                      : "border-border text-tx-mute"
                  }`}
                >
                  {label}
                </Link>
              );
            })}
            <button
              type="button"
              onClick={leave}
              aria-label={t("signOut")}
              className="border-border text-tx-dim rounded-btn shrink-0 border px-3 py-1.5"
            >
              <LogOut size={14} />
            </button>
          </nav>
          <div className="ml-auto shrink-0">
            <ThemeToggle />
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}
