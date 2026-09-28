import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { formatUzs } from "@/lib/seo";

/** Price in soʻm (or «Нет в наличии»), the Steam price link, and the buy button. */
export function SkinPriceBlock({
  priceUzs,
  steamUrl,
  locale,
}: {
  priceUzs: string | null;
  steamUrl: string;
  locale: string;
}) {
  const t = useTranslations("web.skins");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="font-display text-3xl font-bold">
          {priceUzs !== null ? formatUzs(locale, Math.round(Number(priceUzs))) : t("soldOut")}
        </span>
        <a
          href={steamUrl}
          target="_blank"
          rel="nofollow noopener noreferrer"
          className="text-tx-dim hover:text-foreground inline-flex items-center gap-1 text-[13px]"
        >
          {t("steamPrice")}
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>
      {/* Purchase is plan 3; the button says so instead of pretending. */}
      <button
        type="button"
        disabled
        className="bg-primary text-primary-foreground w-full rounded-xl py-3.5 text-[15px] font-bold opacity-60"
      >
        {t("buySoon")}
      </button>
    </div>
  );
}
