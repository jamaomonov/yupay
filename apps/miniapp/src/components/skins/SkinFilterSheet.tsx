import { EXTERIORS } from "@yupay/utils";
import { activeFilterCount } from "@yupay/utils";
import { SlidersHorizontal } from "lucide-react";
import { useState } from "react";

import type { Exterior, SkinFacets, SkinQuery, SkinQueryPatch } from "@yupay/utils";

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useT } from "@/lib/i18n";

const FIELD = { background: "hsl(var(--surface-2))", border: "1px solid hsl(var(--border))" };

interface Draft {
  exterior: Exterior | undefined;
  rarity: string | undefined;
  stattrak: boolean;
  min: string;
  max: string;
}

function draftOf(q: SkinQuery): Draft {
  return {
    exterior: q.exterior,
    rarity: q.rarity,
    stattrak: q.stattrak === true,
    min: q.minUzs === undefined ? "" : String(q.minUzs),
    max: q.maxUzs === undefined ? "" : String(q.maxUzs),
  };
}

/** Whole soʻm, digits only; anything else is "no bound". */
function bound(text: string): number | undefined {
  const digits = text.replace(/\s/g, "");
  return /^\d{1,12}$/.test(digits) ? Number(digits) : undefined;
}

const CLEARED: SkinQueryPatch = {
  exterior: undefined,
  rarity: undefined,
  stattrak: undefined,
  minUzs: undefined,
  maxUzs: undefined,
};

/** Wear, rarity, StatTrak and price, applied together from a bottom sheet. */
export function SkinFilterSheet({
  query,
  facets,
  onChange,
}: {
  query: SkinQuery;
  facets: SkinFacets | undefined;
  onChange: (patch: SkinQueryPatch) => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => draftOf(query));
  const count = activeFilterCount(query);
  const set = (patch: Partial<Draft>) => {
    setDraft((d) => ({ ...d, ...patch }));
  };

  function apply(): void {
    onChange({
      exterior: draft.exterior,
      rarity: draft.rarity,
      stattrak: draft.stattrak || undefined,
      minUzs: bound(draft.min),
      maxUzs: bound(draft.max),
    });
    setOpen(false);
  }

  const pill = (active: boolean) =>
    `rounded-xl border px-3 py-1.5 text-[12px] font-semibold ${
      active ? "border-primary text-white" : "text-white/60"
    }`;

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <button
        type="button"
        // The draft restarts from the URL on every open: Radix never reports an
        // open we set ourselves, and a draft left over from a closed-without-
        // applying sheet (or from before «Сбросить») would be re-applied.
        onClick={() => {
          setDraft(draftOf(query));
          setOpen(true);
        }}
        className="flex shrink-0 items-center gap-1.5 rounded-xl px-3 py-2.5 text-sm font-semibold text-white"
        style={FIELD}
      >
        <SlidersHorizontal size={15} aria-hidden="true" />
        {t("cs2.filters")}
        {count > 0 && (
          <span className="bg-primary rounded-full px-1.5 text-[11px] font-bold text-black">
            {count}
          </span>
        )}
      </button>
      <SheetContent
        side="bottom"
        className="max-h-[85vh] rounded-t-3xl"
        aria-describedby={undefined}
        // Focusing the close button on open drew a lime ring on it for no reason.
        onOpenAutoFocus={(e) => {
          e.preventDefault();
        }}
      >
        <SheetHeader>
          <SheetTitle>{t("cs2.filters")}</SheetTitle>
        </SheetHeader>
        <div className="mt-4 space-y-5">
          <fieldset>
            <legend className="mb-2 text-xs font-semibold text-white/60">{t("cs2.wear")}</legend>
            <div className="flex flex-wrap gap-2">
              {EXTERIORS.map((e) => (
                <button
                  key={e}
                  type="button"
                  aria-pressed={draft.exterior === e}
                  className={pill(draft.exterior === e)}
                  style={draft.exterior === e ? undefined : FIELD}
                  onClick={() => {
                    set({ exterior: draft.exterior === e ? undefined : e });
                  }}
                >
                  {t(`cs2.exterior.${e}`)}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend className="mb-2 text-xs font-semibold text-white/60">{t("cs2.price")}</legend>
            <div className="flex gap-2">
              {(["min", "max"] as const).map((k) => (
                <input
                  key={k}
                  inputMode="numeric"
                  aria-label={`${t("cs2.price")} — ${t(k === "min" ? "cs2.from" : "cs2.to")}`}
                  placeholder={t(k === "min" ? "cs2.from" : "cs2.to")}
                  value={draft[k]}
                  onChange={(e) => {
                    set({ [k]: e.target.value });
                  }}
                  className="placeholder:text-body-faint w-full rounded-xl px-3 py-2.5 text-sm text-white outline-none"
                  style={FIELD}
                />
              ))}
            </div>
          </fieldset>
          <button
            type="button"
            role="switch"
            aria-checked={draft.stattrak}
            onClick={() => {
              set({ stattrak: !draft.stattrak });
            }}
            className="flex w-full items-center justify-between text-sm text-white"
          >
            {t("cs2.stattrak")}
            <span
              className={`relative h-6 w-10 rounded-full transition ${draft.stattrak ? "bg-primary" : ""}`}
              style={draft.stattrak ? undefined : { background: "hsl(var(--border))" }}
            >
              <span
                className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${draft.stattrak ? "left-[18px]" : "left-0.5"}`}
              />
            </span>
          </button>
          {facets && facets.rarities.length > 0 && (
            <fieldset>
              <legend className="mb-2 text-xs font-semibold text-white/60">
                {t("cs2.rarity")}
              </legend>
              <div className="flex flex-wrap gap-2">
                {facets.rarities.map(({ value, color }) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={draft.rarity === value}
                    className={pill(draft.rarity === value)}
                    style={draft.rarity === value ? undefined : FIELD}
                    onClick={() => {
                      set({ rarity: draft.rarity === value ? undefined : value });
                    }}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: color ?? "currentColor" }}
                        aria-hidden="true"
                      />
                      {value}
                    </span>
                  </button>
                ))}
              </div>
            </fieldset>
          )}
          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={() => {
                onChange(CLEARED);
                setOpen(false);
              }}
              className="flex-1 rounded-xl py-3 text-sm font-semibold text-white/70"
              style={FIELD}
            >
              {t("cs2.reset")}
            </button>
            <button
              type="button"
              onClick={apply}
              className="bg-primary flex-1 rounded-xl py-3 text-sm font-bold text-black"
            >
              {t("cs2.apply")}
            </button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
