/**
 * BrandB2bCard — the brand editor's B2B (merchant catalog) controls: the
 * brand-level `visible_b2b` switch and the bulk-markup action («наценка
 * всем SKU бренда»).
 *
 * Both write through the merchants module's dedicated endpoints (the plain
 * brand PATCH ignores B2B fields), so the card is self-contained rather
 * than part of the main brand form — see SkuB2bCard for the reasoning.
 *
 * The bulk action rewrites the `b2b_markup_pct` of every SKU of the brand
 * in one UPDATE, which is why it goes through a ConfirmDialog naming the
 * brand and the markup, and reports the affected count from the response.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useRef, useState } from "react";

import { parseMarkupPct, patchBrandB2b, postBulkMarkup, T as catalogB2bT } from "../b2b";

import type { BrandB2bOut, BulkMarkupOut } from "../b2b";
import type { Brand } from "../types";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Field } from "@/components/Field";
import { useToast } from "@/components/Toast";
// `fill` is the merchants feature's `{placeholder}` interpolator — reused,
// not copied: this card is the catalog half of the same B2B surface.
import { fill } from "@/features/merchants/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

const T = catalogB2bT.brand;

interface Props {
  brand: Brand;
}

export function BrandB2bCard({ brand }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const [markup, setMarkup] = useState("");
  const [markupError, setMarkupError] = useState<string | null>(null);
  /** The validated markup awaiting confirmation; `null` = dialog closed. */
  const [pendingMarkup, setPendingMarkup] = useState<string | null>(null);
  const [affected, setAffected] = useState<number | null>(null);
  const visibilityKeyRef = useRef("");
  const bulkKeyRef = useRef("");

  const visibility = useMutation<BrandB2bOut, unknown, boolean>({
    mutationFn: (visibleB2b) => patchBrandB2b(brand.id, visibleB2b, visibilityKeyRef.current),
    onSuccess: (data) => {
      toast.success(T.saved);
      // The edit page found this brand by walking the cached list — patch it
      // in place so the checkbox reflects what the server just confirmed.
      qc.setQueryData<Brand[]>(qk.brands(), (old) =>
        old?.map((b) => (b.id === data.id ? { ...b, visible_b2b: data.visible_b2b } : b)),
      );
    },
    onError: (err) => {
      toast.error(fill(T.error, { message: extractApiMessage(err) }));
    },
  });

  const bulk = useMutation<BulkMarkupOut, unknown, string>({
    mutationFn: (markupPct) => postBulkMarkup(brand.slug, markupPct, bulkKeyRef.current),
    onSuccess: (data) => {
      setPendingMarkup(null);
      setAffected(data.affected);
      // Every SKU of the brand may now carry a different markup.
      void qc.invalidateQueries({ queryKey: qk.skus() });
    },
    onError: (err) => {
      // The confirm dialog stays open — a retry reuses the same key.
      toast.error(fill(T.bulk.error, { message: extractApiMessage(err) }));
    },
  });

  const brandName = brand.translations.find((t) => t.locale === "ru")?.name ?? brand.slug;

  const openBulkConfirm = () => {
    const parsed = parseMarkupPct(markup);
    if (parsed === null) {
      setMarkupError(T.bulk.markupInvalid);
      return;
    }
    setMarkupError(null);
    setAffected(null);
    // One key per logical attempt: retries of this attempt replay it, the
    // next click mints a fresh one.
    bulkKeyRef.current = `brand-bulk-markup-${crypto.randomUUID()}`;
    setPendingMarkup(parsed);
  };

  return (
    <section className="space-y-4 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h2 className="font-medium">{T.title}</h2>

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={brand.visible_b2b}
          disabled={visibility.isPending}
          onChange={(e) => {
            visibilityKeyRef.current = `brand-b2b-${crypto.randomUUID()}`;
            visibility.mutate(e.target.checked);
          }}
          className="mt-0.5 size-4"
        />
        <span>
          {T.visible}
          <span className="mt-0.5 block text-xs text-[var(--text-secondary)]">{T.visibleHint}</span>
        </span>
      </label>

      <div className="border-t border-[var(--border-default)] pt-3">
        <Field label={T.bulk.markupLabel} error={markupError}>
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
                className="w-28 font-mono"
              />
              <span className="text-sm text-[var(--text-secondary)]">%</span>
              <Button
                type="button"
                variant="secondary"
                onClick={openBulkConfirm}
                disabled={bulk.isPending}
              >
                {T.bulk.action}
              </Button>
            </div>
          )}
        </Field>
        {affected !== null && (
          <p role="status" className="mt-2 text-sm font-medium text-[var(--success-fg)]">
            {fill(T.bulk.done, { count: String(affected) })}
          </p>
        )}
      </div>

      {pendingMarkup !== null && (
        <ConfirmDialog
          title={T.bulk.confirmTitle}
          tone="danger"
          confirmLabel={T.bulk.confirm}
          busy={bulk.isPending}
          onCancel={() => {
            setPendingMarkup(null);
          }}
          onConfirm={() => {
            bulk.mutate(pendingMarkup);
          }}
        >
          <p>{fill(T.bulk.confirmBody, { brand: brandName, markup: pendingMarkup })}</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
