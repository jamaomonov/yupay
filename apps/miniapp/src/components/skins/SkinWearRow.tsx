import { wearChoices } from "@yupay/utils";
import { Link } from "wouter";

import type { SkinFamilyMember } from "@yupay/utils";

import { useT } from "@/lib/i18n";
import { skinPriceText } from "@/lib/skins";

type Current = Pick<SkinFamilyMember, "slug" | "exterior" | "stattrak" | "souvenir">;

const SURFACE = { background: "hsl(var(--surface-2))", borderColor: "hsl(var(--border))" };

/**
 * Wear in plain words with its price, and StatTrak™/Souvenir as toggles. Every
 * tap replaces the route, so back still leaves for the catalogue. A wear with no
 * copies on sale stays visible, greyed.
 */
export function SkinWearRow({ family, current }: { family: SkinFamilyMember[]; current: Current }) {
  const { t } = useT();
  const c = wearChoices(family, current);
  const price = (slug: string | null) => {
    const m = family.find((f) => f.slug === slug);
    return m ? skinPriceText(m.price_uzs, m.price_usd) : null;
  };
  const toggles = [
    { label: "StatTrak™", toggle: c.stattrak, tone: "text-orange-400 border-orange-400/60" },
    { label: "Souvenir", toggle: c.souvenir, tone: "text-yellow-400 border-yellow-400/60" },
  ].filter(({ toggle }) => toggle.slug !== null || toggle.on);

  return (
    <div className="space-y-2">
      {c.wears.length > 1 && (
        <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
          {c.wears.map((w) => {
            const active = w.slug === current.slug;
            const body = (
              <>
                <span className="whitespace-nowrap text-[11px] font-semibold">
                  {t(`cs2.exterior.${w.exterior}`)}
                </span>
                <span className="whitespace-nowrap text-[12px] font-bold tabular-nums text-white">
                  {w.available ? price(w.slug) : t("cs2.soldOut")}
                </span>
              </>
            );
            const cls = `flex shrink-0 flex-col gap-0.5 rounded-xl border px-3 py-2 ${
              active ? "border-primary text-white" : w.available ? "text-white/60" : "text-white/30"
            }`;
            return w.slug === null ? (
              <span key={w.exterior} className={cls} style={SURFACE}>
                {body}
              </span>
            ) : (
              <Link
                key={w.exterior}
                href={`/cs2-market/${w.slug}`}
                replace
                aria-current={active ? "page" : undefined}
                className={cls}
                style={active ? { background: "hsl(var(--primary) / 0.12)" } : SURFACE}
              >
                {body}
              </Link>
            );
          })}
        </div>
      )}
      {toggles.length > 0 && (
        <div className="flex gap-2">
          {toggles.map(({ label, toggle, tone }) => (
            <Link
              key={label}
              href={`/cs2-market/${toggle.slug ?? current.slug}`}
              replace
              aria-pressed={toggle.on}
              className={`rounded-xl border px-3 py-1.5 text-[12px] font-semibold ${
                toggle.on ? tone : "text-white/60"
              }`}
              style={toggle.on ? undefined : SURFACE}
            >
              {label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
