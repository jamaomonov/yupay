import { homeRegionFlagSrc } from "@yupay/utils";
import { Globe } from "lucide-react";
import Image from "next/image";

interface RegionFlagProps {
  /** Our region code (`us`, `uk`, `global`…) or a SKU's (`US`, `MY/SG`). */
  code: string;
  /** The game's main region, labelled after Uzbekistan — gets our flag. */
  home?: boolean;
  className?: string;
}

/**
 * A region's flag, or a globe for a region that is not one country. Purely
 * visual: the region's name always sits next to it, so it is `alt=""`.
 * SVGs are served as-is (`unoptimized`) — the image optimiser would only
 * rasterise a 1 KB vector.
 */
export function RegionFlag({ code, home = false, className = "" }: RegionFlagProps) {
  const src = homeRegionFlagSrc(code.toLowerCase(), home);
  if (!src) {
    return <Globe aria-hidden size={14} className={`shrink-0 opacity-70 ${className}`} />;
  }
  return (
    <Image
      src={src}
      alt=""
      width={20}
      height={15}
      unoptimized
      loading="lazy"
      className={`h-[15px] w-5 shrink-0 rounded-[3px] object-cover ring-1 ring-white/10 ${className}`}
    />
  );
}
