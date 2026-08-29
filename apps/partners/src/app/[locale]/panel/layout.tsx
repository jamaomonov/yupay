"use client";

import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { Wordmark } from "@/components/Wordmark";
import { Link } from "@/i18n/navigation";
import { SHELL } from "@/components/landing/shell";
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
      {/* The same monospaced bar the landing wears, so a partner who arrives
          from it stays in one product. Tabs are underlined rather than
          pill-filled: a filled pill is a button, and these navigate. */}
      <header className="border-border bg-bg/85 sticky top-0 z-10 border-b backdrop-blur">
        <div className={`${SHELL} flex items-center justify-between gap-4 py-4`}>
          <Link href="/" className="flex items-center gap-3.5">
            <Wordmark height={22} />
            <span className="border-border text-tx-mute hidden border-l pl-3.5 font-mono text-[11px] uppercase tracking-[0.14em] sm:inline sm:text-[12px]">
              {t("brand")}
            </span>
          </Link>
          <div className="flex items-center gap-4 sm:gap-5">
            <LocaleSwitcher />
            <span className="text-tx-mute hidden font-mono text-[11.5px] sm:block">
              {partner.display_name ?? partner.email}
            </span>
            <button
              type="button"
              onClick={() => void signOut()}
              className="text-tx-mute hover:text-foreground font-mono text-[11px] uppercase tracking-[0.12em] transition"
            >
              {t("signOut")}
            </button>
          </div>
        </div>
        {/* The tabs scroll, and on Uzbek at 390px they must: measured
            447px of content in a 390px bar, with "TO'LOVLAY" — the money
            one — falling off the right edge with nothing to suggest it was
            there. The fade says the row continues. */}
        <div className="relative">
          <nav
            className={`${SHELL} -mb-px flex gap-7 overflow-x-auto pr-10 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden`}
          >
            {tabs.map((tab) => (
              <Link
                key={tab.href}
                href={tab.href}
                aria-current={isActive(tab.href) ? "page" : undefined}
                className={`shrink-0 border-b-2 pb-3 font-mono text-[11.5px] uppercase tracking-[0.12em] transition ${
                  isActive(tab.href)
                    ? "border-primary text-primary"
                    : "text-tx-mute hover:text-foreground border-transparent"
                }`}
              >
                {tab.label}
              </Link>
            ))}
          </nav>
          <div
            aria-hidden="true"
            className="from-bg pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l to-transparent"
          />
        </div>
      </header>
      <main className={`${SHELL} py-10`}>{children}</main>
    </div>
  );
}
