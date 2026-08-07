/**
 * Whether Next's image optimizer may fetch this source.
 *
 * Catalog art is admin-pasted and can point at any third-party host (see the
 * `remotePatterns` note in next.config.ts). When such a host is slow or down,
 * the optimizer doesn't degrade — it 504s and the image disappears entirely,
 * which is why every catalog `<Image>` was marked `unoptimized` wholesale.
 *
 * That protection was aimed at hosts we don't control, but it also caught our
 * own: `/public` files and the R2-backed cdn.yupay.uz were shipped raw. The
 * cost is not small — measured against production, a 407 KB brand hero comes
 * back as 8 KB of WebP at w=640, and a 21 KB payment PNG as 1.8 KB.
 *
 * So the rule is narrower now: optimize what we serve ourselves, pass through
 * everything else untouched.
 */

/** Hosts whose availability is ours to guarantee. */
function isFirstPartyHost(hostname: string): boolean {
  return (
    hostname === "yupay.uz" ||
    hostname.endsWith(".yupay.uz") ||
    // R2 public bucket, used when the cdn.yupay.uz custom domain isn't wired
    // up in a given environment.
    hostname.endsWith(".r2.dev")
  );
}

export function isOptimizable(src: string | null | undefined): boolean {
  if (!src) return false;
  // A root-relative path is served by this very app — nothing external to fail.
  if (src.startsWith("/")) return true;
  try {
    const url = new URL(src);
    return url.protocol === "https:" && isFirstPartyHost(url.hostname);
  } catch {
    // Not a parseable absolute URL; leave it alone rather than guess.
    return false;
  }
}
