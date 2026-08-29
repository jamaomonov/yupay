import { useCallback, useEffect, useRef, useState } from "react";

import type { MessageKey } from "@/lib/i18n/messages";

import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

/**
 * The partner promo code field on the Mini App checkout.
 *
 * Every number it shows comes from the server's preview response, never from
 * arithmetic here. Subtracting a server-computed discount from a
 * client-computed total is how a checkout comes to display a price nobody is
 * going to charge — so `total_before` and `total_after` are both taken as
 * given, and the host uses `total_after` on its pay button.
 *
 * Which is also why the code is re-priced whenever the cart moves, and why
 * leaving the tree withdraws the discount. Both were missing: stepping back to
 * the package picker unmounted this field but left the host's discount in
 * place, so the pay button offered a cheaper package's price for a dearer one,
 * with nothing on screen to explain where the discount had come from.
 *
 * The preview is for display only. `create_order` resolves the code again for
 * itself, so nothing shown here can be spent.
 *
 * Nothing in here throws. It sits inside checkout, and a broken promo box must
 * not be able to stop a sale.
 *
 * Its own file rather than more lines in `TopUp.tsx`, which is already 2172
 * lines against a 300-line soft limit.
 */

/** How still the cart has to be before the code is re-priced. A
 *  variable-amount SKU rewrites the cart on every keystroke, and `/preview` is
 *  bucketed at 120 calls a minute — one request per character would spend that
 *  on a single order. */
const REPRICE_DEBOUNCE_MS = 400;

/** "10.00" → "10". The API returns percentages from a Numeric(5,2) column, and
 *  "Скидка 10.00%" reads like a rounding artefact rather than a round number. */
function tidyPercent(raw: string): string {
  const n = Number(raw);
  return Number.isFinite(n) ? String(n) : raw;
}

export interface PromoCartItem {
  sku_id: string;
  qty: number;
  amount_usd?: string;
}

export interface AppliedPromo {
  /** The code as the server normalised it — this is what checkout sends. */
  code: string;
  percent: string;
  /** Server-computed, in the order's currency. */
  totalBefore: string;
  totalAfter: string;
  discount: string;
}

interface PreviewResponse {
  applicable: boolean;
  reason?: string;
  code?: string;
  percent?: string;
  currency: string;
  total_before: string;
  total_after: string;
  discount: string;
}

/** Server rejection reasons mapped to their own message key.
 *
 * Exported so it can be tested directly: this app has no React rendering
 * harness (no jsdom, no testing-library), and it tests exported logic instead —
 * the same shape `OrderSuccess.tsx` uses for `providerLabel`.
 *
 * An unlisted reason — one the server learned before this component did —
 * falls through to the generic message rather than rendering an empty box.
 */
export function rejectionKey(reason: string | undefined): MessageKey {
  const map: Record<string, MessageKey> = {
    unknown: "topup.promoErrUnknown",
    already_used: "topup.promoErrAlreadyUsed",
    not_first_order: "topup.promoErrNotFirstOrder",
    own_code: "topup.promoErrOwnCode",
    pending_coded_order: "topup.promoErrPending",
  };
  return map[reason ?? ""] ?? "topup.promoErrGeneric";
}

/** Which cart this is, as a value rather than a reference — the host rebuilds
 *  the array literal on every render, so an effect keyed on `items` itself
 *  would re-fire forever. Exported for its own test: this app renders no
 *  components under test, so the re-pricing trigger is checked here. */
export function cartSignature(currency: string, items: PromoCartItem[]): string {
  return JSON.stringify({ currency, items });
}

export interface PromoFieldProps {
  /** The cart to price against. Empty before a package is chosen — the field
   *  still renders, so a buyer holding a code can see this checkout takes one. */
  items: PromoCartItem[];
  currency: string;
  /** Normally true: a Mini App buyer is authenticated from Telegram initData
   *  at boot. Not assumed, though — `bootstrapAuth` has an `anonymous`
   *  decision for a session opened outside Telegram or with no init data, and
   *  an assumption that quietly stops holding is worse than a branch that
   *  rarely renders. */
  isLoggedIn: boolean;
  /** Formats an amount the same way the pay button beside it does. Passed in
   *  rather than imported so the two cannot drift. */
  formatAmount: (value: number) => string;
  onChange: (promo: AppliedPromo | null) => void;
}

export function PromoField({
  items,
  currency,
  isLoggedIn,
  formatAmount,
  onChange,
}: PromoFieldProps) {
  const { t } = useT();
  const [code, setCode] = useState("");
  const [applied, setApplied] = useState<AppliedPromo | null>(null);
  const [error, setError] = useState<MessageKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [repricing, setRepricing] = useState(false);

  const hasCart = items.length > 0;
  const cartKey = cartSignature(currency, items);

  // Read through refs inside the async work: `onChange` is an inline closure
  // and `items` a fresh array on each of the host's renders, and neither
  // belongs in a dependency list. Declared first so this effect commits before
  // the re-pricing one below reads them.
  const onChangeRef = useRef(onChange);
  const itemsRef = useRef(items);
  const currencyRef = useRef(currency);
  useEffect(() => {
    onChangeRef.current = onChange;
    itemsRef.current = items;
    currencyRef.current = currency;
  });

  // Only the newest preview may land. Switching packages twice in quick
  // succession otherwise lets the first response overwrite the second, which
  // puts a discount for a cart nobody has back on the pay button.
  const seqRef = useRef(0);
  /** The cart the current `applied` was priced against, or null if none is. */
  const pricedForRef = useRef<string | null>(null);

  const check = useCallback(async (typed: string, mode: "apply" | "reprice"): Promise<void> => {
    const seq = ++seqRef.current;
    const forCart = cartSignature(currencyRef.current, itemsRef.current);
    const settle = (): void => {
      if (seq !== seqRef.current) return;
      if (mode === "apply") setBusy(false);
      else setRepricing(false);
    };
    try {
      const body = await api<PreviewResponse>("/api/v1/affiliate/preview", {
        method: "POST",
        body: JSON.stringify({
          code: typed,
          currency: currencyRef.current,
          items: itemsRef.current,
        }),
      });
      if (seq !== seqRef.current) return;
      if (!body.applicable || !body.code || !body.percent) {
        pricedForRef.current = null;
        setApplied(null);
        setError(rejectionKey(body.reason));
        onChangeRef.current(null);
        return;
      }
      const next: AppliedPromo = {
        code: body.code,
        percent: body.percent,
        totalBefore: body.total_before,
        totalAfter: body.total_after,
        discount: body.discount,
      };
      pricedForRef.current = forCart;
      setApplied(next);
      setError(null);
      onChangeRef.current(next);
    } catch {
      // A failed request must not surface as an unhandled rejection inside the
      // checkout tree.
      if (seq !== seqRef.current) return;
      pricedForRef.current = null;
      setApplied(null);
      setError("topup.promoErrGeneric");
      onChangeRef.current(null);
    } finally {
      settle();
    }
  }, []);

  // The cart moved under an applied code. Until the server has re-priced it,
  // the host must have no discount at all: the alternative is the old one,
  // which belongs to a package the buyer no longer has.
  useEffect(() => {
    if (applied === null) return;
    if (pricedForRef.current === cartKey) return;

    if (!hasCart) {
      seqRef.current += 1;
      pricedForRef.current = null;
      setApplied(null);
      setRepricing(false);
      onChangeRef.current(null);
      return;
    }

    setRepricing(true);
    onChangeRef.current(null);
    const timer = setTimeout(() => {
      void check(applied.code, "reprice");
    }, REPRICE_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [applied, cartKey, hasCart, check]);

  // Leaving the tree must take the discount with it. Stepping back to the
  // package picker unmounts this field, and a discount that outlived it sat on
  // the pay button with nothing on screen to explain it.
  useEffect(
    () => () => {
      onChangeRef.current(null);
    },
    [],
  );

  if (!isLoggedIn) {
    return <p className="mt-4 text-[13px] text-slate-400">{t("topup.promoSignIn")}</p>;
  }

  function submit(): void {
    const typed = code.trim().toUpperCase();
    if (!typed || busy || !hasCart) return;
    setBusy(true);
    setError(null);
    void check(typed, "apply");
  }

  function remove(): void {
    // Bumps the sequence so an in-flight re-price cannot resurrect what was
    // just removed.
    seqRef.current += 1;
    pricedForRef.current = null;
    setApplied(null);
    setCode("");
    setError(null);
    setRepricing(false);
    onChange(null);
  }

  const money = (raw: string): string => formatAmount(Math.round(Number(raw)));

  if (applied) {
    return (
      <div
        className="my-4 rounded-2xl border border-lime-400/40 bg-lime-400/5 px-4 py-3"
        data-testid="promo-applied"
      >
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="block text-[13px] font-semibold text-lime-300">
              {applied.code} · {t("topup.promoApplied", { percent: tidyPercent(applied.percent) })}
            </span>
            <span className="mt-0.5 block text-[13px] text-slate-400">
              {repricing
                ? t("topup.promoRechecking")
                : t("topup.promoSaved", { amount: money(applied.discount) })}
            </span>
          </div>
          <button
            type="button"
            onClick={remove}
            className="shrink-0 text-[13px] text-slate-400 underline"
          >
            {t("topup.promoRemove")}
          </button>
        </div>
        {!repricing && (
          <div className="mt-2 flex items-baseline gap-2">
            <s className="text-[13px] text-slate-500">{money(applied.totalBefore)}</s>
            <span className="text-lg font-bold">{money(applied.totalAfter)}</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="my-4">
      <label htmlFor="promo-code" className="mb-2 block text-[13px] font-semibold text-slate-400">
        {t("topup.promoLabel")}
      </label>
      <div className="flex gap-2">
        <input
          id="promo-code"
          value={code}
          onChange={(e) => {
            setCode(e.target.value.toUpperCase());
            setError(null);
          }}
          placeholder={t("topup.promoPlaceholder")}
          maxLength={32}
          autoCapitalize="characters"
          autoComplete="off"
          className="h-11 flex-1 rounded-xl border border-slate-700 bg-slate-900 px-3 text-sm"
        />
        <button
          type="button"
          disabled={!code.trim() || busy || !hasCart}
          onClick={submit}
          className="h-11 shrink-0 rounded-xl border border-slate-700 px-4 text-sm font-semibold disabled:opacity-50"
        >
          {busy ? t("topup.promoChecking") : t("topup.promoApply")}
        </button>
      </div>
      {/* The code cannot be checked against nothing, and a button that just
          sits there dead is a puzzle. Say what is missing. */}
      {!hasCart && <p className="mt-2 text-[13px] text-slate-400">{t("topup.promoNeedPackage")}</p>}
      {error !== null && <p className="mt-2 text-[13px] text-red-400">{t(error)}</p>}
    </div>
  );
}
