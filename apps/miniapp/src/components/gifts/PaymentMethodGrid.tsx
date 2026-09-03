import type { ProviderAvailability } from "@/lib/orders";
import type { PaymentMethod } from "@/lib/payment-methods";

import { useT } from "@/lib/i18n";
import { methodVisibility } from "@/lib/orders";
import { cn } from "@/lib/utils";

/**
 * Acquirer picker for the gift checkout — `GiftGame`'s own provider
 * state/UI, mirroring `TopUp.tsx`'s acquirer grid rather than importing that
 * page (see the M2 brief). The wallet ("pay from balance") option is NOT
 * one of these tiles: it's rendered as its own full-width card by
 * `GiftBuyPanel`, above this grid (2026-09-03, mirrors `TopUp.tsx`'s
 * `WalletPayOption`) — this grid only ever reasons about upstream
 * acquirers. Also no separate "soon"/maintenance badge strip, since a gift
 * checkout has nothing to show for an admin-disabled method beyond simply
 * not rendering it.
 *
 * Extracted out of `GiftGame.tsx` (2026-09-03) purely to keep that file near
 * the repo's TS file-length budget — no behaviour change.
 */
export function PaymentMethodGrid({
  methods,
  activeId,
  providerStatusBySlug,
  onSelect,
}: {
  /** Full method list — hidden (admin-disabled) ones are filtered here. */
  methods: PaymentMethod[];
  activeId: string;
  providerStatusBySlug: Map<string, ProviderAvailability> | null;
  onSelect: (id: string) => void;
}) {
  const { t } = useT();
  const visible = methods.filter(
    (m) => methodVisibility(m.provider, providerStatusBySlug) !== "hidden",
  );

  if (visible.length === 0) {
    return <p className="text-sm text-white/40">{t("gifts.checkout.noMethods")}</p>;
  }

  return (
    <div
      className="grid gap-2"
      style={{ gridTemplateColumns: `repeat(${String(visible.length)}, minmax(0, 1fr))` }}
    >
      {visible.map((m) => {
        const visibility = methodVisibility(m.provider, providerStatusBySlug);
        const available = visibility === "active";
        const active = activeId === m.id && available;
        return (
          <button
            key={m.id}
            type="button"
            disabled={!available}
            title={
              available
                ? undefined
                : visibility === "maintenance"
                  ? t("payment.maintenance")
                  : t("topup.soon")
            }
            aria-pressed={active}
            onClick={() => {
              onSelect(m.id);
            }}
            className="flex flex-col items-center gap-1 rounded-2xl py-3 transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
              border: active
                ? "1.5px solid hsl(var(--primary) / 0.8)"
                : "1px solid hsl(var(--border))",
            }}
          >
            <span className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-md">
              <img src={m.icon} alt={m.name} className="h-full w-full object-cover" />
            </span>
            <span
              className={cn(
                "text-[11px] font-bold leading-none",
                active ? "text-white" : available ? "text-white/50" : "text-white/35",
              )}
            >
              {m.name}
            </span>
          </button>
        );
      })}
    </div>
  );
}
