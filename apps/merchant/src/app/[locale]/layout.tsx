import { Inter, JetBrains_Mono, Unbounded } from "next/font/google";
import { notFound } from "next/navigation";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { routing } from "@/i18n/routing";
import { alternates, localeUrl, ogLocale, SITE } from "@/lib/seo";
import { THEME_BOOTSTRAP } from "@/lib/theme";

import "../globals.css";

// Self-hosted by next/font, so there is no runtime request to Google and no
// layout shift. The same three faces and the same variable names the
// storefront uses — a reseller signing in should recognise the product.
const sans = Inter({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--app-font-sans",
  display: "swap",
});

const display = Unbounded({
  // Cyrillic subset included: RU and UZ headings keep the display face, which
  // is where the whole visual contrast lives.
  subsets: ["latin", "cyrillic"],
  weight: ["500", "600", "700"],
  variable: "--app-font-display",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "700"],
  variable: "--app-font-mono",
  display: "swap",
});

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "merchant.meta" });
  return {
    // Absolute base so every relative metadata URL (alternates, OG) resolves
    // to https://reseller.yupay.uz/... — search consoles reject relative
    // hreflang/canonical.
    metadataBase: new URL(SITE),
    title: t("title"),
    description: t("description"),
    // Absolute canonical + hreflang (incl. x-default), ru without a prefix.
    alternates: alternates(locale),
    openGraph: {
      type: "website",
      siteName: "YuPay",
      url: localeUrl(locale),
      ...ogLocale(locale),
    },
    // No blanket `robots` here any more: the cabinet layout sets `NOINDEX`,
    // the auth-screen layouts do too (see `login/layout.tsx` and its
    // siblings), and every indexable page sets `ROBOTS` itself — see
    // `lib/seo.ts`. Inheriting `index: true` here previously meant every
    // route was indexable by default, cabinet included, until its own
    // layout overrode it.
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

  return (
    <html
      lang={locale}
      suppressHydrationWarning
      className={`${sans.variable} ${display.variable} ${mono.variable}`}
    >
      <head>
        {/* Before first paint — see THEME_BOOTSTRAP for why this cannot be a
            React effect. `suppressHydrationWarning` above is the cost: the
            server cannot know which theme the browser will pick. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="min-h-dvh">
        <NextIntlClientProvider messages={messages}>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
