"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import { useCabinet } from "@/components/CabinetContext";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
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
  const { profile, search, setSearch, searchPlaceholder } = useCabinet();
  const box = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchPlaceholder === null) return undefined;
    const onKey = (event: KeyboardEvent) => {
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

  return (
    <div className="border-border flex items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
      {searchPlaceholder !== null ? (
        <label className="border-border bg-card-2 rounded-btn text-tx-dim flex min-w-0 flex-1 items-center gap-2 border px-3 py-2 sm:max-w-sm">
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
            className="text-foreground min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
          <kbd className="border-border text-tx-dim hidden shrink-0 rounded border px-1.5 py-0.5 text-[11px] sm:block">
            ⌘K
          </kbd>
        </label>
      ) : (
        <div className="min-w-0 flex-1" />
      )}

      <div className="flex shrink-0 items-center gap-2 sm:gap-3">
        <div className="border-border bg-card rounded-btn flex items-center gap-2 border py-1 pl-3 pr-1 sm:gap-3 sm:pl-4">
          <span className="text-primary font-mono text-sm font-extrabold">
            {balance === null ? "—" : `$${formatUsd(balance)}`}
          </span>
          <a
            href="https://t.me/yupay_support"
            className="bg-primary text-primary-foreground rounded-btn whitespace-nowrap px-3 py-1.5 text-xs font-bold"
          >
            {t("topUp")}
          </a>
        </div>
        {/* Shown on a phone too. Hiding it there would leave the one
            surface a reseller uses daily with no way to change language — the
            complaint this whole control answers. The search box carries
            `min-w-0 flex-1`, so it gives up the width. */}
        <LocaleSwitcher />
        <ThemeToggle />
        <div
          aria-hidden
          className="bg-primary text-primary-foreground hidden h-[34px] w-[34px] items-center justify-center rounded-[10px] text-sm font-extrabold sm:flex"
        >
          {initial}
        </div>
      </div>
    </div>
  );
}
