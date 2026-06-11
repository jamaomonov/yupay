import { useEffect, useState, type ReactNode } from "react";

/**
 * `<img>` that degrades gracefully: when the URL 404s / DNS-fails (catalog
 * art lives on an external CDN), it renders `fallback` instead of the
 * browser's broken-image glyph with alt text bleeding over the layout.
 */
export function SafeImage({
  src,
  alt = "",
  className,
  fallback = null,
}: {
  src: string;
  alt?: string;
  className?: string;
  fallback?: ReactNode;
}) {
  const [failed, setFailed] = useState(false);
  // A new URL deserves a fresh attempt (brand switch on the topup page).
  useEffect(() => {
    setFailed(false);
  }, [src]);
  if (failed) return <>{fallback}</>;
  return (
    <img src={src} alt={alt} loading="lazy" className={className} onError={() => setFailed(true)} />
  );
}
