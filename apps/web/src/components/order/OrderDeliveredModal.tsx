"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import type { OrderOut } from "@/lib/orders-types";

import { ReviewAsk } from "@/components/store/ReviewAsk";
import { apiFetch } from "@/lib/client";
import { getMyReviews } from "@/lib/reviews";
import { useOrderDeliveredModal } from "@/store/useOrderDeliveredModal";

/**
 * Global "order delivered" modal — mounted once in the locale layout, opened
 * by `useOrderSocket` on an `order.delivered` WS message.
 *
 * The review is collected here as a one-tap star row. There is intentionally
 * no "order failed" counterpart: fulfillment failures keep the order at
 * `fulfilling` for admin remediation.
 */
export function OrderDeliveredModal() {
  const t = useTranslations("web.orderResult");
  const { orderId, close } = useOrderDeliveredModal();
  const cardRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  const order = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => apiFetch<OrderOut>(`/orders/${orderId ?? ""}`),
    enabled: orderId !== null,
  });

  const myReviews = useQuery({
    queryKey: ["my-reviews"],
    queryFn: () => getMyReviews(),
    enabled: orderId !== null,
  });

  const isOpen = orderId !== null && !order.isLoading && Boolean(order.data);

  useEffect(() => {
    if (isOpen) {
      openerRef.current = document.activeElement as HTMLElement | null;
      cardRef.current?.focus();
    } else if (openerRef.current) {
      openerRef.current.focus();
      openerRef.current = null;
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [isOpen, close]);

  if (!isOpen || !order.data) return null;

  const display = order.data.items[0]?.display;
  const brandSlug = display?.brand_slug ?? null;
  const alreadyReviewed = (myReviews.data?.items ?? []).some((r) => r.order_id === orderId);
  const canRate = brandSlug !== null && !alreadyReviewed;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("deliveredTitle")}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
    >
      <button
        type="button"
        aria-hidden="true"
        tabIndex={-1}
        onClick={close}
        className="bg-bg/80 absolute inset-0 backdrop-blur-sm"
      />
      <div
        ref={cardRef}
        tabIndex={-1}
        className="border-border bg-card relative z-10 w-full max-w-[420px] rounded-2xl border p-7 shadow-2xl outline-none"
      >
        <button
          type="button"
          onClick={close}
          aria-label={t("close")}
          className="text-tx-mute hover:bg-muted hover:text-foreground absolute right-3 top-3 flex h-10 w-10 items-center justify-center rounded-full transition"
        >
          <X size={18} />
        </button>

        <h2 className="font-display max-w-[16rem] text-2xl font-bold leading-tight tracking-[-0.02em]">
          {t("deliveredTitle")}
        </h2>
        <p className="text-tx-mute mt-3 text-sm leading-relaxed">{t("deliveredBody")}</p>

        {canRate && orderId !== null && brandSlug !== null && (
          <ReviewAsk
            key={orderId}
            variant="bare"
            className="border-border/60 mt-5 border-t pt-5"
            orderId={orderId}
            brandSlug={brandSlug}
            brandName={display?.brand_name ?? null}
          />
        )}
      </div>
    </div>
  );
}
