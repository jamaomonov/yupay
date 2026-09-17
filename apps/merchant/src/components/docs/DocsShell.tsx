"use client";

import {
  ArrowLeft,
  BookOpen,
  KeyRound,
  Rocket,
  Search,
  TriangleAlert,
  Webhook,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { SkipLink } from "@/components/SkipLink";
import { ThemeToggle } from "@/components/ThemeToggle";
import { withoutLocale } from "@/lib/locale-href";

export interface NavItem {
  href: string;
  label: string;
  /** The long form — shown on hover, and searched alongside the label. */
  title?: string;
  /** `GET`, `POST`… on a reference entry; absent on a guide. */
  method?: string;
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

/**
 * An icon for each guide, keyed on its trailing path segment.
 *
 * Keyed here rather than carried on `NavItem` because the sidebar is built in
 * a Server Component and a component reference cannot cross that boundary as a
 * prop. The segment is stable — these five pages are the guides — and a path
 * that is not one of them gets no icon rather than a wrong one.
 *
 * Only the guides. The reference entries below already carry a method badge,
 * and the schema list is one kind of thing repeated: an icon on every row
 * there would be wallpaper.
 */
const GUIDE_ICON: Record<string, LucideIcon> = {
  docs: BookOpen,
  authentication: KeyRound,
  quickstart: Rocket,
  errors: TriangleAlert,
  webhooks: Webhook,
};

function guideIcon(href: string): LucideIcon | undefined {
  const segment = href.split("/").filter(Boolean).at(-1) ?? "";
  return GUIDE_ICON[segment];
}

/** The tone of each method badge. Unlisted methods render neutral. */
const METHOD_TONE: Record<string, string> = {
  GET: "text-blue",
  POST: "text-primary-ink",
  PUT: "text-gold",
  PATCH: "text-gold",
  DELETE: "text-danger",
};

/**
 * The documentation shell: a sidebar of everything, a search over it, and the
 * page.
 *
 * The sidebar is built from the **contract** by the server layout above, so an
 * endpoint appears here the day it is published and cannot be forgotten. The
 * search filters that same list rather than indexing prose — what a developer
 * is looking for at speed is an endpoint or a model, and a full-text index
 * over guide copy would bury both.
 */
export function DocsShell({
  groups,
  brand,
  apiOverview,
  children,
}: {
  groups: NavGroup[];
  brand: string;
  /** Link back to the `/api` marketing page — the door a developer came in
   *  through, one level up from the reference itself. */
  apiOverview: string;
  children: React.ReactNode;
}) {
  const t = useTranslations("merchant.docs");
  // Normalised on both sides — see the cabinet shell for the full story. Here
  // the symptom was different and just as wrong: the server-rendered highlight
  // was right, and every client-side navigation after it left the mark where
  // it started, so clicking three guides in a row still showed the first.
  const here = withoutLocale(usePathname());
  const [query, setQuery] = useState("");
  const box = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // Not while the reader is typing somewhere else: on macOS Ctrl-K is the
      // standard "kill to end of line" inside a text field, and stealing it
      // yanks somebody mid-edit into a search box they did not ask for.
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          target instanceof HTMLInputElement ||
          target instanceof HTMLTextAreaElement)
      ) {
        return;
      }
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        box.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle === "") return groups;
    return groups
      .map((group) => ({
        ...group,
        // Both halves. The label is now the path, so typing "orders" — the
        // natural query — used to match the prose and never the endpoint,
        // and typing "/merchant/v1/catalog" matched nothing at all.
        items: group.items.filter((item) =>
          `${item.label} ${item.title ?? ""}`.toLowerCase().includes(needle),
        ),
      }))
      .filter((group) => group.items.length > 0);
  }, [groups, query]);

  return (
    <div className="flex min-h-dvh">
      <SkipLink />
      <aside
        aria-label={t("navLabel")}
        className="border-border bg-card hidden w-[252px] shrink-0 flex-col border-r md:flex"
      >
        <div className="px-5 pb-4 pt-5">
          <Link href={brand} className="font-display text-[15px] font-semibold tracking-[0.02em]">
            {t("title")}
          </Link>
          <Link
            href={apiOverview}
            className="text-tx-dim hover:text-foreground mt-1 flex items-center gap-1 text-[12px] transition"
          >
            <ArrowLeft size={12} aria-hidden="true" />
            {t("apiOverview")}
          </Link>
        </div>
        <div className="px-4 pb-3">
          <label className="border-border bg-card-2 rounded-btn text-tx-dim flex items-center gap-2 border px-3 py-2">
            <Search size={14} className="shrink-0" />
            <input
              ref={box}
              type="search"
              value={query}
              placeholder={t("searchPlaceholder")}
              aria-label={t("searchPlaceholder")}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
              className="text-foreground min-w-0 flex-1 bg-transparent text-[13px]"
            />
            <kbd className="border-border text-tx-dim shrink-0 rounded border px-1.5 text-[10.5px]">
              ⌘K
            </kbd>
          </label>
        </div>

        <nav aria-label={t("navLabel")} className="min-h-0 flex-1 overflow-y-auto px-3 pb-6">
          {shown.length === 0 && (
            <p role="status" className="text-tx-dim px-2 py-3 text-xs">
              {t("noMatches")}
            </p>
          )}
          {shown.map((group) => (
            <div key={group.title} className="mb-4">
              <p className="text-tx-dim px-2 pb-1.5 pt-2 text-[10.5px] font-bold tracking-[0.09em]">
                {group.title}
              </p>
              {group.items.map((item) => {
                const active = here === withoutLocale(item.href);
                const Icon = item.method === undefined ? guideIcon(item.href) : undefined;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    title={item.title}
                    className={`rounded-btn flex items-center gap-2 px-2 py-1.5 text-[13px] ${
                      active ? "bg-card-2 text-foreground font-semibold" : "text-tx-mute"
                    }`}
                  >
                    {Icon !== undefined && (
                      <Icon
                        aria-hidden
                        size={14}
                        className={`shrink-0 ${active ? "text-primary-ink" : "text-tx-dim"}`}
                      />
                    )}
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {item.method !== undefined && (
                      <span
                        className={`shrink-0 font-mono text-[10px] font-bold ${
                          METHOD_TONE[item.method] ?? "text-tx-dim"
                        }`}
                      >
                        {item.method}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-border flex items-center justify-between gap-3 border-b px-4 py-3 sm:px-8">
          <Link href={brand} className="text-tx-mute text-sm font-medium md:hidden">
            {t("title")}
          </Link>
          <div className="hidden md:block" />
          <div className="flex items-center gap-4">
            <Link href={brand} className="text-tx-mute hidden text-[13.5px] sm:block">
              {t("backToSite")}
            </Link>
            <LocaleSwitcher />
            <ThemeToggle />
          </div>
        </header>

        {/* Below `md` the sidebar is gone; the same list rides above the page
            as a scrolling row, for the reason the cabinet's does — a phone
            reader must never land on a page with no way off it. */}
        <nav
          aria-label={t("navLabel")}
          className="border-border flex gap-2 overflow-x-auto border-b px-4 py-2.5 md:hidden"
        >
          {groups
            .flatMap((group) => group.items)
            .map((item) => (
              <Link
                key={item.href}
                href={item.href}
                aria-current={here === withoutLocale(item.href) ? "page" : undefined}
                className={`rounded-btn shrink-0 whitespace-nowrap border px-3 py-1.5 text-xs ${
                  here === withoutLocale(item.href)
                    ? "border-border-2 bg-card-2 font-semibold"
                    : "border-border text-tx-mute"
                }`}
              >
                {item.label}
              </Link>
            ))}
        </nav>

        <main id="main" tabIndex={-1} className="min-w-0 flex-1">
          {children}
        </main>
      </div>
    </div>
  );
}
