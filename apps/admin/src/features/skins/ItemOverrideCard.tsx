/**
 * A per-skin markup: find an item (or list the ones already overridden), then set or
 * clear its margin adjustment (pp) and fixed price. Only the fields sent change; `null`
 * clears one. One Idempotency-Key per save attempt, as on the rules card.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useEffect, useRef, useState } from "react";

import { fill, T, usd } from "./api";
import {
  findItems,
  patchItem,
  previewPrice,
  refusal,
  type AdminSkinItemOut,
  type ItemPricingIn,
} from "./pricing-api";
import { Card, INPUT, NumberField } from "./pricing-ui";

import { qk } from "@/lib/queryKeys";

const P = T.pricing.items;

function ItemEditor({ item, onSaved }: { item: AdminSkinItemOut; onSaved: () => void }) {
  const [margin, setMargin] = useState(item.margin_override_pp ?? "");
  const [fixed, setFixed] = useState(item.fixed_price_usd ?? "");
  const key = useRef<string | null>(null);
  const save = useMutation({
    mutationFn: (body: ItemPricingIn) => {
      key.current ??= `skins-item-${item.slug}-${crypto.randomUUID()}`;
      return patchItem(item.slug, body, key.current);
    },
    onSuccess: (out) => {
      key.current = null;
      setMargin(out.margin_override_pp ?? "");
      setFixed(out.fixed_price_usd ?? "");
      onSaved();
    },
  });
  const orNull = (v: string) => (v.trim() === "" ? null : v.trim());
  // The price these numbers would give, before saving: the preview with the skin's own
  // data and the typed override on top. Debounced so typing does not fire per key.
  const [probe, setProbe] = useState({ margin, fixed });
  useEffect(() => {
    const timer = setTimeout(() => {
      setProbe({ margin, fixed });
    }, 300);
    return () => {
      clearTimeout(timer);
    };
  }, [margin, fixed]);
  const live = useQuery({
    queryKey: ["admin", "skins", "preview", item.slug, probe.margin, probe.fixed],
    queryFn: () =>
      previewPrice({
        slug: item.slug,
        item_pp: probe.margin.trim() === "" ? "0" : probe.margin,
        fixed_price_usd: probe.fixed,
      }),
  });

  return (
    <div
      role="group"
      aria-label={item.name}
      className="space-y-3 rounded-md border border-[var(--border-default)] p-3"
    >
      <p className="text-sm font-medium">{item.name}</p>
      <div className="grid max-w-md grid-cols-2 gap-3">
        <NumberField
          label={P.margin}
          value={margin}
          onChange={(v) => {
            key.current = null;
            setMargin(v);
          }}
        />
        <NumberField
          label={P.fixed}
          value={fixed}
          onChange={(v) => {
            key.current = null;
            setFixed(v);
          }}
        />
      </div>
      <p className="text-xs text-[var(--text-secondary)]">
        {P.precedence} {P.clearHint}.
      </p>
      {live.data && (
        <p className="text-sm font-medium">
          {fill(P.willSell, { price: usd(live.data.price_usd) })}
        </p>
      )}
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          disabled={save.isPending}
          onClick={() => {
            save.mutate({ margin_override_pp: orNull(margin), fixed_price_usd: orNull(fixed) });
          }}
        >
          {P.save}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={save.isPending}
          onClick={() => {
            key.current = null;
            save.mutate({ margin_override_pp: null, fixed_price_usd: null });
          }}
        >
          {P.clear}
        </Button>
        {save.isSuccess && <span className="text-sm text-[var(--success-fg)]">{P.saved}</span>}
        {save.isError && (
          <span role="alert" className="text-sm text-[var(--danger)]">
            {refusal(save.error)}
          </span>
        )}
      </div>
    </div>
  );
}

export function ItemOverrideCard() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [overridden, setOverridden] = useState(true);
  const [picked, setPicked] = useState<AdminSkinItemOut | null>(null);
  const items = useQuery({
    queryKey: qk.skinItems(q, overridden),
    queryFn: () => findItems(q, overridden),
    enabled: overridden || q.trim().length >= 2,
  });

  return (
    <Card title={P.title}>
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={q}
          placeholder={P.search}
          aria-label={P.search}
          onChange={(e) => {
            setQ(e.target.value);
            if (e.target.value.trim()) setOverridden(false);
          }}
          className={`${INPUT} max-w-sm`}
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={overridden}
            onChange={(e) => {
              setOverridden(e.target.checked);
            }}
          />
          {P.overridden}
        </label>
      </div>
      {items.data?.items.length === 0 && (
        <p className="text-sm text-[var(--text-secondary)]">{P.empty}</p>
      )}
      <ul className="space-y-1">
        {items.data?.items.map((it) => (
          <li key={it.slug}>
            <button
              type="button"
              onClick={() => {
                setPicked(it);
              }}
              className="w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-[var(--bg-muted)]"
            >
              <span className="font-medium">{it.name}</span>{" "}
              <span className="text-[var(--text-secondary)]">
                · {fill(P.cost, { cost: it.cost_usd ? usd(it.cost_usd) : "—" })} ·{" "}
                {fill(P.sell, { price: it.sell_price_usd ? usd(it.sell_price_usd) : "—" })}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {picked && (
        <ItemEditor
          key={picked.slug}
          item={picked}
          onSaved={() => {
            void qc.invalidateQueries({ queryKey: ["admin", "skins", "items"] });
          }}
        />
      )}
    </Card>
  );
}
