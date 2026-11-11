import Image from "next/image";

interface CryptoLogoProps {
  /** A round 128×128 logo under `public/crypto/`. */
  src: string;
  /** Rendered size in CSS pixels; next/image serves 1x and 2x of it. */
  size: number;
  /** Empty by default: the chain or coin is named in text beside it. */
  alt?: string;
  className?: string;
}

/** A coin or chain logo — round, transparent, sized by the caller. */
export function CryptoLogo({ src, size, alt = "", className }: CryptoLogoProps) {
  return (
    <Image
      src={src}
      alt={alt}
      width={size}
      height={size}
      className={`shrink-0 rounded-full ${className ?? ""}`}
    />
  );
}
