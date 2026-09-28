/**
 * Server-side feature flags, read at request time from the web container's env
 * (`secrets/web.env` on prod) — not `NEXT_PUBLIC_*`, which would be baked in at
 * build and need a CI build arg to flip.
 */

/** The `/skins` section: nav, footer and sitemap entries. The API has its own flag. */
export function skinsEnabled(): boolean {
  return process.env.SKINS_ENABLED === "true";
}
