import { notFound } from "next/navigation";

/**
 * Every path no route under `[locale]` claims, sent to the localized 404.
 *
 * Without it Next answered `/some-missing-page` with its own bare English
 * «This page could not be found» — no header, no footer, no way back — because
 * `[locale]/not-found.tsx` only catches `notFound()` thrown *inside* the
 * segment, and an unmatched URL never enters it (2026-11-13 review). The
 * standard next-intl catch-all; static and dynamic routes still win over it.
 */
export default function CatchAll(): never {
  notFound();
}
