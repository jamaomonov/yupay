import { Home, Share2, Star } from "lucide-react";
import { useEffect, useState } from "react";

import { ActionButton } from "./ActionButton";

import { useT } from "@/lib/i18n";
import {
  addToHomeScreen,
  canShareToStory,
  getHomeScreenStatus,
  shareToStory,
} from "@/lib/telegram";

/**
 * Post-delivery offers: pin the app, brag about the top-up.
 *
 * Deliberately only on a delivered order — asking someone to install a
 * shortcut before they know the purchase worked is noise. Each affordance
 * hides itself unless the client actually supports it, so on older Telegram
 * versions this section simply isn't there.
 *
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function DeliveredExtras({
  brandName,
  imageUrl,
  canRate,
  onRate,
}: {
  brandName: string | null;
  imageUrl: string | null;
  canRate: boolean;
  onRate: () => void;
}) {
  const { t } = useT();
  const [canPin, setCanPin] = useState(false);
  const canShare = canShareToStory() && Boolean(imageUrl);

  useEffect(() => {
    let alive = true;
    void getHomeScreenStatus().then((status) => {
      // "missed" = supported and not installed yet. "added" / "unsupported" /
      // null all mean there's nothing worth offering.
      if (alive) setCanPin(status === "missed");
    });
    return () => {
      alive = false;
    };
  }, []);

  if (!canPin && !canShare && !canRate) return null;

  return (
    <div className="grid grid-cols-2 gap-3 px-4 pt-1">
      {canPin && (
        <ActionButton
          icon={<Home size={15} />}
          label={t("success.addToHome")}
          variant="secondary"
          onClick={() => {
            addToHomeScreen();
          }}
        />
      )}
      {canShare && imageUrl && (
        <ActionButton
          icon={<Share2 size={15} />}
          label={t("success.share")}
          variant="secondary"
          onClick={() => {
            shareToStory(imageUrl, {
              text: brandName
                ? t("success.shareStoryText", { game: brandName })
                : t("success.shareStoryTextGeneric"),
            });
          }}
        />
      )}
      {canRate && (
        <ActionButton
          icon={<Star size={15} />}
          label={t("reviews.rateCta")}
          variant="secondary"
          onClick={onRate}
        />
      )}
    </div>
  );
}
