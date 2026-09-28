import { CATEGORY_ICONS } from "@yupay/utils";
import { LayoutGrid, Music } from "lucide-react";

import type { SkinCategory } from "@yupay/utils";

/**
 * A category's silhouette: a self-hosted Steam item image used as a CSS mask
 * over `currentColor`, so it takes the tile's grey or its active colour.
 */
export function SkinCategoryIcon({ category }: { category: SkinCategory | "all" }) {
  if (category === "all") return <LayoutGrid className="h-5 w-5" aria-hidden="true" />;
  const icon = CATEGORY_ICONS[category];
  if (icon === null) return <Music className="h-5 w-5" aria-hidden="true" />;
  const url = `url(/skins/categories/${icon.file})`;
  const size = icon.wide ? "100% auto" : "118% auto";
  return (
    <span
      aria-hidden="true"
      className={`block h-6 bg-current ${icon.wide ? "w-11" : "w-7"}`}
      style={{
        maskImage: url,
        WebkitMaskImage: url,
        maskSize: size,
        WebkitMaskSize: size,
        maskPosition: "center",
        WebkitMaskPosition: "center",
        maskRepeat: "no-repeat",
        WebkitMaskRepeat: "no-repeat",
      }}
    />
  );
}
