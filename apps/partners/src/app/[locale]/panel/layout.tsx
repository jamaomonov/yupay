"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { useRequireSession } from "@/lib/auth";

/**
 * The gate and the navigation.
 *
 * Renders nothing but a placeholder while the session is still being restored:
 * a partner returning to an open tab is not signed out, they are not known
 * yet, and flashing the login screen at them would be a lie.
 */
export default function PanelLayout({ children }: { children: React.ReactNode }) {
  const t = useTranslations("partners.panel");
  const { status, partner, signOut } = useRequireSession();
  const pathname = usePathname();

  if (status !== "in" || partner === null) {
    return (
      <main className="flex min-h-dvh items-center justify-center">
        <p className="text-tx-mute text-[14px]">{t("loading")}</p>
      </main>
    );
  }

  const tabs = [
    { href: "/panel", label: t("navOverview") },
    { href: "/panel/codes", label: t("navCodes") },
    { href: "/panel/referrals", label: t("navReferrals") },
    { href: "/panel/payouts", label: t("navPayouts") },
  ] as const;

  // `startsWith` would light up "Overview" on every child route, since every
  // panel path begins with /panel.
  const isActive = (href: string): boolean =>
    href === "/panel" ? pathname.endsWith("/panel") : pathname.endsWith(href);

  return (
    <div className="min-h-dvh">
      <header className="border-border bg-card/80 sticky top-0 z-10 border-b backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-5 py-3">
          <span className="font-display text-[15px] font-bold">YuPay</span>
          <div className="flex items-center gap-3">
            <span className="text-tx-mute hidden text-[13px] sm:block">
              {partner.display_name ?? partner.email}
            </span>
            <button
              type="button"
              onClick={() => void signOut()}
              className="text-tx-mute hover:text-foreground text-[13px] underline transition"
            >
              {t("signOut")}
            </button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-5xl gap-1 overflow-x-auto px-5 pb-2">
          {tabs.map((tab) => (
            <Link
              key={tab.href}
              href={tab.href}
              className={`rounded-btn shrink-0 px-3.5 py-2 text-[13px] font-semibold transition ${
                isActive(tab.href)
                  ? "bg-primary/10 text-primary"
                  : "text-tx-mute hover:text-foreground"
              }`}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-5xl px-5 py-8">{children}</main>
    </div>
  );
}
