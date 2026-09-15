import { Inter, JetBrains_Mono, Unbounded } from "next/font/google";
import { notFound } from "next/navigation";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server";

import type { Metadata } from "next";

import { routing } from "@/i18n/routing";
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
    title: t("title"),
    description: t("description"),
    // The cabinet must never be indexed; the landing is handled per route.
    robots: { index: true, follow: true },
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
