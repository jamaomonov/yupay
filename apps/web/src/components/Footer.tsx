import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { useId } from "react";

import { Wordmark } from "./Wordmark";

import { getBrands, type BrandSummary } from "@/lib/catalog";
import { pathFor } from "@/lib/seo";

/** Public social channels. Instagram handle yupay.app, Telegram channel
 * yupay_channel (distinct from the @yupay_support contact above). Full-colour
 * brand marks live in public/social. */
/** The affiliate site. Its own host, and configurable so a staging storefront
 *  does not link visitors at production. */
const PARTNERS_URL = process.env.NEXT_PUBLIC_PARTNERS_URL ?? "https://partners.yupay.uz";
/** The B2B wholesale program — a different product from the affiliate site
 *  above: reselling the catalog at wholesale prices, not a 2% referral fee. */
const RESELLER_URL = process.env.NEXT_PUBLIC_RESELLER_URL ?? "https://reseller.yupay.uz";

const SOCIALS = [
  { href: "https://instagram.com/yupay.app", label: "Instagram", src: "/social/instagram.svg" },
  { href: "https://t.me/yupay_channel", label: "Telegram", src: "/social/telegram.svg" },
];

/** Real acquirer marks, each in a small white chip (same treatment as
 * SteamZeroCommission.tsx, scaled down for the footer's bottom bar) so every
 * mark reads on the dark footer regardless of its native background. */
const PAY_METHODS: { src: string; name: string; w: number; h: number }[] = [
  { src: "/payment/click-dark.svg", name: "Click", w: 157, h: 40 },
  { src: "/payment/payme.png", name: "Payme", w: 454, h: 179 },
  { src: "/payment/uzum.png", name: "Uzum", w: 506, h: 148 },
];

export async function Footer({ locale }: { locale: string }) {
  const t = await getTranslations("web.footer");
  const nav = await getTranslations("web.nav");
  const year = new Date().getFullYear();
  // Site-wide links to the brand pages: gives the money pages the same footer
  // reach the legal pages have, so internal authority isn't hoarded by /legal/*.
  let brands: BrandSummary[] = [];
  try {
    brands = await getBrands(locale);
  } catch {
    // API down → skip the games column rather than break the footer.
  }

  return (
    <footer className="border-border border-t pt-[72px]">
      <div className="mx-auto max-w-[1200px] px-6 pb-10 sm:px-10">
        <div className="mb-10 grid grid-cols-2 gap-10 md:grid-cols-3 lg:grid-cols-[1.6fr_1fr_1fr_1fr_1fr]">
          <div className="col-span-2 md:col-span-3 lg:col-span-1">
            <Wordmark />
            <p className="text-tx-mute mt-5 max-w-[300px] text-sm leading-relaxed">
              {t("tagline")}
            </p>
            <p className="text-tx-dim mb-3 mt-6 font-mono text-[11px] font-bold uppercase tracking-[0.16em]">
              {t("followUs")}
            </p>
            <div className="flex items-center gap-3">
              {SOCIALS.map(({ href, label, src }) => (
                <a
                  key={label}
                  href={href}
                  target="_blank"
                  rel="noreferrer noopener"
                  aria-label={label}
                  className="-m-1.5 flex h-11 w-11 items-center justify-center opacity-90 transition hover:opacity-100"
                >
                  <Image src={src} alt={label} width={32} height={32} className="h-8 w-8" />
                </a>
              ))}
            </div>
          </div>

          <FooterCol title={t("productTitle")}>
            <FooterLink href={pathFor(locale, "/store")}>{nav("store")}</FooterLink>
            <FooterLink href={pathFor(locale, "/blog")}>{nav("blog")}</FooterLink>
            <FooterLink href={pathFor(locale, "/store")}>{t("prices")}</FooterLink>
            <FooterLink href={`${pathFor(locale)}#how`}>{nav("how")}</FooterLink>
            {/* Its own domain, so `external` — otherwise Next would treat it as
                an in-app route and prefetch a page that is not part of this
                build. */}
            <FooterLink href={PARTNERS_URL} external>
              {t("partners")}
            </FooterLink>
            <FooterLink href={RESELLER_URL} external>
              {t("wholesale")}
            </FooterLink>
          </FooterCol>

          <FooterCol title={t("helpTitle")}>
            <FooterLink href="https://t.me/yupay_support" external>
              {nav("support")}
            </FooterLink>
            <FooterLink href={pathFor(locale, "/legal/refunds")} prefetch={false}>
              {t("refunds")}
            </FooterLink>
          </FooterCol>

          {/* The legal column sits on every page and is opened by almost nobody,
              so the default viewport prefetch spends a mobile visitor's data on
              five documents they will not read — and the browser cancels those
              requests on navigation, which is what fills the proxy log with
              "aborting with incomplete response". */}
          <FooterCol title={t("legalTitle")}>
            <FooterLink href={pathFor(locale, "/legal/terms")} prefetch={false}>
              {t("terms")}
            </FooterLink>
            <FooterLink href={pathFor(locale, "/legal/agreement")} prefetch={false}>
              {t("agreement")}
            </FooterLink>
            <FooterLink href={pathFor(locale, "/legal/privacy")} prefetch={false}>
              {t("privacy")}
            </FooterLink>
            <FooterLink href={pathFor(locale, "/legal/imprint")} prefetch={false}>
              {t("imprint")}
            </FooterLink>
            <FooterLink href={pathFor(locale, "/legal")} prefetch={false}>
              {t("allDocs")}
            </FooterLink>
          </FooterCol>

          <FooterCol title={t("usTitle")}>
            <FooterLink href="https://t.me/yupay_support" external>
              Telegram
            </FooterLink>
            <FooterLink href="mailto:support@yupay.uz" external>
              Email
            </FooterLink>
          </FooterCol>
        </div>

        {/* Its own strip rather than a sixth column. Seventeen brands stacked
            vertically made the whole footer as tall as its longest column —
            three times what the other five needed — and narrowing that column
            instead only moved the problem: "Arena Breakout: Infinite" and
            "Magic Chess: Go Go" wrap onto two lines well before the height
            comes down. Laid out wide, every name fits on one line and the
            block is four rows.

            Every brand still ships. The column exists so the money pages get
            the same site-wide reach the legal ones have (see below), and
            capping the list at N would spend exactly what it was built for to
            buy back height a layout change gives for free. */}
        {brands.length > 0 && (
          <div className="border-border mb-10 border-t pt-8">
            <FooterCol title={t("gamesTitle")}>
              {/* `break-inside-avoid` on the rows: each link is a 44px flex row, and a
                  column break through one splits the tap target across two
                  columns. */}
              <div className="columns-2 gap-x-8 sm:columns-3 lg:columns-5 [&_a]:break-inside-avoid">
                {brands.map((b) => (
                  <FooterLink key={b.slug} href={pathFor(locale, `/store/${b.slug}`)}>
                    {b.name}
                  </FooterLink>
                ))}
              </div>
            </FooterCol>
          </div>
        )}

        <div className="border-border flex flex-col items-start justify-between gap-4 border-t pt-8 md:flex-row md:items-center">
          <span className="text-tx-mute font-mono text-[12px]">
            {t("copyright", { year })} · <span className="text-tx-mute/70">{t("disclaimer")}</span>
          </span>
          <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
            <div className="flex flex-wrap items-center gap-2.5">
              {PAY_METHODS.map((p) => (
                <span
                  key={p.name}
                  className="flex h-11 w-16 items-center justify-center rounded-lg bg-white p-1.5"
                >
                  <Image
                    src={p.src}
                    alt={p.name}
                    title={p.name}
                    width={p.w}
                    height={p.h}
                    style={{ maxWidth: "100%", maxHeight: "100%", width: "auto", height: "auto" }}
                    className="object-contain"
                  />
                </span>
              ))}
            </div>
            <span className="text-tx-mute font-mono text-[12px]">
              {t("madeBy")}{" "}
              <a
                href="https://t.me/jama_omonov"
                target="_blank"
                rel="noreferrer noopener"
                className="text-tx-mute hover:text-foreground underline-offset-2 transition hover:underline"
              >
                Jam
              </a>
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}

function FooterCol({ title, children }: { title: string; children: React.ReactNode }) {
  // `useId` rather than a slug of the title: the caption is translated, and an
  // id built from it would change per locale.
  const headingId = useId();
  return (
    <nav aria-labelledby={headingId}>
      <p
        id={headingId}
        className="text-tx-dim mb-3 font-mono text-[11px] font-bold uppercase tracking-[0.16em]"
      >
        {title}
      </p>
      {/* Rows are 44px-tall tap targets (min-h), so no extra gap between them. */}
      <div className="flex flex-col">{children}</div>
    </nav>
  );
}

function FooterLink({
  href,
  external,
  // `null` is Next's own default (prefetch on viewport), not `true` — passing
  // `true` would force a *full* route prefetch, the opposite of the intent.
  prefetch = null,
  children,
}: {
  href: string;
  external?: boolean;
  prefetch?: boolean | null;
  children: React.ReactNode;
}) {
  const cls =
    "text-foreground hover:text-primary flex min-h-[44px] items-center text-[13px] font-medium transition";
  if (external) {
    return (
      <a href={href} target="_blank" rel="noreferrer noopener" className={cls}>
        {children}
      </a>
    );
  }
  return (
    <Link href={href} prefetch={prefetch} className={cls}>
      {children}
    </Link>
  );
}
