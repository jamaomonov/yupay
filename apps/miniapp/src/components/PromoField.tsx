import { useState } from "react";

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
 * The preview is for display only. `create_order` resolves the code again for
 * itself, so nothing shown here can be spent.
 *
 * Nothing in here throws. It sits inside checkout, and a broken promo box must
 * not be able to stop a sale.
 *
 * Its own file rather than more lines in `TopUp.tsx`, which is already 2172
 * lines against a 300-line soft limit.
 */

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

export interface PromoFieldProps {
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

  if (!isLoggedIn) {
    return <p className="mt-4 text-[13px] text-slate-400">{t("topup.promoSignIn")}</p>;
  }

  async function submit(): Promise<void> {
    const typed = code.trim().toUpperCase();
    if (!typed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const body = await api<PreviewResponse>("/api/v1/affiliate/preview", {
        method: "POST",
        body: JSON.stringify({ code: typed, currency, items }),
      });
      if (!body.applicable || !body.code || !body.percent) {
        setError(rejectionKey(body.reason));
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
    } catch {
      // A failed request must not surface as an unhandled rejection inside the
      // checkout tree.
      setError("topup.promoErrGeneric");
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

  const money = (raw: string): string => formatAmount(Math.round(Number(raw)));

  if (applied) {
    return (
      <div className="mt-4 rounded-2xl border border-lime-400/40 bg-lime-400/5 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="block text-[13px] font-semibold text-lime-300">
              {applied.code} · {t("topup.promoApplied", { percent: applied.percent })}
            </span>
            <span className="mt-0.5 block text-[13px] text-slate-400">
              {t("topup.promoSaved", { amount: money(applied.discount) })}
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
        <div className="mt-2 flex items-baseline gap-2">
          <s className="text-[13px] text-slate-500">{money(applied.totalBefore)}</s>
          <span className="text-lg font-bold">{money(applied.totalAfter)}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-4">
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
          disabled={!code.trim() || busy}
          onClick={() => {
            void submit();
          }}
          className="h-11 shrink-0 rounded-xl border border-slate-700 px-4 text-sm font-semibold disabled:opacity-50"
        >
          {busy ? t("topup.promoChecking") : t("topup.promoApply")}
        </button>
      </div>
      {error !== null && <p className="mt-2 text-[13px] text-red-400">{t(error)}</p>}
    </div>
  );
}
