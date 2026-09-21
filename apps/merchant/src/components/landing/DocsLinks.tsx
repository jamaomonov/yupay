import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { pathFor } from "@/lib/locale-href";
import { OPENAPI_URL } from "@/lib/seo";

/**
 * The way into the documentation, on every marketing page that offers one.
 *
 * One component because the landing and `/api` carried the same markup
 * twice, and it had the same defect twice: the accent — bold, coloured, first
 * in the row — was on the **raw OpenAPI JSON**, with the four pages a person
 * actually reads set beside it as plain grey 13px text. That is backwards for
 * everybody except the reader who was going to find the spec anyway. A
 * developer arriving on this page wants «как подписать запрос», not a 90 KB
 * document their browser renders as one line.
 *
 * So: a real button to the reference, the four pages under it, and the spec
 * last and dim — still there, because a client generator needs it, and no
 * longer the loudest thing in the block.
 */
export async function DocsLinks({ locale }: { locale: string }) {
  const t = await getTranslations("merchant.landing");
  const pages = [
    { href: "/docs/quickstart", label: t("devQuickstart") },
    { href: "/docs/authentication", label: t("devAuth") },
    { href: "/docs/webhooks", label: t("devWebhooks") },
    { href: "/docs/errors", label: t("devErrors") },
  ];

  return (
    <div className="mt-6">
      <Link
        href={pathFor(locale, "/docs")}
        className="bg-primary text-primary-foreground rounded-btn inline-flex items-center gap-2 px-5 py-3 text-sm font-semibold"
      >
        {t("devDocsCta")}
        <ArrowRight size={16} />
      </Link>
      <div className="text-tx-mute mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px]">
        {pages.map(({ href, label }) => (
          <Link
            key={href}
            href={pathFor(locale, href)}
            className="underline-offset-4 hover:underline"
          >
            {label}
          </Link>
        ))}
        <a href={OPENAPI_URL} className="text-tx-dim">
          {t("devSpec")}
        </a>
      </div>
    </div>
  );
}
