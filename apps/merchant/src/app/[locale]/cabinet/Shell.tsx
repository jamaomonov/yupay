"use client";

import {
  ArrowLeftRight,
  BookOpen,
  LayoutDashboard,
  LogOut,
  Package,
  Settings,
  Webhook,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useState } from "react";

import { CabinetProvider, sectionsOf, useCabinet } from "@/components/CabinetContext";
import { Mark } from "@/components/Mark";
import { SkipLink } from "@/components/SkipLink";
import { TopBar } from "@/components/TopBar";
import { hasSession, signOut } from "@/lib/api";
import { pathFor, withoutLocale } from "@/lib/locale-href";

/** The account group, in the order a day in the cabinet goes.
 *
 * These carry icons and the catalog sections above them do not, which is the
 * distinction rather than an inconsistency: a section is a *filter* on one
 * screen — and there is no icon for "Игры" that is not invented — while these
 * are *places*. The dot marks the first kind, the icon the second, and
 * each screen repeats its own icon in the heading so a click visibly landed. */
const ACCOUNT: { key: string; path: string; icon: LucideIcon }[] = [
  { key: "navOrders", path: "/cabinet/orders", icon: Package },
  { key: "navTransactions", path: "/cabinet/transactions", icon: ArrowLeftRight },
  { key: "navSettings", path: "/cabinet/settings", icon: Settings },
];

/** Everything a reseller only needs when they, or their server, talk to the
 *  API directly — kept out of the phone strip and off the manual-order path,
 *  grouped under its own heading in the desktop sidebar instead. */
const DEVELOPERS: { key: string; path: string; icon: LucideIcon }[] = [
  { key: "navWebhooks", path: "/cabinet/webhooks", icon: Webhook },
  { key: "navDocs", path: "/docs", icon: BookOpen },
];

function CabinetChrome({ children }: { children: React.ReactNode }) {
  const t = useTranslations("merchant.cabinet");
  const { locale } = useParams<{ locale: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const { catalog, profile } = useCabinet();
  const sections = sectionsOf(catalog);
  // Which section the catalog is filtered to, so the sidebar can say so.
  const active = useSearchParams().get("section");
  // Compared without a locale segment on either side. `usePathname()` returns
  // the browser's path — which for the default locale has no prefix at all —
  // so comparing it to a prefixed href matched nothing, and the sidebar
  // highlighted nothing for every Russian-speaking reseller.
  const here = withoutLocale(pathname);
  const onCatalog = here.startsWith("/cabinet/catalog");

  const leave = () => {
    void signOut().then(() => {
      router.replace(pathFor(locale, "/login"));
    });
  };

  const catalogHref = (slug: string | null) =>
    slug === null
      ? pathFor(locale, "/cabinet/catalog")
      : pathFor(locale, `/cabinet/catalog?section=${slug}`);

  const nav = (
    <>
      <p className="text-tx-dim px-3 pb-1.5 pt-3 text-[10.5px] font-bold tracking-[0.09em]">
        {t("groupCatalog")}
      </p>
      {/* Sections, not a hard-coded pair: they come from the catalog the shell
          already holds, so a category that has nothing purchasable in it never
          appears — and a new one appears the day it does. */}
      <SideLink
        href={catalogHref(null)}
        label={t("navAllBrands")}
        active={onCatalog && active === null}
      />
      {sections.map((section) => (
        <SideLink
          key={section.slug}
          href={catalogHref(section.slug)}
          label={section.name}
          count={section.count}
          active={onCatalog && active === section.slug}
        />
      ))}

      <p className="text-tx-dim px-3 pb-1.5 pt-4 text-[10.5px] font-bold tracking-[0.09em]">
        {t("groupAccount")}
      </p>
      <SideLink
        href={pathFor(locale, "/cabinet")}
        label={t("navDashboard")}
        icon={LayoutDashboard}
        active={here === "/cabinet"}
      />
      {ACCOUNT.map(({ key, path, icon }) => (
        <SideLink
          key={key}
          href={pathFor(locale, path)}
          label={t(key)}
          icon={icon}
          active={here.startsWith(path)}
        />
      ))}

      <p className="text-tx-dim px-3 pb-1.5 pt-4 text-[10.5px] font-bold tracking-[0.09em]">
        {t("groupDevelopers")}
      </p>
      {DEVELOPERS.map(({ key, path, icon }) => (
        <SideLink
          key={key}
          href={pathFor(locale, path)}
          label={t(key)}
          icon={icon}
          active={here.startsWith(path)}
        />
      ))}
    </>
  );

  return (
    <div className="flex min-h-dvh">
      <SkipLink />
      <aside className="border-border bg-card hidden w-[216px] shrink-0 flex-col border-r px-3 py-4 md:flex">
        <Link
          href={pathFor(locale, "/cabinet")}
          className="flex items-center gap-2.5 px-2.5 pb-4 pt-1"
        >
          <Mark />
          <span className="font-display text-[15px] font-semibold tracking-[0.02em]">YUPAY</span>
        </Link>
        <nav aria-label={t("navLabel")} className="space-y-0.5">
          {nav}
        </nav>
        <div className="border-border text-tx-dim mt-auto border-t px-3 pt-3 text-xs">
          <p className="text-foreground truncate font-medium">{profile?.title ?? " "}</p>
          <p className="mt-0.5 truncate text-[11px]">{profile?.email ?? " "}</p>
          <button type="button" onClick={leave} className="mt-2.5 flex items-center gap-2 text-xs">
            <LogOut size={13} />
            {t("signOut")}
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        {/* Below `md` the sidebar is gone, so the destinations a reseller uses
            day to day ride above the content as a scrolling row. Webhooks and
            docs stay off this strip — they are reachable from the sidebar on
            desktop and from the docs link in the landing header — because the
            manual-order path (catalog → order → orders) is the one a phone
            visitor is on. A drawer would be tidier and would also mean a
            phone user staring at a screen with no visible way off it until
            they find the button. */}
        <nav
          aria-label={t("navLabel")}
          className="border-border flex gap-2 overflow-x-auto border-b px-4 py-2.5 md:hidden"
        >
          <MobileLink
            href={pathFor(locale, "/cabinet")}
            label={t("navDashboard")}
            icon={LayoutDashboard}
            active={here === "/cabinet"}
          />
          <MobileLink href={catalogHref(null)} label={t("navCatalog")} active={onCatalog} />
          {ACCOUNT.map(({ key, path, icon }) => (
            <MobileLink
              key={key}
              href={pathFor(locale, path)}
              label={t(key)}
              icon={icon}
              active={here.startsWith(path)}
            />
          ))}
          <button
            type="button"
            onClick={leave}
            aria-label={t("signOut")}
            className="border-border text-tx-dim rounded-btn shrink-0 border px-3 py-1.5"
          >
            <LogOut size={14} />
          </button>
        </nav>

        <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-4 py-5 sm:px-6">
          {children}
        </main>
      </div>
    </div>
  );
}

function SideLink({
  href,
  label,
  count,
  icon: Icon,
  active,
}: {
  href: string;
  label: string;
  count?: number;
  /** A destination gets a mark; a catalog filter gets the dot below. */
  icon?: LucideIcon;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`rounded-btn flex items-center gap-2.5 px-3 py-2 text-[13.5px] ${
        active ? "bg-card-2 text-foreground font-semibold" : "text-tx-mute"
      }`}
    >
      {Icon === undefined ? (
        <span
          aria-hidden
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${active ? "bg-primary" : "bg-border-2"}`}
        />
      ) : (
        <Icon
          aria-hidden
          size={15}
          className={`shrink-0 ${active ? "text-primary-ink" : "text-tx-dim"}`}
        />
      )}
      <span className="min-w-0 truncate">{label}</span>
      {count !== undefined && (
        <span className="text-tx-dim ml-auto font-mono text-[11px]">{count}</span>
      )}
    </Link>
  );
}

function MobileLink({
  href,
  label,
  icon: Icon,
  active,
}: {
  href: string;
  label: string;
  icon?: LucideIcon;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`rounded-btn flex shrink-0 items-center gap-1.5 whitespace-nowrap border px-3 py-1.5 text-xs ${
        active ? "border-border-2 bg-card-2 font-semibold" : "border-border text-tx-mute"
      }`}
    >
      {Icon !== undefined && (
        <Icon aria-hidden size={13} className={active ? "text-primary-ink" : "text-tx-dim"} />
      )}
      {label}
    </Link>
  );
}

/**
 * The signed-in cabinet chrome: sidebar/mobile nav, session gate, and the
 * catalog/profile context every screen below it reads.
 *
 * Lives apart from `layout.tsx` because that file must stay a server
 * component to export the `noindex` metadata, and this shell needs the
 * client hooks (`usePathname`, `useState`) a server component cannot use.
 */
export function Shell({ children }: { children: React.ReactNode }) {
  const { locale } = useParams<{ locale: string }>();
  const router = useRouter();
  // `null` while unknown: `localStorage` is not readable during SSR, so
  // rendering the cabinet before the check would flash a signed-in shell at
  // somebody who is signed out.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  useEffect(() => {
    const present = hasSession();
    setSignedIn(present);
    if (!present) router.replace(pathFor(locale, "/login"));
  }, [locale, router]);

  if (signedIn !== true) return null;

  // The provider sits inside the session check so its two fetches never fire
  // for a browser that is about to be redirected to the sign-in form.
  return (
    <CabinetProvider>
      {/* `useSearchParams` in the chrome opts this subtree into client
          rendering, and Next requires the boundary to be explicit — the same
          shape `/confirm` and `/reset` use. */}
      <Suspense fallback={null}>
        <CabinetChrome>{children}</CabinetChrome>
      </Suspense>
    </CabinetProvider>
  );
}
