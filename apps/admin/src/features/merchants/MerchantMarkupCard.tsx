import { useMutation } from "@tanstack/react-query";
import { Percent } from "lucide-react";
import { useId, useState } from "react";

import { T, fill, setMerchantMarkup, type MerchantOut } from "./api";

import type { ApiError } from "@/lib/api";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { extractApiMessage } from "@/lib/apiError";

/** Percentage points, signed, at most two decimals. `null` when unusable —
 *  the same shape `parseUsdAmount` uses one card over. */
export function parsePoints(raw: string): string | null {
  const text = raw.trim().replace(",", ".");
  if (!/^-?\d{1,3}(\.\d{1,2})?$/.test(text)) return null;
  return text;
}

/** The body of a `markup_below_floor` refusal, as the server flattens it. */
interface FloorBody {
  code?: unknown;
  thinnest_markup_pct?: unknown;
  floor_pct?: unknown;
  lowest_allowed_pp?: unknown;
}

/**
 * The floor refusal, rendered as the number to type next — or `null` when
 * this is any other failure.
 *
 * The server answers `markup_below_floor` with the thinnest markup in the
 * catalogue, the floor, and the lowest adjustment that would work. Flattening
 * that into "не удалось сохранить" would tell an operator something went
 * wrong and not what to do about it.
 *
 * Exported and pure because the harness these cards are tested in renders no
 * toasts, so this is the only way the branch can be asserted at all.
 */
export function floorMessage(err: ApiError): string | null {
  const body: FloorBody =
    typeof err.body === "object" && err.body !== null ? (err.body as FloorBody) : {};
  if (body.code !== "markup_below_floor") return null;
  return fill(T.markup.floorError, {
    thinnest: String(body.thinnest_markup_pct),
    floor: String(body.floor_pct),
    lowest: String(body.lowest_allowed_pp),
  });
}

/**
 * What this merchant pays over cost, relative to everybody else.
 *
 * `markup_adjustment_pp` has been on the merchant row since M1 and nothing
 * could write it: `pricing.merchant_markup_pct` has been adding it to every
 * SKU's own markup all along, and it was `None` for every merchant alive.
 * This card is the setter.
 *
 * Percentage **points**, not a multiplier and not a price. With the
 * catalogue at 7 %, `-2` prices this merchant at 5 % over cost — on
 * everything at once, which is why the confirm names the whole catalogue
 * rather than a number in isolation.
 *
 * A discount below the margin floor is refused by the server, which answers
 * with the lowest value that would work; that answer is rendered rather than
 * flattened into "не удалось сохранить", because the fix is a number.
 */
export function MerchantMarkupCard({
  merchant,
  onChange,
}: {
  merchant: MerchantOut;
  /** Called with the row the API returned, so the page and the list agree. */
  onChange: (merchant: MerchantOut) => void;
}) {
  const toast = useToast();
  const fieldId = useId();
  const [value, setValue] = useState("");
  const [pending, setPending] = useState<string | null>(null);

  const save = useMutation<MerchantOut, ApiError, string | null>({
    mutationFn: (adjustment) => setMerchantMarkup(merchant.id, adjustment),
    onSuccess: (row, adjustment) => {
      setPending(null);
      setValue("");
      onChange(row);
      toast.success(adjustment === null ? T.markup.clearedToast : T.markup.savedToast);
    },
    onError: (err) => {
      setPending(null);
      toast.error(floorMessage(err) ?? fill(T.markup.error, { message: extractApiMessage(err) }));
    },
  });

  const current = merchant.markup_adjustment_pp;

  return (
    <section className="mb-6 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <Percent size={16} />
        {T.markup.title}
      </h2>
      <p className="mb-3 text-xs text-[var(--text-secondary)]">{T.markup.hint}</p>

      <p className="mb-3 text-sm">
        {current === null ? T.markup.none : fill(T.markup.current, { value: current })}
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={fieldId} className="text-xs uppercase text-[var(--text-secondary)]">
            {T.markup.label}
          </label>
          <input
            id={fieldId}
            value={value}
            inputMode="decimal"
            placeholder={T.markup.placeholder}
            onChange={(event) => {
              setValue(event.target.value);
            }}
            className="rounded-btn mt-1 w-32 border px-3 py-2 font-mono text-sm"
          />
        </div>
        <button
          type="button"
          disabled={save.isPending}
          onClick={() => {
            const parsed = parsePoints(value);
            if (parsed === null) {
              toast.error(T.markup.invalid);
              return;
            }
            setPending(parsed);
          }}
          className="rounded-btn border px-4 py-2 text-sm font-semibold disabled:opacity-60"
        >
          {save.isPending ? T.markup.saveBusy : T.markup.save}
        </button>
        {current !== null && (
          <button
            type="button"
            disabled={save.isPending}
            onClick={() => {
              save.mutate(null);
            }}
            className="rounded-btn border px-3 py-2 text-xs disabled:opacity-60"
          >
            {T.markup.clear}
          </button>
        )}
      </div>

      {pending !== null && (
        <ConfirmDialog
          title={T.markup.confirmTitle}
          confirmLabel={T.markup.confirm}
          cancelLabel={T.markup.cancel}
          busy={save.isPending}
          onCancel={() => {
            setPending(null);
          }}
          onConfirm={() => {
            save.mutate(pending);
          }}
        >
          <p>{fill(T.markup.confirmBody, { title: merchant.title, value: pending })}</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
