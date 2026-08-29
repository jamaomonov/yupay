import Image from "next/image";

/**
 * The yupay wordmark — white "yupay" with the lime up-arrow as the "u".
 *
 * Byte-identical to the storefront's copy, and carried in this app's own
 * `public/` the way the Mini App carries its own: these are three separately
 * built images, and a shared asset would have to become a package to be shared
 * at all.
 *
 * `unoptimized` because Next does not rasterize SVG, and the optimizer round
 * trip returns the file unchanged while costing a slower, uncached request —
 * measured on the storefront, where the same lockup renders on every page.
 *
 * It is white-on-dark by construction, so it belongs only on the dark
 * surfaces: the landing and panel headers. It must not go on the lime
 * application band, where the arrow would vanish into the background.
 */
export function Wordmark({ height = 24 }: { height?: number }) {
  return (
    <Image
      src="/logo/wordmark.svg"
      alt="yupay"
      width={Math.round(height * 3.27)}
      height={height}
      unoptimized
      style={{ height, width: "auto" }}
    />
  );
}
