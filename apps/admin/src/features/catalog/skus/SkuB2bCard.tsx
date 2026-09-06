/**
 * SkuB2bCard — the SKU editor's B2B (merchant catalog) controls: the
 * `visible_b2b` switch, the `b2b_markup_pct` field, and the price preview.
 *
 * Deliberately NOT part of the main SKU form: B2B state is written through
 * the merchants module's dedicated `PATCH /admin/catalog/skus/{id}/b2b`
 * (the plain catalog PATCH ignores these fields), so folding it into the
 * main Save would leave a half-saved SKU whenever one of the two requests
 * failed. One card, one endpoint, its own Save.
 *
 * The preview math lives in `../b2b.ts` (`previewB2bPrice`) — the one
 * sanctioned client-side copy of the formula whose authority is
 * `apps/api/src/yupay/modules/merchants/pricing.py`.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useRef, useState } from "react";

import { parseMarkupPct, patchSkuB2b, previewB2bPrice, T as catalogB2bT } from "../b2b";

import type { SkuB2bOut } from "../b2b";
import type { Sku } from "../types";

import { Field } from "@/components/Field";
import { useToast } from "@/components/Toast";
// `fill` / `formatUsd` are the merchants feature's string helpers — reused,
// not copied: this card is the catalog half of the same B2B surface.
import { fill, formatUsd } from "@/features/merchants/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

const T = catalogB2bT.sku;

interface Props {
  sku: Sku;
  /** The *live* cost from the form's `cost_usdt` field (possibly unsaved),
   *  so the preview tracks what the operator is looking at — «предварительно»
   *  either way; the server prices from what is actually saved. */
  cost: string;
}

export function SkuB2bCard({ sku, cost }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  // Initialised from props ONCE, on mount. That is safe here only because
  // the card lives on the /skus/:id route, which remounts it per SKU — a
  // mount always sees a fresh `sku`. If this card is ever reused somewhere a
  // *mounted* instance's `sku` prop can change (a list row, a modal that
  // swaps SKUs), this state goes stale and needs an explicit re-sync.
  const [visible, setVisible] = useState(sku.visible_b2b);
  const [markup, setMarkup] = useState(sku.b2b_markup_pct);
  const [markupError, setMarkupError] = useState<string | null>(null);
  const keyRef = useRef("");

  const save = useMutation<SkuB2bOut, unknown, { markup_pct: string; visible_b2b: boolean }>({
    mutationFn: (body) => patchSkuB2b(sku.id, body, keyRef.current),
    onSuccess: (data) => {
      toast.success(T.saved);
      // The edit page found this SKU by walking the cached list — patch that
      // list in place so a reopen shows what the server just confirmed.
      qc.setQueryData<Sku[]>(qk.skus(), (old) =>
        old?.map((s) =>
          s.id === data.id
            ? { ...s, visible_b2b: data.visible_b2b, b2b_markup_pct: data.b2b_markup_pct }
            : s,
        ),
      );
    },
    onError: (err) => {
      toast.error(fill(T.error, { message: extractApiMessage(err) }));
    },
  });

  const submit = () => {
    const parsed = parseMarkupPct(markup);
    if (parsed === null) {
      setMarkupError(T.markupInvalid);
      return;
    }
    setMarkupError(null);
    // One key per logical attempt: retries of this attempt replay it, the
    // next click mints a fresh one.
    keyRef.current = `sku-b2b-${crypto.randomUUID()}`;
    save.mutate({ markup_pct: parsed, visible_b2b: visible });
  };

  const preview = previewB2bPrice(cost, markup);
  // Distinguish "no usable cost" (the SKU has no B2B price at all — see
  // `effective_cost` in the pricing module) from "markup half-typed"
  // (preview simply unavailable for a moment).
  const hasCost = previewB2bPrice(cost, "0") !== null;

  return (
    <section className="space-y-3 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h3 className="text-sm font-semibold">{T.title}</h3>

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={visible}
          onChange={(e) => {
            setVisible(e.target.checked);
          }}
          className="mt-0.5 size-4"
        />
        <span>
          {T.visible}
          <span className="mt-0.5 block text-xs text-[var(--text-secondary)]">{T.visibleHint}</span>
        </span>
      </label>

      <Field label={T.markupLabel} error={markupError}>
        {({ inputProps }) => (
          <div className="flex items-center gap-2">
            <Input
              {...inputProps}
              value={markup}
              onChange={(e) => {
                setMarkup(e.target.value);
              }}
              inputMode="decimal"
              placeholder="7.00"
              className="font-mono"
            />
            <span className="text-sm text-[var(--text-secondary)]">%</span>
          </div>
        )}
      </Field>

      <div className="text-xs">
        <p className="font-medium uppercase tracking-wide text-[var(--text-secondary)]">
          {T.previewLabel}
        </p>
        {preview ? (
          <p
            className={`mt-0.5 font-mono text-sm font-semibold ${
              preview.belowCost ? "text-[var(--danger)]" : "text-[var(--accent)]"
            }`}
          >
            {fill(T.previewValue, { price: formatUsd(preview.price) })}
            {preview.belowCost && (
              <span className="ml-1.5 font-sans font-medium">— {T.previewBelowCost}</span>
            )}
          </p>
        ) : hasCost ? (
          <p className="mt-0.5 text-[var(--text-secondary)]">—</p>
        ) : (
          <p className="mt-0.5 text-[var(--text-secondary)]">{T.previewNoCost}</p>
        )}
      </div>

      <Button type="button" onClick={submit} disabled={save.isPending}>
        {save.isPending ? T.saving : T.save}
      </Button>
    </section>
  );
}
