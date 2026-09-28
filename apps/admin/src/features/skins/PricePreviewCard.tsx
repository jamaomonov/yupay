/**
 * What a skin would sell for under the saved rules, with the reasoning: cost, expenses,
 * the bracket markup, every adjustment and which rule won (formula, fixed, min margin,
 * Steam cap, floor). Read-only — `GET /admin/skins/pricing/preview`.
 */

import { useMutation } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useState } from "react";

import { T } from "./api";
import { previewPrice, refusal, type SkinQuoteOut } from "./pricing-api";
import { Card, INPUT, NumberField } from "./pricing-ui";

const P = T.pricing.preview;
const ROWS = Object.keys(P.breakdown) as (keyof typeof P.breakdown)[];

export function PricePreviewCard({ categories }: { categories: string[] }) {
  const [form, setForm] = useState({
    cost_usd: "",
    category: categories[0] ?? "rifles",
    channel: "retail",
    count: "",
    item_pp: "",
    fixed_price_usd: "",
    steam_price_usd: "",
  });
  const set = (patch: Partial<typeof form>) => {
    setForm((f) => ({ ...f, ...patch }));
  };
  const quote = useMutation<SkinQuoteOut, unknown, typeof form>({
    mutationFn: (params) => previewPrice(params),
  });

  return (
    <Card title={P.title}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <NumberField
          label={P.cost}
          value={form.cost_usd}
          onChange={(v) => {
            set({ cost_usd: v });
          }}
        />
        <label className="block space-y-1 text-sm">
          <span className="text-[var(--text-secondary)]">{P.category}</span>
          <select
            value={form.category}
            onChange={(e) => {
              set({ category: e.target.value });
            }}
            className={INPUT}
          >
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="block space-y-1 text-sm">
          <span className="text-[var(--text-secondary)]">{P.channel}</span>
          <select
            value={form.channel}
            onChange={(e) => {
              set({ channel: e.target.value });
            }}
            className={INPUT}
          >
            <option value="retail">{P.retail}</option>
            <option value="b2b">{P.b2b}</option>
          </select>
        </label>
        <NumberField
          label={P.count}
          step="1"
          value={form.count}
          onChange={(v) => {
            set({ count: v });
          }}
        />
        <NumberField
          label={P.itemPp}
          value={form.item_pp}
          onChange={(v) => {
            set({ item_pp: v });
          }}
        />
        <NumberField
          label={P.fixed}
          value={form.fixed_price_usd}
          onChange={(v) => {
            set({ fixed_price_usd: v });
          }}
        />
        <NumberField
          label={P.steam}
          value={form.steam_price_usd}
          onChange={(v) => {
            set({ steam_price_usd: v });
          }}
        />
      </div>
      <Button
        disabled={form.cost_usd.trim() === "" || quote.isPending}
        onClick={() => {
          quote.mutate(form);
        }}
      >
        {P.run}
      </Button>
      {quote.isError && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          {refusal(quote.error)}
        </p>
      )}
      {quote.data && (
        <dl className="grid max-w-md grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <dt className="font-semibold">{P.price}</dt>
          <dd className="text-right font-semibold tabular-nums">${quote.data.price_usd}</dd>
          {ROWS.map((k) => (
            <div key={k} className="contents">
              <dt className="text-[var(--text-secondary)]">{P.breakdown[k]}</dt>
              <dd className="text-right tabular-nums">{quote.data[k]}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}
