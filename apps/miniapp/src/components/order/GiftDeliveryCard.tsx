import { motion } from "framer-motion";

import type { DeliveryOut } from "@/lib/orders";

import { useT } from "@/lib/i18n";
import { getActiveLocale } from "@/lib/i18n/core";

// A Steam gift's fulfiller (`gengine_gifts.py::_map_gift_order`) stamps its
// own `kind: "gift"` onto the artifact — the top-level `artifact_kind` stays
// `"topup_receipt"` (the product is seeded `kind="top_up"`), so `isGiftDelivery`
// (in `order-helpers.ts`) is the only reliable signal `ItemCard` has that a
// delivery is a gift rather than an ordinary top-up receipt.

function giftArtifactString(artifact: Record<string, unknown>, key: string): string | null {
  const value = artifact[key];
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

/**
 * "Примите подарок" card: what was sent (`app_name — package_name`), then
 * the three steps that get it from "sent" to "in your library" — the invite
 * lands via a bot account, which Steam itself flags with a warning the
 * recipient needs to know is expected. Falls back to the fulfiller's own
 * `message` (RU free text, `_DELIVERY_MESSAGE` in `gengine_gifts.py`) only
 * when the structured `app_name`/`package_name` fields aren't there to build
 * the header from — an older artifact shape, or a different supplier.
 *
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function GiftDeliveryCard({ delivery }: { delivery: DeliveryOut }) {
  const { t } = useT();
  const appName = giftArtifactString(delivery.artifact, "app_name");
  const packageName = giftArtifactString(delivery.artifact, "package_name");
  const message = giftArtifactString(delivery.artifact, "message");
  const subtitle = [appName, packageName].filter((v): v is string => v !== null).join(" — ");
  const steps = [t("success.gift.step1"), t("success.gift.step2"), t("success.gift.step3")];

  return (
    <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-3">
      <div className="mb-1.5 flex items-center gap-1.5">
        <span
          className="text-[10px] font-semibold uppercase tracking-[0.08em]"
          style={{ color: "hsl(var(--primary))" }}
        >
          {t("success.gift.badge")}
        </span>
        <span className="text-[10px] text-white/25">·</span>
        <span className="text-[10px] text-white/35">
          {new Date(delivery.delivered_at).toLocaleString(getActiveLocale(), {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
      <div
        className="space-y-2.5 rounded-xl p-3"
        style={{
          background: "hsl(var(--surface-2))",
          border: "1px solid hsl(var(--border))",
        }}
      >
        <div>
          <p className="text-sm font-bold text-white">{t("success.gift.title")}</p>
          {subtitle !== "" && <p className="mt-0.5 text-xs text-white/55">{subtitle}</p>}
        </div>
        <ol className="space-y-1.5">
          {steps.map((step, i) => (
            <li key={step} className="flex gap-2 text-[12px] leading-relaxed text-white/60">
              <span className="text-primary flex-shrink-0 font-semibold">{i + 1}.</span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
        {subtitle === "" && message !== null && (
          <p className="text-[12px] leading-relaxed text-white/50">{message}</p>
        )}
      </div>
    </motion.div>
  );
}
