"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ticket } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { buttonStyles } from "@/lib/button";
import { promoErrorKey } from "@/lib/promo";
import { formatUzs } from "@/lib/seo";
import { redeemPromo } from "@/lib/wallet";
import { toast } from "@/store/useToast";

export interface PromoCodeCardProps {
  locale: string;
}

/**
 * Promo code redemption on the web wallet — the Mini App's `PromoCodeCard`
 * (`apps/miniapp/src/pages/Wallet.tsx`) ported to this surface's own card
 * styling and its `useToast` queue instead of the Mini App's toast hook.
 *
 * Redemption credits `user_wallet` directly (`promo/service.py`), so a
 * success invalidates the `["wallet"]` query the hero balance above reads —
 * the number the customer just changed is the number they see next render.
 */
export function PromoCodeCard({ locale }: PromoCodeCardProps) {
  const t = useTranslations("web.wallet");
  const qc = useQueryClient();
  const [code, setCode] = useState("");

  const redeem = useMutation({
    // A fresh Idempotency-Key per press, minted here rather than hoisted
    // into a ref or module scope — see `redeemPromo`'s docstring on why
    // reuse is wrong for this call, unlike a top-up retry.
    mutationFn: (value: string) => redeemPromo(value, crypto.randomUUID()),
    onSuccess: (data) => {
      setCode("");
      // Formatted the same way the balance card above renders its figure —
      // not a raw `${amount} ${currency}` concatenation, which is the bug
      // the Mini App fixed on this exact toast (2026-09-04 review).
      toast.success(
        t("promoSuccess", {
          amount: formatUzs(locale, Math.round(Number.parseFloat(data.amount) || 0)),
        }),
      );
      // The hero balance card sits right above — refresh it immediately.
      void qc.invalidateQueries({ queryKey: ["wallet"] });
    },
    onError: (err) => {
      toast.error(t(promoErrorKey(err)));
    },
  });

  const trimmed = code.trim();
  const submit = (): void => {
    if (!trimmed || redeem.isPending) return;
    redeem.mutate(trimmed);
  };

  return (
    <section className="border-border bg-card mb-8 rounded-2xl border p-6">
      <label htmlFor="wallet-promo-code" className="mb-3 flex items-center gap-1.5">
        <Ticket size={14} className="text-primary" aria-hidden="true" />
        <span className="text-tx-dim font-mono text-[11px] font-bold uppercase tracking-[0.16em]">
          {t("promoTitle")}
        </span>
      </label>
      <div className="flex gap-2">
        <input
          id="wallet-promo-code"
          value={code}
          onChange={(e) => {
            setCode(e.target.value.toUpperCase());
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder={t("promoPlaceholder")}
          maxLength={64}
          autoCapitalize="characters"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="send"
          className="border-border bg-card focus:border-primary rounded-btn h-11 min-w-0 flex-1 border px-3 text-sm font-semibold uppercase tracking-wide outline-none transition"
        />
        <button
          type="button"
          onClick={submit}
          disabled={!trimmed || redeem.isPending}
          className={buttonStyles({ variant: "ghost", size: "md", className: "shrink-0" })}
        >
          {t("promoApply")}
        </button>
      </div>
    </section>
  );
}
