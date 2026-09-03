import { HelpCircle } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useT } from "@/lib/i18n";

/**
 * "Где найти ссылку?" guide: the 3 steps for locating a Steam profile/invite
 * link, opened from `GiftGame`'s invite field. Extracted out of `GiftGame.tsx`
 * (2026-09-03 review) purely to keep that file near the repo's TS file-length
 * budget — no behaviour change.
 */
export function InviteGuideSheet({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { t } = useT();
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="rounded-t-3xl">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <HelpCircle size={16} className="text-primary" aria-hidden="true" />
            {t("gifts.game.inviteGuideTitle")}
          </SheetTitle>
          <SheetDescription asChild>
            <ol className="mt-1 list-decimal space-y-1.5 pl-5 text-left leading-relaxed text-white/70">
              <li>{t("gifts.game.inviteGuideStep1")}</li>
              <li>{t("gifts.game.inviteGuideStep2")}</li>
              <li>{t("gifts.game.inviteGuideStep3")}</li>
            </ol>
          </SheetDescription>
        </SheetHeader>
      </SheetContent>
    </Sheet>
  );
}
