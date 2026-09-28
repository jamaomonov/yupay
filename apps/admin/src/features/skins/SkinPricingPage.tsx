/**
 * CS2 skin pricing: the rules document, a price preview that explains itself, and
 * per-skin overrides (backend: `apps/api/src/yupay/modules/skins/admin.py`).
 */

import { useQuery } from "@tanstack/react-query";

import { T } from "./api";
import { ItemOverrideCard } from "./ItemOverrideCard";
import { PricePreviewCard } from "./PricePreviewCard";
import { getPricing } from "./pricing-api";
import { PricingRulesCard } from "./PricingRulesCard";

import { PageHeader } from "@/components/PageHeader";
import { qk } from "@/lib/queryKeys";

export function SkinPricingPage() {
  const pricing = useQuery({ queryKey: qk.skinPricing(), queryFn: getPricing });
  return (
    <div className="space-y-4">
      <PageHeader title={T.pricing.title} description={T.pricing.description} />
      {pricing.isError && <p className="text-sm text-[var(--danger)]">{T.pricing.loadError}</p>}
      {pricing.data && (
        <>
          <PricingRulesCard rules={pricing.data.rules} categories={pricing.data.categories} />
          <PricePreviewCard categories={pricing.data.categories} />
        </>
      )}
      <ItemOverrideCard />
    </div>
  );
}
