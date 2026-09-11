import { Home, Share2 } from "lucide-react";
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
 * Rating lives next to the receipt (`RateAsk`), not here — a secondary tile
 * among pin/share is the wrong job at this moment.
 */
export function DeliveredExtras({
  brandName,
  imageUrl,
}: {
  brandName: string | null;
  imageUrl: string | null;
}) {
  const { t } = useT();
  const [canPin, setCanPin] = useState(false);
  const canShare = canShareToStory() && Boolean(imageUrl);

  useEffect(() => {
    let alive = true;
    void getHomeScreenStatus().then((status) => {
      if (alive) setCanPin(status === "missed");
    });
    return () => {
      alive = false;
    };
  }, []);

  if (!canPin && !canShare) return null;

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
    </div>
  );
}
