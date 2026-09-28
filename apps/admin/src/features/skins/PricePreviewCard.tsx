/**
 * What a skin would sell for under the saved rules, with the reasoning: cost, expenses,
 * the bracket markup, every adjustment and which rule won. Either a real skin picked by
 * name (its own cost, category, listing count, overrides and Steam price) or numbers
 * typed by hand. Read-only — `GET /admin/skins/pricing/preview`.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useState } from "react";

import { fill, T, usd } from "./api";
import {
  findItems,
  previewPrice,
  refusal,
  type AdminSkinItemOut,
  type SkinQuoteOut,
} from "./pricing-api";
import { Card, INPUT, NumberField } from "./pricing-ui";

import { qk } from "@/lib/queryKeys";

const P = T.pricing.preview;
const CATEGORY_NAMES: Record<string, string> = T.pricing.categories;
const APPLIED: Record<string, string> = P.applied;
/** Breakdown rows in dollars; the rest are percentage points. */
const DOLLARS = new Set(["cost_usd", "expenses_usd", "bracket_margin_usd"]);
const ROWS = Object.keys(P.breakdown) as (keyof typeof P.breakdown)[];

function Breakdown({ quote }: { quote: SkinQuoteOut }) {
  return (
    <dl className="grid max-w-md grid-cols-2 gap-x-4 gap-y-1 text-sm">
      <dt className="font-semibold">{P.price}</dt>
      <dd className="text-right font-semibold tabular-nums">{usd(quote.price_usd)}</dd>
      {ROWS.map((k) => (
        <div key={k} className="contents">
          <dt className="text-[var(--text-secondary)]">{P.breakdown[k]}</dt>
          <dd className="text-right tabular-nums">
            {k === "applied"
              ? (APPLIED[quote.applied] ?? quote.applied)
              : DOLLARS.has(k)
                ? usd(quote[k])
                : quote[k]}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function SkinPicker({ onPick }: { onPick: (item: AdminSkinItemOut) => void }) {
  const [q, setQ] = useState("");
  const found = useQuery({
    queryKey: qk.skinItems(q, false),
    queryFn: () => findItems(q, false),
    enabled: q.trim().length >= 2,
  });
  const label = P.pickLabel;
  return (
    <div className="space-y-1">
      <input
        type="search"
        value={q}
        aria-label={label}
        placeholder={T.pricing.items.search}
        onChange={(e) => {
          setQ(e.target.value);
        }}
        className={`${INPUT} max-w-sm`}
      />
      {found.data && found.data.items.length > 0 && (
        <ul role="listbox" aria-label={label} className="max-w-xl space-y-0.5">
          {found.data.items.map((it) => (
            <li
              key={it.slug}
              role="option"
              aria-selected={false}
              tabIndex={0}
              onClick={() => {
                onPick(it);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") onPick(it);
              }}
              className="cursor-pointer rounded px-2 py-1 text-sm hover:bg-[var(--bg-muted)]"
            >
              {it.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function PricePreviewCard({ categories }: { categories: string[] }) {
  const [mode, setMode] = useState<"skin" | "manual">("manual");
  const [skin, setSkin] = useState<AdminSkinItemOut | null>(null);
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
  const quote = useMutation<SkinQuoteOut, unknown, Record<string, string>>({
    mutationFn: (params) => previewPrice(params),
  });
  const ready = mode === "skin" ? skin !== null : form.cost_usd.trim() !== "";

  return (
    <Card title={P.title}>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant={mode === "skin" ? "primary" : "ghost"}
          onClick={() => {
            setMode("skin");
          }}
        >
          {P.pickSkin}
        </Button>
        <Button
          size="sm"
          variant={mode === "manual" ? "primary" : "ghost"}
          onClick={() => {
            setMode("manual");
          }}
        >
          {P.manual}
        </Button>
      </div>

      {mode === "skin" ? (
        <div className="space-y-2">
          <SkinPicker onPick={setSkin} />
          {skin && <p className="text-sm font-medium">{fill(P.pickedSkin, { name: skin.name })}</p>}
        </div>
      ) : (
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
                  {CATEGORY_NAMES[c] ?? c}
                </option>
              ))}
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
      )}

      <div className="flex flex-wrap items-end gap-3">
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
        <Button
          disabled={!ready || quote.isPending}
          onClick={() => {
            quote.mutate(
              mode === "skin" && skin ? { slug: skin.slug, channel: form.channel } : form,
            );
          }}
        >
          {P.run}
        </Button>
      </div>
      {quote.isError && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          {refusal(quote.error)}
        </p>
      )}
      {quote.data && <Breakdown quote={quote.data} />}
    </Card>
  );
}
