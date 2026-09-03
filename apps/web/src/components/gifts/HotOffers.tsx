import { getTranslations } from "next-intl/server";

import { GiftCard } from "./GiftCard";

import type { GiftApp } from "@/lib/gifts";

/**
 * Curated "hot" strip — pinned apps plus the best current discounts, server-
 * fetched and server-rendered (no client JS). Renders nothing when `items`
 * is empty, so a dark deploy (feature flag off → `getGiftsHot` returns `[]`)
 * leaves no empty shell on the page.
 */
export async function HotOffers({ items, locale }: { items: GiftApp[]; locale: string }) {
  if (items.length === 0) return null;
  const t = await getTranslations("web.gifts");

  return (
    <section className="mt-12">
      <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t("hot.title")}</h2>
      <div className="mt-5 flex gap-4 overflow-x-auto pb-2">
        {items.map((app) => (
          <div key={app.app_id} className="w-[180px] shrink-0 sm:w-[210px]">
            <GiftCard app={app} locale={locale} />
          </div>
        ))}
      </div>
    </section>
  );
}
