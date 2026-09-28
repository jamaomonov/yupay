import { CATEGORY_ICONS } from "@yupay/utils";
import { LayoutGrid, Music } from "lucide-react";

import type { SkinCategory } from "@/lib/skins";

/**
 * A category's silhouette: a self-hosted Steam item image used as a CSS mask
 * over `currentColor`, so it takes the tile's grey or its active colour.
 */
export function SkinCategoryIcon({ category }: { category: SkinCategory | "all" }) {
  const icon = category === "all" ? null : CATEGORY_ICONS[category];
  if (category === "all") return <LayoutGrid className="h-5 w-5" aria-hidden />;
  if (icon === null) return <Music className="h-5 w-5" aria-hidden />;
  const url = `url(/skins/categories/${icon.file})`;
  return (
    <span
      data-skin-icon
      aria-hidden
      className={`block h-[26px] bg-current ${icon.wide ? "w-[48px]" : "w-[30px]"}`}
      style={{
        maskImage: url,
        WebkitMaskImage: url,
        maskSize: icon.wide ? "100% auto" : "118% auto",
        WebkitMaskSize: icon.wide ? "100% auto" : "118% auto",
        maskPosition: "center",
        WebkitMaskPosition: "center",
        maskRepeat: "no-repeat",
        WebkitMaskRepeat: "no-repeat",
      }}
    />
  );
}
