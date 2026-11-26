"use client";

import { foldRegions, regionMatches } from "@yupay/utils";
import { ChevronDown, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useMemo, useState } from "react";

import { RegionFlag } from "./RegionFlag";

interface RegionSwitcherProps {
  /** Region codes in the API's order; the first is the game's main region. */
  codes: readonly string[];
  current: string;
  name: (code: string) => string;
  onPick: (code: string) => void;
}

const CHIP =
  "focus-visible:ring-primary focus-visible:ring-offset-bg inline-flex min-h-[44px] items-center gap-2 rounded-full border px-4 py-2 text-[13px] font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2";

function chipTone(active: boolean): string {
  return active
    ? "border-primary bg-primary/10 text-foreground"
    : "border-border bg-card text-tx-mute hover:border-border-2";
}

/**
 * The region chips (ADR-0099), with flags. A game sold in many regions
 * (PlayStation: 43) keeps eight on screen — its main region, then the
 * countries our buyers pick most — and folds the rest under «Все регионы»,
 * an inline list with a search field. The picked region always stays a chip.
 */
export function RegionSwitcher({ codes, current, name, onPick }: RegionSwitcherProps) {
  const t = useTranslations("web.store");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const listId = useId();
  const home = codes[0];
  const { shown, folded } = foldRegions(codes, current);

  const all = useMemo(
    () => [...codes].sort((a, b) => name(a).localeCompare(name(b))),
    [codes, name],
  );
  const found = all.filter((c) => regionMatches(query, name(c), c));

  function pick(code: string): void {
    onPick(code);
    setOpen(false);
    setQuery("");
  }

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {shown.map((code) => {
          const active = code === current;
          return (
            <button
              key={code}
              type="button"
              aria-pressed={active}
              onClick={() => {
                pick(code);
              }}
              className={`${CHIP} ${chipTone(active)}`}
            >
              <RegionFlag code={code} home={code === home} />
              {name(code)}
            </button>
          );
        })}
        {folded > 0 && (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => {
              setOpen((v) => !v);
            }}
            className={`${CHIP} ${chipTone(open)}`}
          >
            {open ? t("regionCollapse") : t("regionAll", { count: codes.length })}
            <ChevronDown
              aria-hidden
              size={14}
              className={`transition-transform ${open ? "rotate-180" : ""}`}
            />
          </button>
        )}
      </div>
      {folded > 0 && open && (
        <div id={listId} className="border-border bg-card mt-3 rounded-2xl border p-3">
          <label className="border-border bg-bg focus-within:border-primary flex items-center gap-2 rounded-xl border px-3">
            <Search aria-hidden size={16} className="text-tx-mute shrink-0" />
            <input
              type="search"
              value={query}
              autoFocus
              placeholder={t("regionSearch")}
              aria-label={t("regionSearch")}
              onChange={(e) => {
                setQuery(e.target.value);
              }}
              onKeyDown={(e) => {
                if (e.key === "Escape") setOpen(false);
                if (e.key === "Enter" && found[0]) pick(found[0]);
              }}
              className="placeholder:text-tx-mute min-h-[44px] w-full bg-transparent text-sm outline-none"
            />
          </label>
          {found.length === 0 ? (
            <p className="text-tx-mute px-1 pb-1 pt-3 text-[13px]">{t("regionNone")}</p>
          ) : (
            <ul className="mt-2 grid max-h-72 grid-cols-2 gap-1 overflow-y-auto sm:grid-cols-3 lg:grid-cols-4">
              {found.map((code) => {
                const active = code === current;
                return (
                  <li key={code}>
                    <button
                      type="button"
                      aria-pressed={active}
                      onClick={() => {
                        pick(code);
                      }}
                      className={`focus-visible:ring-primary flex min-h-[40px] w-full items-center gap-2 rounded-lg px-2.5 text-left text-[13px] font-medium transition focus-visible:outline-none focus-visible:ring-2 ${
                        active ? "bg-primary/10 text-foreground" : "text-tx-mute hover:bg-white/5"
                      }`}
                    >
                      <RegionFlag code={code} home={code === home} />
                      <span className="truncate">{name(code)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
