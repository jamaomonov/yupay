import { Info } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useT } from "@/lib/i18n";

/**
 * "Как узнать регион?" hint: where in Steam to find the account's country,
 * opened from `GiftGame`'s region step. Extracted as its own sheet (rather
 * than an always-open box, the way `regionWarning` is) because the country
 * picker — flag + localized name — is already self-explanatory for most
 * buyers; this only earns its screen space on demand. Mirrors
 * `InviteGuideSheet`'s shape exactly, one explanatory paragraph instead of a
 * numbered list since there's one place to look, not a multi-step flow.
 */
export function RegionGuideSheet({
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
            <Info size={16} className="text-primary" aria-hidden="true" />
            {t("gifts.game.regionHintCta")}
          </SheetTitle>
          <SheetDescription asChild>
            <p className="mt-1 text-left leading-relaxed text-white/70">
              {t("gifts.game.regionHintText")}
            </p>
          </SheetDescription>
        </SheetHeader>
      </SheetContent>
    </Sheet>
  );
}
