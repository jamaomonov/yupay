import Image from "next/image";
import Link from "next/link";
import { useTranslations } from "next-intl";

import type { GiftApp } from "@/lib/gifts";

import { isOptimizable } from "@/lib/image";
import { formatUzs, pathFor } from "@/lib/seo";

/**
 * One catalog row — cover art, name, editions/DLC counters, discount badge,
 * UZS price. Links straight to the game page Task 9 adds at
 * `/store/steam-gifts/{app_id}`.
 *
 * No `"use client"`: `useTranslations` from `next-intl` (not
 * `next-intl/server`) resolves through the package's `react-server` export
 * condition when this renders inside a Server Component (`HotOffers`, the
 * page itself) and through the normal client runtime when it renders inside
 * `GiftsBrowser` ("use client") — same component, either tree.
 */
export function GiftCard({ app, locale }: { app: GiftApp; locale: string }) {
  const t = useTranslations("web.gifts");
  // `web.store.from` ("от"/"from"/"dan") is `PurchasePanel`'s and the brand
  // hero's established "starting at" label — reused rather than forking a
  // second translation of the same word into this namespace.
  const ts = useTranslations("web.store");
  const discount =
    app.discount_percent != null && app.discount_percent > 0 ? app.discount_percent : null;
  const priceUzs =
    app.price_uzs != null ? formatUzs(locale, Math.round(Number(app.price_uzs))) : null;

  return (
    <Link
      href={pathFor(locale, `/store/steam-gifts/${String(app.app_id)}`)}
      className="border-border bg-card hover:border-border-2 group flex h-full flex-col overflow-hidden rounded-xl border transition hover:-translate-y-1"
    >
      <div className="bg-muted relative aspect-[16/9] w-full overflow-hidden">
        {app.image ? (
          <Image
            src={app.image}
            alt={app.name}
            fill
            unoptimized={!isOptimizable(app.image)}
            sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 220px"
            className="object-cover transition duration-500 group-hover:scale-[1.04]"
          />
        ) : null}
        {discount !== null && (
          <span className="bg-primary text-primary-foreground absolute right-2 top-2 rounded-full px-2 py-1 text-[11px] font-bold">
            {t("badge.discount", { percent: discount })}
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <div className="line-clamp-2 text-[13px] font-semibold leading-snug">{app.name}</div>
        {/* A single edition with no DLC ("1 издание · 0 DLC") is true of
            almost every card in the catalog — printed on every one of them
            it's noise, not information. Only worth a line once there is
            something to actually choose between (2026-09-04 review). */}
        {(app.packages_count > 1 || app.dlc_count > 0) && (
          <div className="text-tx-dim text-[11px]">
            {t("card.editions", { count: app.packages_count })}
            {" · "}
            {t("card.dlc", { count: app.dlc_count })}
          </div>
        )}
        {priceUzs !== null && (
          // "от" ("from"/"dan") — this row is the *default-zone reference*
          // price (`gifts/routes.py`), never the per-package, per-country
          // figure the game page actually charges. Without the prefix a
          // buyer taps in at 1 250 000 and lands on 1 410 000, which reads
          // as bait (2026-09-04 review).
          <div className="mt-auto flex items-baseline gap-1 pt-1.5">
            <span className="text-tx-dim font-sans text-[11px] font-semibold">{ts("from")}</span>
            <span className="font-mono text-[14px] font-bold">{priceUzs}</span>
          </div>
        )}
      </div>
    </Link>
  );
}
