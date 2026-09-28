/**
 * CS2 skin pricing: the rules document, a price preview that explains itself, and
 * per-skin overrides (backend: `apps/api/src/yupay/modules/skins/admin.py`).
 */

import { useQuery } from "@tanstack/react-query";

import { fill, T } from "./api";
import { ItemOverrideCard } from "./ItemOverrideCard";
import { PricePreviewCard } from "./PricePreviewCard";
import { getPricing, type SkinsPricingOut } from "./pricing-api";
import { PricingRulesCard } from "./PricingRulesCard";

import { PageHeader } from "@/components/PageHeader";
import { qk } from "@/lib/queryKeys";

const S = T.pricing.status;

/** Whether skins are on the site, whether prices sync, and how fresh they are. */
function StatusCard({ pricing }: { pricing: SkinsPricingOut }) {
  const last = pricing.prices_updated_at
    ? new Intl.DateTimeFormat("ru", { dateStyle: "short", timeStyle: "short" }).format(
        new Date(pricing.prices_updated_at),
      )
    : S.never;
  const chip = (on: boolean) =>
    on
      ? "bg-[var(--success-soft)] text-[var(--success-fg)]"
      : "bg-[var(--warning-soft)] text-[var(--warning-fg)]";
  return (
    <section className="flex flex-wrap items-center gap-2 text-sm" aria-label={S.title}>
      <span className={`rounded-full px-2.5 py-1 ${chip(pricing.enabled)}`}>
        {pricing.enabled ? S.siteOn : S.siteOff}
      </span>
      <span className={`rounded-full px-2.5 py-1 ${chip(pricing.sync_enabled)}`}>
        {pricing.sync_enabled ? S.syncOn : S.syncOff} · {fill(S.lastSync, { date: last })}
      </span>
      <span className="rounded-full bg-[var(--bg-muted)] px-2.5 py-1">
        {fill(S.active, { count: String(pricing.items_active) })}
      </span>
    </section>
  );
}

export function SkinPricingPage() {
  const pricing = useQuery({ queryKey: qk.skinPricing(), queryFn: getPricing });
  return (
    <div className="space-y-4">
      <PageHeader title={T.pricing.title} description={T.pricing.description} />
      {pricing.isError && <p className="text-sm text-[var(--danger)]">{T.pricing.loadError}</p>}
      {pricing.data && (
        <>
          <StatusCard pricing={pricing.data} />
          <PricingRulesCard
            rules={pricing.data.rules}
            categories={pricing.data.categories}
            itemsActive={pricing.data.items_active}
          />
          <PricePreviewCard categories={pricing.data.categories} />
        </>
      )}
      <ItemOverrideCard />
    </div>
  );
}
