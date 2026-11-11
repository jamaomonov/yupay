import Link from "next/link";

import "./globals.css";

/**
 * The 404 for anything outside `[locale]`.
 *
 * Rare: the middleware maps every path onto a locale, and unknown paths under
 * a locale render `[locale]/not-found.tsx` through the `[...rest]` catch-all.
 * What is left is a path the middleware skips — a dotted file that does not
 * exist, an unknown `/og/…`. There is no locale and no layout above this page
 * (the root layout passes children through), so it renders its own document
 * and says the short version in all three languages.
 */
export default function RootNotFound() {
  return (
    <html lang="ru">
      <body className="min-h-dvh">
        <title>404 — YuPay Reseller</title>
        <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-5 py-12">
          <p className="text-tx-dim font-mono text-sm">404</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">
            Страница не найдена · Page not found · Sahifa topilmadi
          </h1>
          <nav className="mt-6 flex flex-col items-start gap-3 text-sm">
            <Link
              href="/"
              className="bg-primary text-primary-foreground rounded-btn px-4 py-2.5 font-semibold"
            >
              YuPay Reseller
            </Link>
            <Link href="/docs" className="text-primary-ink font-semibold">
              Документация · Docs
            </Link>
            <a href="https://t.me/yupay_support" className="text-primary-ink font-semibold">
              Telegram: @yupay_support
            </a>
          </nav>
        </main>
      </body>
    </html>
  );
}
