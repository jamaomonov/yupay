import { notFound } from "next/navigation";

/**
 * Every path under a locale that no route claims.
 *
 * Without this, an unknown URL (`/nope`, `/en/nope`) never reached
 * `[locale]/not-found.tsx` — that boundary only catches `notFound()` thrown
 * inside the segment — and fell through to the root 404, outside the locale
 * layout: no styles, no language, an empty `<title>`. Throwing here renders
 * the localised 404 inside the layout instead. The pattern next-intl
 * documents for exactly this.
 */
export default function CatchAll(): never {
  notFound();
}
