import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Wordmark } from "./Wordmark";

import { pathFor } from "@/lib/seo";

/** Public social channels. Instagram handle yupay.app, Telegram channel
 * yupay_channel (distinct from the @yupay_support contact above). Full-colour
 * brand marks live in public/social. */
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

  return (
    <footer className="border-border border-t pt-[72px]">
      <div className="mx-auto max-w-[1200px] px-6 pb-10 sm:px-10">
        <div className="mb-14 grid grid-cols-2 gap-10 md:grid-cols-[2fr_1fr_1fr_1fr_1fr]">
          <div className="col-span-2 md:col-span-1">
            <Wordmark />
            <p className="text-tx-mute mt-5 max-w-[300px] text-sm leading-relaxed">
              {t("tagline")}
            </p>
            <h4 className="text-tx-dim mb-3 mt-6 font-mono text-[11px] font-bold uppercase tracking-[0.16em]">
              {t("followUs")}
            </h4>
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
                  <Image
                    src={src}
                    alt={label}
                    width={32}
                    height={32}
                    unoptimized
                    className="h-8 w-8"
                  />
                </a>
              ))}
            </div>
          </div>

          <FooterCol title={t("productTitle")}>
            <FooterLink href={pathFor(locale, "/store")}>{nav("store")}</FooterLink>
            <FooterLink href={pathFor(locale, "/store")}>{t("prices")}</FooterLink>
            <FooterLink href="#how">{nav("how")}</FooterLink>
          </FooterCol>

          <FooterCol title={t("helpTitle")}>
            <FooterLink href="https://t.me/yupay_support" external>
              {nav("support")}
            </FooterLink>
            <FooterLink href={pathFor(locale, "/legal/refunds")}>{t("refunds")}</FooterLink>
          </FooterCol>

          <FooterCol title={t("legalTitle")}>
            <FooterLink href={pathFor(locale, "/legal/terms")}>{t("terms")}</FooterLink>
            <FooterLink href={pathFor(locale, "/legal/privacy")}>{t("privacy")}</FooterLink>
            <FooterLink href={pathFor(locale, "/legal/imprint")}>{t("imprint")}</FooterLink>
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
                    unoptimized
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
  return (
    <div>
      <h4 className="text-tx-dim mb-3 font-mono text-[11px] font-bold uppercase tracking-[0.16em]">
        {title}
      </h4>
      {/* Rows are 44px-tall tap targets (min-h), so no extra gap between them. */}
      <div className="flex flex-col">{children}</div>
    </div>
  );
}

function FooterLink({
  href,
  external,
  children,
}: {
  href: string;
  external?: boolean;
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
    <Link href={href} className={cls}>
      {children}
    </Link>
  );
}
