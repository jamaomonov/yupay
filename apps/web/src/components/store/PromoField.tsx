"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

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

  async function submit(): Promise<void> {
    const typed = code.trim().toUpperCase();
    if (!typed || busy) return;
    setBusy(true);
    setError(null);
    try {
      // Through `apiFetch`, not a raw `fetch`. It attaches the access token
      // and refreshes it once on a 401 — written with a bare fetch, this
      // endpoint (which is signed-in only) answered 401 for every buyer and
      // the field showed "could not check" to people whose code was fine.
      const body = await apiFetch<PreviewResponse>("/affiliate/preview", {
        method: "POST",
        body: { code: typed, currency, items },
      });
      if (!body.applicable || !body.code || !body.percent) {
        setError(REASON_KEYS[body.reason ?? ""] ?? "promoErrGeneric");
        onChange(null);
        return;
      }
      const next: AppliedPromo = {
        code: body.code,
        percent: body.percent,
        totalBefore: body.total_before,
        totalAfter: body.total_after,
        discount: body.discount,
      };
      setApplied(next);
      onChange(next);
    } catch (err) {
      // A guest reaches this branch through the 401 the endpoint answers, and
      // deserves the sign-in line rather than "could not check" — the field is
      // rendered for a signed-in buyer, but a session can expire while the
      // page is open.
      setError(err instanceof ApiError && err.status === 401 ? "promoSignIn" : "promoErrGeneric");
      onChange(null);
    } finally {
      setBusy(false);
    }
  }

  function remove(): void {
    setApplied(null);
    setCode("");
    setError(null);
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
              {t("promoSaved", { amount: money(applied.discount) })}
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
        <div className="mt-2 flex items-baseline gap-2">
          <s data-testid="promo-total-before" className="text-tx-dim text-[13px]">
            {money(applied.totalBefore)}
          </s>
          <span data-testid="promo-total-after" className="font-display text-lg font-bold">
            {money(applied.totalAfter)}
          </span>
        </div>
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
          disabled={!code.trim() || busy}
          onClick={() => {
            void submit();
          }}
          className="border-border rounded-btn h-11 shrink-0 border px-4 text-sm font-semibold disabled:opacity-50"
        >
          {busy ? t("promoChecking") : t("promoApply")}
        </button>
      </div>
      {error && <p className="text-danger mt-2 text-[13px]">{t(error)}</p>}
    </div>
  );
}
