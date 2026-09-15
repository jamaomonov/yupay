import Link from "next/link";
import { getTranslations } from "next-intl/server";

/** A 404 that belongs to this product rather than to the framework. */
export default async function NotFound() {
  const t = await getTranslations("merchant.common");
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-5 py-12">
      <h1 className="font-display text-2xl font-semibold tracking-tight">{t("notFoundTitle")}</h1>
      <p className="text-tx-mute mt-2 text-sm leading-relaxed">{t("notFoundBody")}</p>
      <Link
        href="/"
        className="bg-primary text-primary-foreground rounded-btn mt-6 self-start px-4 py-2.5 text-sm font-semibold"
      >
        {t("goHome")}
      </Link>
    </main>
  );
}
