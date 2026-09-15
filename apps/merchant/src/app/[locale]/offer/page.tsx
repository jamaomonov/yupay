import { readFile } from "node:fs/promises";
import path from "node:path";

import { AlertTriangle } from "lucide-react";
import { getTranslations, setRequestLocale } from "next-intl/server";
import Link from "next/link";

export const revalidate = 3600;

/**
 * The B2B offer a merchant ticks at registration.
 *
 * Rendered from `docs/legal/merchant-offer.ru.md` rather than from the i18n
 * catalogue, because a legal document is versioned prose and not UI strings:
 * the version a merchant accepted is recorded against their user row, so the
 * text must live somewhere a diff can show what changed between versions.
 *
 * It is a **draft**, and says so in a banner nobody can miss. The mechanism —
 * the checkbox, the version, the timestamp — is finished; the words are the
 * owner's to replace. Shipping the mechanism first is deliberate: retrofitting
 * consent onto merchants who registered without it is not possible after the
 * fact.
 */
export default async function OfferPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("merchant.offer");

  const file = path.join(process.cwd(), "../../docs/legal/merchant-offer.ru.md");
  const raw = await readFile(file, "utf8").catch(() => "");
  // Strip the HTML comment and the in-document banner — the page shows its own,
  // and a duplicated warning reads as boilerplate rather than as a warning —
  // then the two markers this document actually uses. Not a markdown parser: a
  // dependency and an XSS surface for nine headings is a bad trade, and the
  // source is ours, not a user's.
  const body = raw
    .replace(/<!--[\s\S]*?-->/g, "")
    .split("\n")
    .filter((line) => !line.startsWith(">") && !line.startsWith("**Версия"))
    .map((line) => line.replace(/^#{1,6}\s+/, "").replace(/\*\*(.+?)\*\*/g, "$1"))
    .join("\n")
    .trim();

  return (
    <main className="mx-auto w-full max-w-3xl px-5 py-16">
      <div className="border-gold/40 bg-gold/10 rounded-xl border p-4">
        <p className="flex items-start gap-2.5 text-sm font-semibold">
          <AlertTriangle size={18} className="text-gold mt-0.5 shrink-0" />
          {t("draftBanner")}
        </p>
      </div>

      <h1 className="mt-8 text-3xl font-bold tracking-tight">{t("title")}</h1>
      <p className="text-tx-dim mt-2 font-mono text-sm">{t("version")}: 2026-09-draft</p>
      {locale !== "ru" && <p className="text-tx-mute mt-2 text-sm">{t("readInRu")}</p>}

      {/* Plain text in a <pre>: rendering untrusted-looking markdown through a
          parser would add a dependency and an XSS surface for a document that
          is three headings and nine paragraphs. */}
      <pre className="text-tx-mute mt-8 whitespace-pre-wrap font-sans text-sm leading-relaxed">
        {body}
      </pre>

      <Link href={`/${locale}/register`} className="text-primary mt-10 inline-block text-sm">
        {t("back")}
      </Link>
    </main>
  );
}
