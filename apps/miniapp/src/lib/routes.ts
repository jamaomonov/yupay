/**
 * Shared route-building helpers for brand-aware links.
 *
 * The one wrinkle every caller must agree on: Steam Gifts has its own
 * native catalog/game flow (`/gifts`, `/gifts/:appId`) — the generic
 * `/topup/:slug` top-up form never renders it, it just redirects there
 * (`TopUp.tsx`'s `steam-gifts` effect). A link built with the generic
 * `/topup/${slug}` pattern for this one brand still works, but it costs an
 * extra hop through that redirect — and worse, if the hop ever pushes
 * instead of replacing history, it's how the Telegram BackButton trap in
 * `TopUp.tsx` happened in the first place. Route straight to `/gifts` here
 * so nothing has to hit that redirect at all.
 */

/** Steam Gifts' brand slug — the one value every brand-aware call site
 *  (`Home`, `OrderSuccess`, `History`) matches on to skip the redirect. */
export const STEAM_GIFTS_SLUG = "steam-gifts";

/** The CS2 skins brand: its page is the skins market, not a top-up form. */
export const CS2_SKINS_SLUG = "cs2-skins";

/**
 * Where a brand's "top up" / "buy again" link should point, given just its
 * slug. Steam Gifts routes straight to `/gifts`, CS2 skins to `/cs2-market`;
 * every other brand goes to its own `/topup/:slug` form.
 */
export function hrefForGameSlug(slug: string): string {
  if (slug === STEAM_GIFTS_SLUG) return "/gifts";
  if (slug === CS2_SKINS_SLUG) return "/cs2-market";
  return `/topup/${slug}`;
}

/** Convenience wrapper for callers that already hold a full game/brand
 *  object — its `id` is the same slug `hrefForGameSlug` matches on. */
export function hrefForGame(game: { id: string }): string {
  return hrefForGameSlug(game.id);
}

/**
 * Whether a brand gets a tile in the home screen's services grid. CS2 skins does not:
 * the market has its own promo card at the top of the home screen, and a second, plain
 * tile in the grid only repeats it. Search still finds it.
 */
export function inHomeGrid(slug: string): boolean {
  return slug !== CS2_SKINS_SLUG;
}
