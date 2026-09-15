"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";

import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";

export interface NavItem {
  href: string;
  label: string;
  /** `GET`, `POST`… on a reference entry; absent on a guide. */
  method?: string;
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

/** The tone of each method badge. Unlisted methods render neutral. */
const METHOD_TONE: Record<string, string> = {
  GET: "text-blue",
  POST: "text-primary",
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
  children,
}: {
  groups: NavGroup[];
  brand: string;
  children: React.ReactNode;
}) {
  const t = useTranslations("merchant.docs");
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const box = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
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
        items: group.items.filter((item) => item.label.toLowerCase().includes(needle)),
      }))
      .filter((group) => group.items.length > 0);
  }, [groups, query]);

  return (
    <div className="flex min-h-dvh">
      <aside className="border-border bg-card hidden w-[252px] shrink-0 flex-col border-r md:flex">
        <div className="px-5 pb-4 pt-5">
          <Link href={brand} className="font-display text-[15px] font-semibold tracking-[0.02em]">
            {t("title")}
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
              className="text-foreground min-w-0 flex-1 bg-transparent text-[13px] outline-none"
            />
            <kbd className="border-border text-tx-dim shrink-0 rounded border px-1.5 text-[10.5px]">
              ⌘K
            </kbd>
          </label>
        </div>

        <nav aria-label={t("navLabel")} className="min-h-0 flex-1 overflow-y-auto px-3 pb-6">
          {shown.length === 0 && <p className="text-tx-dim px-2 py-3 text-xs">{t("noMatches")}</p>}
          {shown.map((group) => (
            <div key={group.title} className="mb-4">
              <p className="text-tx-dim px-2 pb-1.5 pt-2 text-[10.5px] font-bold tracking-[0.09em]">
                {group.title}
              </p>
              {group.items.map((item) => {
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`rounded-btn flex items-center gap-2 px-2 py-1.5 text-[13px] ${
                      active ? "bg-card-2 text-foreground font-semibold" : "text-tx-mute"
                    }`}
                  >
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
                aria-current={pathname === item.href ? "page" : undefined}
                className={`rounded-btn shrink-0 whitespace-nowrap border px-3 py-1.5 text-xs ${
                  pathname === item.href
                    ? "border-border-2 bg-card-2 font-semibold"
                    : "border-border text-tx-mute"
                }`}
              >
                {item.label}
              </Link>
            ))}
        </nav>

        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
