import { Input } from "@yupay/ui";
import { forwardRef, useRef, type ChangeEvent, type ComponentPropsWithoutRef } from "react";
import { flushSync } from "react-dom";

import { groupAmountInput, ungroupAmountInput } from "@/lib/money";

type NativeInputProps = ComponentPropsWithoutRef<typeof Input>;

export interface MoneyInputProps extends Omit<NativeInputProps, "value" | "onChange" | "type"> {
  /** Canonical (ungrouped) amount string, e.g. ``"12000000"`` or ``"-3.5"`` —
   *  the same shape existing parsers (`parseAdjustAmount`, price-override
   *  schemas) already expect. */
  value: string;
  onChange: (raw: string) => void;
}

/** Count of non-whitespace characters in `s` before index `pos` — used to
 *  keep the caret glued to the same digit while grouping spaces are
 *  inserted or removed around it. */
function significantCountBefore(s: string, pos: number): number {
  let n = 0;
  for (let i = 0; i < pos && i < s.length; i++) {
    if (!/\s/.test(s.charAt(i))) n++;
  }
  return n;
}

/** Inverse of `significantCountBefore`: the index in `s` right after its
 *  `count`-th non-whitespace character. */
function indexAfterSignificantCount(s: string, count: number): number {
  if (count <= 0) return 0;
  let seen = 0;
  for (let i = 0; i < s.length; i++) {
    if (!/\s/.test(s.charAt(i))) {
      seen += 1;
      if (seen >= count) return i + 1;
    }
  }
  return s.length;
}

/**
 * Money-amount text input that groups digits as the operator types —
 * ``"12000000"`` reads as ``"12 000 000"`` without counting zeros, matching
 * `formatMoney`'s grouping everywhere the amount is later shown at rest.
 *
 * `value`/`onChange` carry the ungrouped canonical string; grouping is a
 * display-only concern handled entirely inside this component, so callers
 * (and the parsers they hand the value to) never see the inserted spaces.
 */
export const MoneyInput = forwardRef<HTMLInputElement, MoneyInputProps>(
  ({ value, onChange, ...props }, forwardedRef) => {
    const localRef = useRef<HTMLInputElement | null>(null);

    function handleChange(e: ChangeEvent<HTMLInputElement>) {
      const el = e.target;
      const cursor = el.selectionStart ?? el.value.length;
      const significantBefore = significantCountBefore(el.value, cursor);
      // Synchronous so the DOM already reflects the re-grouped `value` prop
      // by the time this call returns — otherwise there's nothing to base
      // the restored caret position on.
      flushSync(() => {
        onChange(ungroupAmountInput(el.value));
      });
      const pos = indexAfterSignificantCount(el.value, significantBefore);
      el.setSelectionRange(pos, pos);
    }

    return (
      <Input
        ref={(node) => {
          localRef.current = node;
          if (typeof forwardedRef === "function") forwardedRef(node);
          else if (forwardedRef) forwardedRef.current = node;
        }}
        value={groupAmountInput(value)}
        onChange={handleChange}
        inputMode="decimal"
        {...props}
      />
    );
  },
);
MoneyInput.displayName = "MoneyInput";
