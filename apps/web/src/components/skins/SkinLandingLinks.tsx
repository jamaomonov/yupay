import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { SkinFacets } from "@/lib/skins";

import { pathFor } from "@/lib/seo";
import { categoryPath, isSkinCategory, weaponPath } from "@/lib/skin-landing";

/** How many weapons the hub links to — the most stocked ones. */
const TOP_WEAPONS = 16;

/**
 * The hub's links to its landing pages: every section («Ножи CS2») and the most stocked
 * weapons («Скины AK-47») — how a crawler, and a browsing buyer, reaches them from `/skins`.
 */
export async function SkinLandingLinks({ facets, locale }: { facets: SkinFacets; locale: string }) {
  const t = await getTranslations("web.skins");
  const groups = [
    {
      title: t("landing.categories"),
      links: facets.categories.flatMap((c) =>
        isSkinCategory(c.value)
          ? [
              {
                label: t("landing.categoryH1", { name: t(`category.${c.value}`) }),
                path: categoryPath(c.value),
              },
            ]
          : [],
      ),
    },
    {
      title: t("landing.popular"),
      links: [...facets.weapons]
        .sort((a, b) => b.count - a.count)
        .slice(0, TOP_WEAPONS)
        .map((w) => ({
          label: t("landing.weaponH1", { weapon: w.value }),
          path: weaponPath(w.value),
        })),
    },
  ];
  return (
    <nav
      className="border-border mt-10 space-y-5 border-t pt-6"
      aria-label={t("landing.categories")}
    >
      {groups.map((g) => (
        <div key={g.title}>
          <h2 className="mb-2 text-[15px] font-bold">{g.title}</h2>
          <ul className="flex flex-wrap gap-2">
            {g.links.map((l) => (
              <li key={l.path}>
                <Link
                  href={pathFor(locale, l.path)}
                  className="border-border hover:border-border-2 text-tx-mute hover:text-foreground inline-block rounded-full border px-3 py-1.5 text-[13px]"
                >
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
