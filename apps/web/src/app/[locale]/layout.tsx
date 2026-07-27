import { Inter, JetBrains_Mono, Unbounded } from "next/font/google";
import { notFound } from "next/navigation";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";

import { Providers } from "./Providers";

import type { Metadata } from "next";

import { LoginModal } from "@/components/auth/LoginModal";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { SupportFab } from "@/components/SupportFab";
import { YandexMetrika } from "@/components/YandexMetrika";
import { routing } from "@/i18n/routing";
import { alternates, localeUrl, ogLocale, SITE } from "@/lib/seo";

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
    robots: { index: true, follow: true },
    // Absolute canonical + hreflang (incl. x-default), ru without a prefix —
    // same helper the store pages use.
    alternates: alternates(locale),
    openGraph: {
      type: "website",
      siteName: "yupay",
      title: t("homeTitle"),
      description: t("homeDescription"),
      url: localeUrl(locale),
      ...ogLocale(locale),
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

  return (
    <html lang={locale} className={`${sans.variable} ${display.variable} ${mono.variable}`}>
      <body className="bg-bg text-foreground min-h-screen font-sans antialiased">
        <YandexMetrika />
        <NextIntlClientProvider locale={locale} messages={messages}>
          <Providers>
            <Header locale={locale} />
            {children}
            <Footer locale={locale} />
            <LoginModal locale={locale} />
            <SupportFab />
          </Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
