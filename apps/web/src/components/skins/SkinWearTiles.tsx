import Link from "next/link";
import { useTranslations } from "next-intl";

import type { SkinFamilyMember } from "@/lib/skins";

import { pathFor } from "@/lib/seo";
import { displayPrice } from "@/lib/skins";

/**
 * One tile per wear (and StatTrak/Souvenir twin) of the same skin: the wear,
 * «от» our price, how many offers. The current one is marked. Sold-out wears
 * stay listed — the customer should see the wear exists.
 */
export function SkinWearTiles({
  family,
  current,
  locale,
}: {
  family: SkinFamilyMember[];
  current: string;
  locale: string;
}) {
  const t = useTranslations("web.skins");
  if (family.length < 2) return null;

  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {family.map((m) => {
        const active = m.slug === current;
        return (
          <li key={m.slug}>
            <Link
              href={pathFor(locale, `/skins/${m.slug}`)}
              aria-current={active ? "page" : undefined}
              className={`block rounded-xl border p-3 transition ${
                active
                  ? "border-primary bg-primary/10"
                  : "border-border bg-card hover:border-border-2"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[13px] font-bold">
                  {m.stattrak && <span className="text-orange-400">ST </span>}
                  {m.souvenir && <span className="text-yellow-400">SV </span>}
                  {m.exterior ?? "—"}
                </span>
                <span className="text-tx-dim font-mono text-[11px]">{m.count}</span>
              </div>
              {m.exterior && (
                <div className="text-tx-dim truncate text-[11px]">
                  {t(`exterior.${m.exterior}`)}
                </div>
              )}
              <div className="mt-1 font-mono text-[13px] font-semibold">
                {(() => {
                  const price = displayPrice(locale, m.price_uzs, m.price_usd);
                  return price !== null ? t("fromPrice", { price }) : t("soldOut");
                })()}
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
