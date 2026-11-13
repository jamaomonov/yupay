import type { Metadata } from "next";

import { getTranslations } from "next-intl/server";

/** A tab title of its own: the client page cannot export metadata, and without
 *  this the tab read as the home page (2026-11-13 review). */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; orderId: string }>;
}): Promise<Metadata> {
  const { locale, orderId } = await params;
  const t = await getTranslations({ locale, namespace: "web.orders" });
  return { title: t("fallbackTitle", { id: orderId.slice(0, 8) }) };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
