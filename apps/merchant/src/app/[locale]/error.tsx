"use client";

import { useTranslations } from "next-intl";
import { useEffect } from "react";

/**
 * What a client-side exception looks like, instead of what it looked like.
 *
 * Without this file Next renders its own unbranded black page reading
 * "Application error: a client-side exception has occurred", with no wordmark,
 * no link home and no way back — on a cabinet a reseller pays to use. One
 * exception during the UI review produced exactly that.
 */
export default function CabinetError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("merchant.common");

  useEffect(() => {
    // The digest is what correlates this with the server log; the message
    // itself may carry a customer's own data, so it is not printed.
    console.error("merchant.render_failed", error.digest ?? "no-digest");
  }, [error]);

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-5 py-12">
      <h1 className="font-display text-2xl font-semibold tracking-tight">{t("errorTitle")}</h1>
      <p className="text-tx-mute mt-2 text-sm leading-relaxed">{t("errorBody")}</p>
      <button
        type="button"
        onClick={reset}
        className="bg-primary text-primary-foreground rounded-btn mt-6 self-start px-4 py-2.5 text-sm font-semibold"
      >
        {t("errorRetry")}
      </button>
    </main>
  );
}
