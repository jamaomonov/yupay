"use client";

import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import { useCabinet } from "@/components/CabinetContext";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { Mark } from "@/components/Mark";
import { ThemeToggle } from "@/components/ThemeToggle";
import { pathFor } from "@/lib/locale-href";
import { formatUsd, toCents } from "@/lib/money";

/**
 * Balance, search and account, on every cabinet screen.
 *
 * The balance lives here rather than on the dashboard because it is the
 * number a reseller checks before every order, and the catalog is where they
 * spend it — two screens away from where it used to be shown.
 */
export function TopBar() {
  const t = useTranslations("merchant.cabinet");
  // A box that looks searchable and searches nothing is worse than no box, so
  // screens without one — Settings, Webhooks — declare no placeholder and the
  // slot collapses.
  const { profile, p2p, search, setSearch, searchPlaceholder } = useCabinet();
  const { locale } = useParams<{ locale: string }>();
  const box = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchPlaceholder === null) return undefined;
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
      // ⌘K / Ctrl-K focuses the box. Not a command palette — this is the
      // shortcut for the search that is already on the screen, which is the
      // half of ⌘K people actually reach for.
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        box.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [searchPlaceholder]);

  const balance = profile ? toCents(profile.balance_usd) : null;
  const initial = profile?.title.trim().charAt(0).toUpperCase() ?? "";

  const topUpClass =
    "bg-primary text-primary-foreground rounded-btn flex items-center gap-1 whitespace-nowrap px-2 py-1.5 text-xs font-bold sm:px-3";
  const plus = (
    <>
      {/* On a phone the «+» alone: the row also carries the language now. */}
      <Plus aria-hidden size={14} strokeWidth={3} />
      <span className="hidden sm:inline">{t("topUp")}</span>
    </>
  );

  return (
    // Wraps below `sm`. The row holds a search box, a balance, a top-up
    // button, three locale links, a theme toggle and an avatar; at 390px the
    // search collapsed to zero width and the toggle sat 14px past the edge.
    // Letting the search take its own row is cheaper than hiding any of it.
    <div className="border-border bg-bg/90 sticky top-0 z-30 flex flex-wrap items-center justify-between gap-x-3 gap-y-2.5 border-b px-4 py-3 backdrop-blur-xl sm:flex-nowrap sm:px-6">
      {/* The sidebar carries the mark on desktop; on a phone this row is the
          only chrome at the top, so it carries it instead. */}
      <span className="md:hidden">
        <Mark />
      </span>
      {searchPlaceholder !== null ? (
        <label className="border-border bg-card-2 rounded-btn text-tx-dim order-last flex w-full min-w-0 items-center gap-2 border px-3 py-2 sm:order-none sm:w-auto sm:max-w-sm sm:flex-1">
          <Search size={15} className="shrink-0" />
          <input
            ref={box}
            type="search"
            value={search}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            onChange={(event) => {
              setSearch(event.target.value);
            }}
            className="text-foreground min-w-0 flex-1 bg-transparent text-sm"
          />
          <kbd className="border-border text-tx-dim hidden shrink-0 rounded border px-1.5 py-0.5 text-[11px] sm:block">
            ⌘K
          </kbd>
        </label>
      ) : (
        <div className="hidden min-w-0 flex-1 sm:block" />
      )}

      <div className="ml-auto flex min-w-0 items-center gap-2 sm:ml-0 sm:shrink-0 sm:gap-3">
        <div className="border-border bg-card rounded-btn flex items-center gap-2 border py-1 pl-3 pr-1 sm:gap-3 sm:pl-4">
          <span className="text-primary-ink font-mono text-sm font-extrabold tabular-nums">
            {balance === null ? "—" : `$${formatUsd(balance)}`}
          </span>
          {p2p?.enabled === true ? (
            <Link
              href={pathFor(locale, "/cabinet/top-up")}
              aria-label={t("topUp")}
              className={topUpClass}
            >
              {plus}
            </Link>
          ) : (
            // New tab. It navigated the cabinet away to Telegram, so an
            // operator mid-order lost the page they were on.
            <a
              href="https://t.me/yupay_support"
              target="_blank"
              rel="noopener noreferrer"
              aria-label={t("topUp")}
              className={topUpClass}
            >
              {plus}
            </a>
          )}
        </div>
        {/* The language stays in the bar on a phone too: the cabinet is not machine
            translated (see the cabinet layout), so this is how it becomes Uzbek. The
            theme moves into the tab bar's «Ещё» sheet. */}
        <LocaleSwitcher className="order-first sm:order-none" />
        <span className="hidden md:block">
          <ThemeToggle />
        </span>
        <div
          aria-hidden
          className="bg-primary text-primary-foreground hidden h-9 w-9 items-center justify-center rounded-lg text-sm font-extrabold sm:flex"
        >
          {initial}
        </div>
      </div>
    </div>
  );
}
