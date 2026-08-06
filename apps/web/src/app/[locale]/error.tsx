"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

import { buttonStyles } from "@/lib/button";

/**
 * Locale-level error boundary.
 *
 * Without one, a render failure anywhere under `/[locale]` fell through to
 * Next's built-in screen: unstyled, English, and with no way back into the
 * shop. On a storefront that first-time buyers already approach warily, that
 * looks like the site broke for good.
 */
export default function LocaleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("web.common");

  useEffect(() => {
    // Surfaced to the browser console (and so to Sentry's console
    // integration) — the digest is what ties this to the server-side trace.
    console.error("route error", error.digest ?? error.message);
  }, [error]);

  return (
    <main className="flex min-h-[70vh] items-center justify-center px-6 pt-[120px]">
      <div className="max-w-[420px] text-center">
        <h1 className="font-display text-2xl font-extrabold tracking-[-0.02em]">
          {t("errorTitle")}
        </h1>
        <p className="text-tx-mute mt-3 text-sm leading-relaxed">{t("errorBody")}</p>
        <div className="mt-6 flex flex-col justify-center gap-2.5 sm:flex-row">
          <button type="button" onClick={reset} className={buttonStyles({ size: "md" })}>
            {t("errorRetry")}
          </button>
          <Link href="/" className={buttonStyles({ variant: "ghost", size: "md" })}>
            {t("errorHome")}
          </Link>
        </div>
      </div>
    </main>
  );
}
