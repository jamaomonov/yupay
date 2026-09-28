import { wearChoices } from "@yupay/utils";
import Link from "next/link";
import { useTranslations } from "next-intl";

import type { SkinFamilyMember } from "@/lib/skins";

import { pathFor } from "@/lib/seo";

type Current = Pick<SkinFamilyMember, "slug" | "exterior" | "stattrak" | "souvenir">;

/**
 * Wear as one segmented row in plain words, and StatTrak™/Souvenir as toggles —
 * the old grid of «ST · FT» tiles made people decode two things at once. A wear
 * with no copies on sale is shown greyed, not hidden, so the range is visible.
 */
export function SkinWearPicker({
  family,
  current,
  locale,
}: {
  family: SkinFamilyMember[];
  current: Current;
  locale: string;
}) {
  const t = useTranslations("web.skins");
  const c = wearChoices(family, current);
  const href = (slug: string) => pathFor(locale, `/skins/${slug}`);
  const toggles = [
    { label: "StatTrak™", toggle: c.stattrak, tone: "text-orange-400 border-orange-400/60" },
    { label: "Souvenir", toggle: c.souvenir, tone: "text-yellow-400 border-yellow-400/60" },
  ].filter(({ toggle }) => toggle.slug !== null || toggle.on);

  return (
    <div className="space-y-3">
      {c.wears.length > 1 && (
        <div className="border-border bg-card grid grid-cols-2 gap-1 rounded-xl border p-1 sm:flex">
          {c.wears.map((w) => {
            const active = w.slug === current.slug;
            const cls = `flex-1 rounded-lg px-3 py-2 text-center text-[13px] font-semibold transition ${
              active
                ? "bg-primary/15 text-foreground"
                : w.available
                  ? "text-tx-mute hover:bg-muted hover:text-foreground"
                  : "text-tx-dim/60"
            }`;
            const label = t(`exterior.${w.exterior}`);
            return w.slug === null ? (
              <span key={w.exterior} className={`${cls} cursor-not-allowed`}>
                {label}
              </span>
            ) : (
              <Link
                key={w.exterior}
                href={href(w.slug)}
                className={cls}
                aria-current={active ? "page" : undefined}
                aria-disabled={w.available ? undefined : true}
              >
                {label}
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
              href={href(toggle.slug ?? current.slug)}
              aria-current={toggle.on ? "page" : undefined}
              className={`rounded-lg border px-3 py-1.5 text-[13px] font-semibold transition ${
                toggle.on ? tone : "border-border text-tx-mute hover:border-border-2"
              }`}
            >
              {label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
