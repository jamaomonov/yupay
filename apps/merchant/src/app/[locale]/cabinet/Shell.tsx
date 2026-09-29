"use client";

import {
  ArrowLeftRight,
  BookOpen,
  LayoutDashboard,
  LayoutGrid,
  LogOut,
  MoreHorizontal,
  Package,
  Settings,
  Wallet,
  Webhook,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useState } from "react";

import { CabinetProvider, sectionsOf, useCabinet } from "@/components/CabinetContext";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { Mark } from "@/components/Mark";
import { SkipLink } from "@/components/SkipLink";
import { ThemeToggle } from "@/components/ThemeToggle";
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
  const [moreOpen, setMoreOpen] = useState(false);

  // A tap on a link inside the sheet navigates; the sheet must not survive it.
  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

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
    // `translate="no"`: see the cabinet layout — a translated page stops updating.
    <div className="flex min-h-dvh" translate="no">
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
        {/* Below `md` the sidebar is gone. The strip that replaced it scrolled
            sideways at the top of the page, so on a 390px phone Settings and
            sign-out sat past the edge and nothing said they were there. A tab
            bar at the thumb's edge holds the four daily places in plain sight;
            everything else — settings, the developer screens, language, theme,
            sign-out — lives one tap away under «Ещё». */}
        <MobileTabs
          items={[
            {
              href: pathFor(locale, "/cabinet"),
              label: t("navDashboard"),
              icon: LayoutDashboard,
              active: here === "/cabinet",
            },
            {
              href: catalogHref(null),
              label: t("navCatalog"),
              icon: LayoutGrid,
              active: onCatalog,
            },
            {
              href: pathFor(locale, "/cabinet/orders"),
              label: t("navOrders"),
              icon: Package,
              active: here.startsWith("/cabinet/orders"),
            },
            {
              href: pathFor(locale, "/cabinet/transactions"),
              label: t("tabBalance"),
              icon: Wallet,
              active: here.startsWith("/cabinet/transactions"),
            },
          ]}
          moreLabel={t("navMore")}
          moreActive={here.startsWith("/cabinet/settings") || here.startsWith("/cabinet/webhooks")}
          onMore={() => {
            setMoreOpen(true);
          }}
        />
        {moreOpen && (
          <MoreSheet
            onClose={() => {
              setMoreOpen(false);
            }}
            title={profile?.title ?? ""}
            email={profile?.email ?? ""}
            links={[
              {
                href: pathFor(locale, "/cabinet/settings"),
                label: t("navSettings"),
                icon: Settings,
              },
              {
                href: pathFor(locale, "/cabinet/webhooks"),
                label: t("navWebhooks"),
                icon: Webhook,
              },
              { href: pathFor(locale, "/docs"), label: t("navDocs"), icon: BookOpen },
            ]}
            languageLabel={t("language")}
            themeLabel={t("theme")}
            closeLabel={t("close")}
            signOutLabel={t("signOut")}
            onSignOut={leave}
          />
        )}

        {/* Bottom padding clears the fixed tab bar and the home indicator. */}
        <main
          id="main"
          tabIndex={-1}
          className="min-w-0 flex-1 px-4 py-5 pb-[calc(5.5rem+env(safe-area-inset-bottom))] sm:px-6 md:pb-5"
        >
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

interface Tab {
  href: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
}

function MobileTabs({
  items,
  moreLabel,
  moreActive,
  onMore,
}: {
  items: Tab[];
  moreLabel: string;
  moreActive: boolean;
  onMore: () => void;
}) {
  const tab = (active: boolean) =>
    `flex min-w-0 flex-1 flex-col items-center gap-1 pb-1.5 pt-2 text-[10.5px] ${
      active ? "text-foreground font-semibold" : "text-tx-dim"
    }`;
  return (
    <nav
      aria-label={moreLabel}
      className="border-border bg-card/95 fixed inset-x-0 bottom-0 z-40 flex border-t pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden"
    >
      {items.map(({ href, label, icon: Icon, active }) => (
        <Link
          key={href}
          href={href}
          aria-current={active ? "page" : undefined}
          className={tab(active)}
        >
          <Icon aria-hidden size={20} className={active ? "text-primary-ink" : ""} />
          <span className="max-w-full truncate px-1">{label}</span>
        </Link>
      ))}
      <button type="button" onClick={onMore} aria-haspopup="dialog" className={tab(moreActive)}>
        <MoreHorizontal aria-hidden size={20} className={moreActive ? "text-primary-ink" : ""} />
        <span className="max-w-full truncate px-1">{moreLabel}</span>
      </button>
    </nav>
  );
}

function MoreSheet({
  onClose,
  title,
  email,
  links,
  languageLabel,
  themeLabel,
  closeLabel,
  signOutLabel,
  onSignOut,
}: {
  onClose: () => void;
  title: string;
  email: string;
  links: { href: string; label: string; icon: LucideIcon }[];
  languageLabel: string;
  themeLabel: string;
  closeLabel: string;
  signOutLabel: string;
  onSignOut: () => void;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 md:hidden"
    >
      <button
        type="button"
        aria-label={closeLabel}
        onClick={onClose}
        className="absolute inset-0 bg-black/50"
      />
      <div className="border-border bg-card absolute inset-x-0 bottom-0 rounded-t-2xl border-t px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-4">
        <div className="flex items-start justify-between gap-3 px-1">
          <div className="min-w-0">
            <p className="truncate font-semibold">{title}</p>
            <p className="text-tx-dim truncate text-xs">{email}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            className="border-border text-tx-mute flex h-9 w-9 shrink-0 items-center justify-center rounded-full border"
          >
            <X size={16} />
          </button>
        </div>
        <nav className="mt-4 space-y-1">
          {links.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="rounded-btn hover:bg-card-2 flex items-center gap-3 px-3 py-3 text-[15px]"
            >
              <Icon aria-hidden size={18} className="text-tx-dim" />
              {label}
            </Link>
          ))}
        </nav>
        <div className="border-border mt-3 space-y-3 border-t px-3 pt-4 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-tx-mute">{languageLabel}</span>
            <LocaleSwitcher />
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-tx-mute">{themeLabel}</span>
            <ThemeToggle />
          </div>
        </div>
        <button
          type="button"
          onClick={onSignOut}
          className="border-border text-danger rounded-btn mt-4 flex w-full items-center justify-center gap-2 border py-3 text-sm font-semibold"
        >
          <LogOut aria-hidden size={16} />
          {signOutLabel}
        </button>
      </div>
    </div>
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
