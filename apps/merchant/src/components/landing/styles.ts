/**
 * Tailwind class strings shared by the public marketing pages.
 *
 * They lived in the landing until `/telegram`, `/api` and `/faq` needed the
 * same section heading and the same card: a class string copied into four
 * files is four places a heading size can drift apart. Plain constants, not
 * components — the markup differs per page, only the look is shared.
 */
export const SECTION_HEADING = "font-display text-2xl font-semibold tracking-tight";
export const CARD = "border-border bg-card rounded-xl border p-5";

/** The width every public page's `<main>` uses, so the header, the body and
 *  the footer line up on one column. */
export const PAGE_MAIN = "mx-auto w-full max-w-5xl px-5 py-14 sm:py-20";

/** The first prose on a page — the paragraph an assistant lifts whole. */
export const LEAD = "text-tx-mute mt-6 max-w-3xl text-[15px] leading-relaxed";
