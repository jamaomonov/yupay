import Image from "next/image";

/**
 * yupay wordmark — the real brand lockup (white "yupay" + lime up-arrow as the
 * "u"), shared with the Telegram mini app so web and in-app branding match
 * 1:1. SVG keeps it crisp at any size; intrinsic ratio is ~3.27:1.
 *
 * `unoptimized` because Next does not rasterize SVG. Measured on production,
 * `/_next/image?url=…wordmark.svg&w=256` returns the file byte-for-byte
 * identical to `/logo/wordmark.svg` — 3981 bytes either way — so the round trip
 * through the optimizer produced nothing and cost 433ms of TTFB against 273ms
 * for the plain file, the optimizer path not being edge-cached.
 *
 * And no `priority`: that emits a `<link rel="preload" as="image">`, so a
 * header logo which changes nothing about the page was being preloaded ahead
 * of the brand hero, which is the actual LCP element. It is rendered twice per
 * page (header and footer), so it was two of them.
 */
export function Wordmark({ size = "md" }: { size?: "sm" | "md" }) {
  const height = size === "sm" ? 24 : 30;
  const width = Math.round(height * 3.27);
  return (
    <Image
      src="/logo/wordmark.svg"
      alt="yupay"
      width={width}
      height={height}
      unoptimized
      style={{ height, width: "auto" }}
    />
  );
}
