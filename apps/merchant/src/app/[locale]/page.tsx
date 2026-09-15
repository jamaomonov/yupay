import { ArrowRight, Braces, KeyRound, ShoppingCart, UserPlus } from "lucide-react";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { CodeWindow } from "@/components/CodeWindow";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { countBrands } from "@/lib/brands";
import { pathFor } from "@/lib/locale-href";

export const revalidate = 3600;

/** The window's title: the request the body below belongs to. */
const SNIPPET_TITLE = "POST /merchant/v1/orders";

/** Kept verbatim rather than built from strings: it is a code sample, and the
 *  moment it is templated somebody will template a field name too. */
const SNIPPET = `{
  "merchant_order_id": "shop-10482",
  "sku_id": "01a042ce-7bf4-...",
  "expected_price": "8.91",
  "fulfillment_data": { "player_id": "1313232551" }
}

201 -> { "status": "paid", "price_usd": "8.91" }`;

export default async function Landing({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.landing");
  const tOffer = await getTranslations("merchant.offer");
  const brands = await countBrands();

  const steps = [
    { icon: UserPlus, title: t("step1Title"), body: t("step1Body") },
    { icon: KeyRound, title: t("step2Title"), body: t("step2Body") },
    { icon: ShoppingCart, title: t("step3Title"), body: t("step3Body") },
  ];

  return (
    <>
      <header className="border-border border-b">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-4 px-5 py-4">
          <span className="flex items-center gap-2.5">
            <Mark />
            <span className="font-display text-[15px] font-semibold tracking-[0.02em]">
              YUPAY <span className="text-tx-dim font-sans text-xs font-medium">reseller</span>
            </span>
          </span>
          <nav className="text-tx-mute flex flex-wrap items-center gap-5 text-[13.5px]">
            <LocaleSwitcher />
            <Link href={pathFor(locale, "/docs")}>{t("navDocs")}</Link>
            <Link
              href={pathFor(locale, "/login")}
              className="border-border rounded-btn text-foreground border px-4 py-2 font-semibold"
            >
              {t("login")}
            </Link>
            <Link
              href={pathFor(locale, "/register")}
              className="bg-primary text-primary-foreground rounded-btn px-4 py-2 font-bold"
            >
              {t("ctaPrimary")}
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-5 py-16 sm:py-20">
        <section className="grid items-center gap-10 lg:grid-cols-[1fr_26rem]">
          <div>
            <h1 className="max-w-3xl text-4xl font-bold leading-tight tracking-tight sm:text-5xl">
              {t("heading")}
            </h1>
            <p className="text-tx-mute mt-5 max-w-2xl text-lg leading-relaxed">{t("subheading")}</p>
            <div className="text-tx-dim mt-6 flex flex-wrap gap-x-6 gap-y-2 text-[12.5px]">
              {/* Brands, never SKUs — the landing-copy rule. A count of
                  denominations reads as inventory padding and is not what a
                  reseller is choosing between. Omitted entirely when the
                  catalog cannot be reached: a made-up number on a page about
                  wholesale is worse than no number. */}
              {brands !== null && (
                <span>
                  <span className="text-primary-ink font-mono">{brands}+</span> {t("metricBrands")}
                </span>
              )}
              <span>
                <span aria-hidden="true" className="text-primary-ink">
                  ●
                </span>{" "}
                {t("metricAuto")}
              </span>
              <span>
                <span className="text-primary-ink font-mono">USD</span> {t("metricUsd")}
              </span>
            </div>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href={pathFor(locale, "/register")}
                className="bg-primary text-primary-foreground rounded-btn inline-flex items-center gap-2 px-5 py-3 text-sm font-semibold"
              >
                {t("ctaPrimary")}
                <ArrowRight size={16} />
              </Link>
              <Link
                href={pathFor(locale, "/docs")}
                className="border-border rounded-btn inline-flex items-center border px-5 py-3 text-sm font-semibold"
              >
                {t("ctaSecondary")}
              </Link>
            </div>
          </div>

          {/* The request a reseller's server will actually make. It is the
            fastest way to answer "what is this" for the person deciding, and
            it is real — the field names are the ones `POST /merchant/v1/orders`
            takes. */}
          <CodeWindow icon={Braces} title={SNIPPET_TITLE}>
            <pre
              tabIndex={0}
              role="region"
              aria-label={SNIPPET_TITLE}
              className="text-tx-mute overflow-x-auto p-5 font-mono text-[12.5px] leading-[1.75]"
            >
              <code>{SNIPPET}</code>
            </pre>
          </CodeWindow>
        </section>

        <section className="mt-20">
          <h2 className="text-2xl font-semibold tracking-tight">{t("stepsHeading")}</h2>
          <ol className="mt-7 grid gap-4 sm:grid-cols-3">
            {steps.map(({ icon: Icon, title, body }, index) => (
              <li key={title} className="border-border bg-card rounded-xl border p-5">
                <div className="text-primary-ink flex items-center gap-2">
                  <Icon size={18} />
                  <span className="font-mono text-xs">{String(index + 1).padStart(2, "0")}</span>
                </div>
                <h3 className="mt-3 font-semibold">{title}</h3>
                <p className="text-tx-mute mt-2 text-sm leading-relaxed">{body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="mt-20">
          <h2 className="text-2xl font-semibold tracking-tight">{t("sectionsHeading")}</h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            {[
              { name: t("sectionTopups"), body: t("sectionTopupsBody"), soon: false },
              { name: t("sectionVouchers"), body: t("sectionVouchersBody"), soon: false },
              { name: t("sectionGifts"), body: t("sectionGiftsBody"), soon: true },
            ].map(({ name, body, soon }) => (
              // No `opacity` on the "soon" card: it multiplies against
              // `tx-dim`/`tx-mute`, which pass AA on their own, and dropped
              // the badge to 2.74:1 and the copy to 3.96:1 — the one
              // dark-theme text failure in the app, and the kind pure token
              // maths never catches. The badge and the dimmer ground already
              // say "not yet".
              <div
                key={name}
                className={`rounded-xl border p-5 ${soon ? "border-border bg-card-2" : "border-border bg-card"}`}
              >
                <p className="flex flex-wrap items-center gap-2.5 font-semibold">
                  {name}
                  {soon && (
                    <span className="border-border text-tx-dim rounded-full border px-2 py-0.5 text-[10.5px] font-bold tracking-[0.06em]">
                      {t("soon")}
                    </span>
                  )}
                </p>
                <p className="text-tx-mute mt-2 text-[13px] leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="border-border bg-card mt-20 rounded-2xl border p-8">
          <h2 className="text-xl font-semibold tracking-tight">{t("supportHeading")}</h2>
          <p className="text-tx-mute mt-2 text-sm">{t("supportBody")}</p>
          <a
            href="https://t.me/yupay_support"
            className="border-border rounded-btn mt-5 inline-flex items-center border px-4 py-2.5 text-sm font-semibold"
          >
            {t("supportCta")}
          </a>
        </section>
      </main>

      <footer className="border-border text-tx-dim mx-auto mt-16 flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 border-t px-5 py-7 text-xs">
        <span>© YuPay · reseller.yupay.uz</span>
        <span className="flex gap-4">
          <Link href={pathFor(locale, "/offer")}>{tOffer("title")}</Link>
          <a href="https://t.me/yupay_support">{t("supportCta")}</a>
        </span>
      </footer>
    </>
  );
}

/** The storefront's mark. */
function Mark() {
  return (
    <svg width="20" height="18" viewBox="0 0 471.8 426.26" aria-hidden className="text-primary-ink">
      <path
        fill="currentColor"
        d="M0.06 23.83l0 294.05c0,0 -5.53,87.63 88.85,108.37l230.68 0c0,0 68.19,-17.67 80.63,-88.17l0 -210.84 71.58 0 -57.83 -63.63 -57.83 -63.63 -57.83 63.63 -57.83 63.63 71.57 0 0 183.78c0,0 -5.1,27.06 -30.74,27.06l-167.01 0c0,0 -26.08,-1.43 -26.08,-20.21l0 -294.05 -88.17 0z"
      />
    </svg>
  );
}
