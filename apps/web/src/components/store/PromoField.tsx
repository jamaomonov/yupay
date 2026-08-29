"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiFetch } from "@/lib/client";
import { formatUzs } from "@/lib/seo";

/**
 * The partner promo code field on checkout.
 *
 * Every number it shows comes from the server's preview response, never from
 * arithmetic here. Subtracting a server-computed discount from a
 * client-computed total is how a checkout comes to display a price nobody is
 * going to charge — so `total_before` and `total_after` are both taken as
 * given, and the host uses `total_after` on its pay button.
 *
 * Which is also why the code is re-priced whenever the cart moves. It used to
 * be priced once, on apply, and the answer kept: a buyer who applied a code and
 * then switched to a dearer package was shown the cheaper one's discounted
 * total, on the pay button, while the order was priced at the dearer one. The
 * charge was always right — `create_order` resolves the code itself — but the
 * quote was not.
 *
 * The preview is for display only. `create_order` resolves the code again for
 * itself, so nothing shown here can be spent: a code deactivated between the
 * two calls produces an order at full price, which the host reports through
 * `promoDropped`.
 *
 * Nothing in here throws. It sits inside checkout, and a broken promo box must
 * not be able to stop a sale.
 */

/** Server rejection reasons mapped to their own sentence. An unlisted reason —
 *  one the server learned before this component did — falls through to the
 *  generic message rather than rendering an empty box. */
const REASON_KEYS: Record<string, string> = {
  unknown: "promoErrUnknown",
  already_used: "promoErrAlreadyUsed",
  not_first_order: "promoErrNotFirstOrder",
  own_code: "promoErrOwnCode",
  pending_coded_order: "promoErrPending",
};

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

export interface PromoFieldProps {
  locale: string;
  /** The cart to price against. Empty before a package is chosen — the field
   *  still renders, so a buyer holding a code can see this checkout takes one. */
  items: PromoCartItem[];
  currency: string;
  isLoggedIn: boolean;
  /** Fires whenever the applied promo changes, including back to null. */
  onChange: (promo: AppliedPromo | null) => void;
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

export function PromoField({ locale, items, currency, isLoggedIn, onChange }: PromoFieldProps) {
  const t = useTranslations("web.store");
  const [code, setCode] = useState("");
  const [applied, setApplied] = useState<AppliedPromo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [repricing, setRepricing] = useState(false);

  const hasCart = items.length > 0;
  // Which cart this is, as a value rather than a reference. The host rebuilds
  // the array literal on every render, so an effect keyed on `items` itself
  // would re-fire forever.
  const cartKey = JSON.stringify({ currency, items });

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
    const forCart = JSON.stringify({
      currency: currencyRef.current,
      items: itemsRef.current,
    });
    const settle = (): void => {
      if (seq !== seqRef.current) return;
      if (mode === "apply") setBusy(false);
      else setRepricing(false);
    };
    try {
      // Through `apiFetch`, not a raw `fetch`. It attaches the access token
      // and refreshes it once on a 401 — written with a bare fetch, this
      // endpoint (which is signed-in only) answered 401 for every buyer and
      // the field showed "could not check" to people whose code was fine.
      const body = await apiFetch<PreviewResponse>("/affiliate/preview", {
        method: "POST",
        body: { code: typed, currency: currencyRef.current, items: itemsRef.current },
      });
      if (seq !== seqRef.current) return;
      if (!body.applicable || !body.code || !body.percent) {
        pricedForRef.current = null;
        setApplied(null);
        setError(REASON_KEYS[body.reason ?? ""] ?? "promoErrGeneric");
        onChangeRef.current(null);
        return;
      }
      pricedForRef.current = forCart;
      setApplied({
        code: body.code,
        percent: body.percent,
        totalBefore: body.total_before,
        totalAfter: body.total_after,
        discount: body.discount,
      });
      setError(null);
      onChangeRef.current({
        code: body.code,
        percent: body.percent,
        totalBefore: body.total_before,
        totalAfter: body.total_after,
        discount: body.discount,
      });
    } catch (err) {
      if (seq !== seqRef.current) return;
      // A guest reaches this branch through the 401 the endpoint answers, and
      // deserves the sign-in line rather than "could not check" — the field is
      // rendered for a signed-in buyer, but a session can expire while the
      // page is open.
      pricedForRef.current = null;
      setApplied(null);
      setError(err instanceof ApiError && err.status === 401 ? "promoSignIn" : "promoErrGeneric");
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

  // Leaving the tree must take the discount with it. The Mini App unmounts
  // this field when the buyer steps back to the package picker, and a discount
  // that outlived it sat on the pay button with nothing on screen to explain
  // it.
  useEffect(
    () => () => {
      onChangeRef.current(null);
    },
    [],
  );

  // A guest cannot use a partner code — the code binds a buyer to a partner,
  // and a guest has no account to bind. Half of all orders here are guest
  // orders, so this branch is the common one on web, and it has to read as an
  // invitation rather than a dead field.
  if (!isLoggedIn) {
    return (
      <div className="border-border bg-muted rounded-btn mt-5 border px-3 py-3">
        <p className="text-tx-mute text-[13px]">{t("promoSignIn")}</p>
      </div>
    );
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

  const money = (raw: string): string => formatUzs(locale, Math.round(Number(raw)));

  if (applied) {
    return (
      <div className="border-primary/40 bg-primary/5 rounded-btn mt-5 border px-3 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-primary block text-[13px] font-semibold">
              <span>{applied.code}</span>
              {" · "}
              <span>{t("promoApplied", { percent: tidyPercent(applied.percent) })}</span>
            </span>
            <span className="text-tx-mute mt-0.5 block text-[13px]">
              {repricing
                ? t("promoRechecking")
                : t("promoSaved", { amount: money(applied.discount) })}
            </span>
          </div>
          <button
            type="button"
            onClick={remove}
            className="text-tx-mute shrink-0 text-[13px] underline"
          >
            {t("promoRemove")}
          </button>
        </div>
        {!repricing && (
          <div className="mt-2 flex items-baseline gap-2">
            <s data-testid="promo-total-before" className="text-tx-dim text-[13px]">
              {money(applied.totalBefore)}
            </s>
            <span data-testid="promo-total-after" className="font-display text-lg font-bold">
              {money(applied.totalAfter)}
            </span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="mt-5">
      <label htmlFor="promo-code" className="text-tx-mute mb-2 block text-[13px] font-semibold">
        {t("promoLabel")}
      </label>
      <div className="flex gap-2">
        <input
          id="promo-code"
          value={code}
          onChange={(e) => {
            setCode(e.target.value.toUpperCase());
            setError(null);
          }}
          placeholder={t("promoPlaceholder")}
          maxLength={32}
          autoCapitalize="characters"
          autoComplete="off"
          className="border-border bg-card rounded-btn h-11 flex-1 border px-3 text-sm"
        />
        <button
          type="button"
          disabled={!code.trim() || busy || !hasCart}
          onClick={submit}
          className="border-border rounded-btn h-11 shrink-0 border px-4 text-sm font-semibold disabled:opacity-50"
        >
          {busy ? t("promoChecking") : t("promoApply")}
        </button>
      </div>
      {/* The code cannot be checked against nothing, and a button that just
          sits there dead is a puzzle. Say what is missing. */}
      {!hasCart && <p className="text-tx-mute mt-2 text-[13px]">{t("promoNeedPackage")}</p>}
      {error && <p className="text-danger mt-2 text-[13px]">{t(error)}</p>}
    </div>
  );
}
