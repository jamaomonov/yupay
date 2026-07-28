"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import type { OrderOut } from "@/lib/orders-types";

import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";
import { getMyReviews } from "@/lib/reviews";
import { useOrderDeliveredModal } from "@/store/useOrderDeliveredModal";

/**
 * Global "order delivered" modal — mounted once in the locale layout, opened
 * by `useOrderSocket` on an `order.delivered` WS message
 * (`useOrderDeliveredModal`). Mirrors `LoginModal`'s dialog styling.
 *
 * There is intentionally no "order failed" counterpart: fulfillment failures
 * keep the order at `fulfilling` for admin remediation, never a
 * customer-facing status (see the realtime module's domain rule).
 */
export function OrderDeliveredModal() {
  const t = useTranslations("web.orderResult");
  const locale = useLocale();
  const { orderId, close } = useOrderDeliveredModal();
  const cardRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  // Same query key `useOrderSocket` invalidates on `order.delivered`, so the
  // fetch below is already warm by the time the socket message opens this
  // modal (invalidation triggers refetch of the same cache entry).
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

  // Focus management: move focus into the dialog on open, restore it to the
  // element that opened the modal on close (WCAG 2.4.3 focus order).
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

  const display = order.data.items[0]?.display ?? null;
  const alreadyReviewed = (myReviews.data?.items ?? []).some((r) => r.order_id === orderId);
  const canRate = Boolean(display?.brand_slug) && !alreadyReviewed;

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

        {canRate && display && (
          <Link
            href={`/${locale}/store/${display.brand_slug}?order=${orderId}#reviews`}
            onClick={close}
            className={buttonStyles({ className: "mt-6 w-full" })}
          >
            {t("rateCta")}
          </Link>
        )}
      </div>
    </div>
  );
}
