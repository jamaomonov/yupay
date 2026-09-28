import { Link } from "wouter";

import type { SkinFamilyMember } from "@yupay/utils";

import { useT } from "@/lib/i18n";
import { skinPriceText } from "@/lib/skins";
import { familyLabel } from "@/lib/skins-view";

/** Every wear and StatTrak/Souvenir twin of this skin; the current one is outlined.
 *  A tap replaces the route, so back still leaves for the catalogue. */
export function SkinWearRow({ family, current }: { family: SkinFamilyMember[]; current: string }) {
  const { t } = useT();
  return (
    <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4">
      {family.map((m) => {
        const active = m.slug === current;
        return (
          <Link
            key={m.slug}
            href={`/cs2-market/${m.slug}`}
            replace
            aria-current={active ? "page" : undefined}
            className={`flex w-[104px] shrink-0 flex-col gap-0.5 rounded-xl border px-2.5 py-2 ${
              active ? "border-primary" : ""
            }`}
            style={{
              background: "hsl(var(--surface-2))",
              ...(active ? {} : { borderColor: "hsl(var(--border))" }),
            }}
          >
            <span
              className={`font-mono text-[11px] font-semibold ${
                m.stattrak ? "text-orange-400" : m.souvenir ? "text-yellow-400" : "text-white/60"
              }`}
            >
              {familyLabel(m)}
            </span>
            <span className="font-mono text-[12px] font-bold text-white">
              {skinPriceText(m.price_uzs, m.price_usd) ?? (
                <span className="font-sans text-[11px] font-normal text-white/50">
                  {t("cs2.soldOut")}
                </span>
              )}
            </span>
          </Link>
        );
      })}
    </div>
  );
}
