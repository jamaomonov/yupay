/**
 * The top-up page's region chips (ADR-0099), with flags.
 *
 * A game sold in many regions (PlayStation: 43) keeps eight chips — its main
 * region, then the countries our buyers pick most — and folds the rest under
 * «Все · 43», an inline list with a search field. The picked region always
 * stays a chip. The fold rule lives in `@yupay/utils` and is shared with the
 * storefront's switcher.
 */

import { foldRegions, homeRegionFlagSrc, regionMatches } from "@yupay/utils";
import { ChevronDown, Globe, Search } from "lucide-react";
import { useId, useState } from "react";

import { useT } from "@/lib/i18n";
import { regionLabel, type BrandRegion } from "@/lib/region";

interface RegionFlagProps {
  code: string;
  home?: boolean;
}

/** A region's flag, or a globe for a region that is not one country. The
 *  name always sits next to it, so it is decorative. */
export function RegionFlag({ code, home = false }: RegionFlagProps) {
  const src = homeRegionFlagSrc(code.toLowerCase(), home);
  if (!src) return <Globe aria-hidden size={13} className="shrink-0 text-white/50" />;
  return (
    <img
      src={src}
      alt=""
      width={18}
      height={13}
      loading="lazy"
      className="h-[13px] w-[18px] shrink-0 rounded-[2px] object-cover ring-1 ring-white/10"
    />
  );
}

interface RegionPickerProps {
  regions: readonly BrandRegion[];
  current: string;
  onPick: (code: string) => void;
}

function chipStyle(active: boolean): React.CSSProperties {
  return {
    background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
    color: active ? "#fff" : "rgba(255,255,255,0.6)",
    border: active ? "1.5px solid hsl(var(--primary) / 0.7)" : "1px solid hsl(var(--border))",
  };
}

const CHIP =
  "flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap rounded-2xl px-3.5 py-1.5 text-xs font-semibold transition-all duration-150";

export function RegionPicker({ regions, current, onPick }: RegionPickerProps) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const listId = useId();
  const home = regions[0]?.code;
  const name = (code: string): string => regionLabel(code, t, code === home);
  const codes = regions.map((r) => r.code);
  const { shown, folded } = foldRegions(codes, current);
  const found = [...codes]
    .sort((a, b) => name(a).localeCompare(name(b)))
    .filter((c) => regionMatches(query, name(c), c));

  function pick(code: string): void {
    onPick(code);
    setOpen(false);
    setQuery("");
  }

  return (
    <>
      <div className="mb-2.5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Globe size={13} className="text-white/40" />
          <span className="text-xs font-semibold uppercase tracking-wide text-white/50">
            {t("topup.pickRegion")}
          </span>
        </div>
        {folded > 0 && (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => {
              setOpen((v) => !v);
            }}
            className="flex items-center gap-1 text-xs font-semibold text-[hsl(var(--primary))]"
          >
            {open ? t("topup.regionCollapse") : t("topup.regionAll", { count: codes.length })}
            <ChevronDown
              aria-hidden
              size={12}
              className={`transition-transform ${open ? "rotate-180" : ""}`}
            />
          </button>
        )}
      </div>
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
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
              className={CHIP}
              style={chipStyle(active)}
            >
              <RegionFlag code={code} home={code === home} />
              {name(code)}
            </button>
          );
        })}
      </div>
      {folded > 0 && open && (
        <div
          id={listId}
          className="mt-2.5 rounded-2xl p-2.5"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          <label className="flex items-center gap-2 rounded-xl bg-black/20 px-3">
            <Search aria-hidden size={14} className="shrink-0 text-white/40" />
            <input
              type="search"
              value={query}
              placeholder={t("topup.regionSearch")}
              aria-label={t("topup.regionSearch")}
              onChange={(e) => {
                setQuery(e.target.value);
              }}
              className="min-h-[40px] w-full bg-transparent text-sm text-white outline-none placeholder:text-white/35"
            />
          </label>
          {found.length === 0 ? (
            <p className="px-1 pt-2.5 text-xs text-white/45">{t("topup.regionNone")}</p>
          ) : (
            <ul className="mt-1.5 grid max-h-64 grid-cols-2 gap-0.5 overflow-y-auto">
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
                      className={`flex min-h-[40px] w-full items-center gap-2 rounded-lg px-2 text-left text-[13px] font-medium ${
                        active ? "bg-white/10 text-white" : "text-white/70 active:bg-white/5"
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
