import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { buttonStyles } from "@/lib/button";
import { NOINDEX, pathFor } from "@/lib/seo";

/**
 * Where an acquirer lands a customer when nothing told it anywhere better.
 *
 * `payments._safe_return_url` has always defaulted to `{web_base_url}
 * /checkout/return`, and this route did not exist — so every flow that did not
 * pass its own `return_url` finished a real payment on a 404. Checkout passes
 * the order page, so the gap only showed on the ones that could not: the
 * wallet top-up, which now names the balance page, and the mini app, whose own
 * origin the same-origin check would reject.
 *
 * Deliberately vague about the outcome, not just about what was bought: every
 * acquirer sends the customer here when they press *cancel* too, so the one
 * visitor who certainly did not pay must not be told to go wait for an order.
 * The copy covers both, and both destinations are one tap away.
 */
export const metadata: Metadata = { title: "YuPay", robots: NOINDEX };

export default async function CheckoutReturnPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations("web.checkoutReturn");

  return (
    <main className="mx-auto max-w-[560px] px-4 pb-24 pt-[120px] text-center">
      <h1 className="font-display mb-3 text-3xl font-bold tracking-[-0.02em]">{t("title")}</h1>
      <p className="text-tx-mute mb-8 text-[15px] leading-relaxed">{t("body")}</p>
      <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
        <Link
          href={pathFor(locale, "/account/orders")}
          className={buttonStyles({ size: "md", className: "w-full sm:w-auto" })}
        >
          {t("toOrders")}
        </Link>
        <Link
          href={pathFor(locale, "/account/wallet")}
          className={buttonStyles({ variant: "ghost", size: "md", className: "w-full sm:w-auto" })}
        >
          {t("toWallet")}
        </Link>
      </div>
    </main>
  );
}
