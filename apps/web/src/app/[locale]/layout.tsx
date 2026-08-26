import { Inter, JetBrains_Mono, Unbounded } from "next/font/google";
import { notFound } from "next/navigation";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";

import { Providers } from "./Providers";

import type { Metadata } from "next";

import { LoginModal } from "@/components/auth/LoginModal";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { JsonLd } from "@/components/JsonLd";
import { OrderDeliveredModal } from "@/components/order/OrderDeliveredModal";
import { SkipLink } from "@/components/SkipLink";
import { SupportFab } from "@/components/SupportFab";
import { YandexMetrika } from "@/components/YandexMetrika";
import { routing } from "@/i18n/routing";
import { apiPreconnectOrigin } from "@/lib/preconnect";
import { alternates, localeUrl, ogLocale, ROBOTS, SITE } from "@/lib/seo";

import "../globals.css";

const sans = Inter({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700", "800", "900"],
  variable: "--app-font-sans",
  display: "swap",
});

const display = Unbounded({
  // Unbounded ships a Cyrillic subset, so RU/UZ headlines keep the same
  // distinctive display face as EN — preserving the display-vs-body contrast
  // the visual system is built on (Inter handles body in all locales).
  subsets: ["latin", "cyrillic"],
  weight: ["500", "600", "700", "800"],
  variable: "--app-font-display",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin", "cyrillic"],
  weight: ["500", "700"],
  variable: "--app-font-mono",
  display: "swap",
});

/** Social share image, 1200×630. */
const OG_IMAGE = "/og.png";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};
  setRequestLocale(locale);
  const t = await getTranslations("web.meta");
  return {
    // Absolute base so every relative metadata URL (alternates, OG) resolves to
    // https://yupay.uz/... — search consoles reject relative hreflang/canonical.
    metadataBase: new URL(SITE),
    title: { template: "%s — yupay", default: t("homeTitle") },
    description: t("homeDescription"),
    robots: ROBOTS,
    // Absolute canonical + hreflang (incl. x-default), ru without a prefix —
    // same helper the store pages use.
    alternates: alternates(locale),
    openGraph: {
      type: "website",
      siteName: "YuPay",
      title: t("homeTitle"),
      description: t("homeDescription"),
      url: localeUrl(locale),
      // Resolved against metadataBase above.
      images: [{ url: OG_IMAGE, width: 1200, height: 630 }],
      ...ogLocale(locale),
    },
    twitter: {
      card: "summary_large_image",
      title: t("homeTitle"),
      description: t("homeDescription"),
      images: [OG_IMAGE],
    },
  };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  setRequestLocale(locale);
  const messages = await getMessages();

  // Site-wide structured data (there is none on `/` otherwise). Organization
  // identifies the brand; WebSite lets search engines attach a sitelinks box.
  const organizationLd = {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "YuPay",
    url: SITE,
    logo: `${SITE}/logo/icon.svg`,
    description:
      "Сервис пополнения игровых валют, подписок, лицензий, гифт-карт и цифровых кодов в Узбекистане, России и СНГ за сумы, по игровому ID или логину.",
    // Entity-resolution signals: where we operate, what we accept, and in which
    // languages — so Google and AI assistants can recognise YuPay as a
    // legitimate, well-scoped service (trust / CITE).
    areaServed: ["UZ", "RU", "KZ"],
    knowsLanguage: ["ru", "uz", "en"],
    currenciesAccepted: "UZS",
    paymentAccepted: "Uzcard, Humo, Click, Payme, Uzum",
    sameAs: [
      "https://instagram.com/yupay.app",
      "https://t.me/yupay_channel",
      "https://t.me/yupayapp_bot",
    ],
    contactPoint: {
      "@type": "ContactPoint",
      contactType: "customer support",
      email: "support@yupay.uz",
      availableLanguage: ["ru", "uz", "en"],
    },
  };
  const websiteLd = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "YuPay",
    alternateName: "yupay",
    url: SITE,
  };

  // Opened while the document is still parsing, so the first API call doesn't
  // pay for the handshake itself. `crossOrigin="anonymous"` is not decoration:
  // the connection pool is keyed by credentials mode, and the call this hint
  // exists for — GET /payments/providers on every product page — is a plain
  // cross-origin fetch that sends none. A credentialed hint would sit unused
  // beside a second connection.
  const apiOrigin = apiPreconnectOrigin(SITE);

  return (
    <html
      lang={locale === "uz" ? "uz-Latn" : locale}
      className={`${sans.variable} ${display.variable} ${mono.variable}`}
    >
      {apiOrigin && <link rel="preconnect" href={apiOrigin} crossOrigin="anonymous" />}
      {/* Metrika's tag.js is 111 KB gzipped — the heaviest asset on the page,
          heavier than any first-party chunk — and it comes from an origin the
          browser has never spoken to. Measured cold from outside: 1.4s to first
          byte, most of it DNS + TCP + TLS. The counter is injected async by the
          inline snippet below, so the handshake only starts once the parser
          reaches it; this hint moves it to the head of the load, in parallel
          with the document. Production only, matching <YandexMetrika />, so dev
          does not open a connection to a counter it never reports to. */}
      {process.env.NODE_ENV === "production" && (
        <link rel="preconnect" href="https://mc.yandex.ru" crossOrigin="anonymous" />
      )}
      <body className="bg-bg text-foreground min-h-screen font-sans antialiased">
        <JsonLd data={organizationLd} />
        <JsonLd data={websiteLd} />
        <YandexMetrika />
        <NextIntlClientProvider locale={locale} messages={messages}>
          <Providers>
            {/* First focusable element on every page: the header plus the
                21-link footer sit between the top of the document and the
                content, and there was no way past them by keyboard. */}
            <SkipLink />
            <Header locale={locale} />
            {children}
            <Footer locale={locale} />
            <LoginModal locale={locale} />
            <OrderDeliveredModal />
            <SupportFab />
          </Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
