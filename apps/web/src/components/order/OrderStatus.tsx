"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, CheckCircle2, Copy } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";

import { GuestReviewPanel } from "./GuestReviewPanel";

import type { OrderOut } from "@/lib/orders-types";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";
import { getMyReviews } from "@/lib/reviews";
import { pathFor } from "@/lib/seo";
import { useRealtimeStatus } from "@/store/useRealtimeStatus";

/** Statuses that mean the order is still moving — keep polling. */
const IN_MOTION = new Set(["pending_payment", "paid", "fulfilling", "fulfilled"]);

interface DeliveryOut {
  id: string;
  order_item_id: string;
  channel: string;
  artifact_kind: string;
  artifact: Record<string, unknown>;
  delivered_at: string;
}

interface DeliveryListOut {
  items: DeliveryOut[];
}

export function OrderStatus({ orderId, email }: { orderId: string; email?: string }) {
  const t = useTranslations("web.orders");
  const tr = useTranslations("web.brandReviews");
  const locale = useLocale();
  const { user } = useAuth();
  // Guest identification travels as a header, never a query param — a query
  // param lands in Caddy / proxy access logs and browser history, a header
  // doesn't. Trimmed + lowercased to match what the backend expects.
  const guestHeaders = email ? { "X-Guest-Email": email.trim().toLowerCase() } : {};
  // While the WS is connected, live pushes keep the cache fresh — invalidated
  // messages already trigger a refetch, so polling is redundant. Polling is
  // the fallback for guests, disconnected sockets, and the reconnect window.
  const connected = useRealtimeStatus((s) => s.connected);

  const order = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => apiFetch<OrderOut>(`/orders/${orderId}`, { headers: guestHeaders }),
    refetchInterval: (q) =>
      !connected && q.state.data && IN_MOTION.has(q.state.data.status) ? 4000 : false,
  });

  const status = order.data?.status;

  const deliveries = useQuery({
    queryKey: ["deliveries", orderId],
    enabled: status === "delivered",
    queryFn: () =>
      apiFetch<DeliveryListOut>(`/orders/${orderId}/deliveries`, { headers: guestHeaders }),
  });

  // Fallback rate CTA: even if the delivered modal was skipped or missed, a
  // logged-in buyer who hasn't reviewed this order can rate it from here. Guests
  // can't review, so the query only runs for a signed-in user on a delivered order.
  const myReviews = useQuery({
    queryKey: ["my-reviews"],
    queryFn: () => getMyReviews(),
    enabled: Boolean(user) && status === "delivered",
  });

  if (order.isLoading) return <p className="text-tx-mute">{t("loading")}</p>;
  if (order.isError || !order.data) return <p className="text-[#FF6B6B]">{t("notFound")}</p>;

  const brandSlug = order.data.items[0]?.display?.brand_slug ?? null;
  const alreadyReviewed = (myReviews.data?.items ?? []).some((r) => r.order_id === order.data.id);
  const canRate = status === "delivered" && Boolean(user) && brandSlug !== null && !alreadyReviewed;

  return (
    <div className="border-border bg-card rounded-2xl border p-6">
      <p className="text-tx-dim font-mono text-xs">#{order.data.id.slice(0, 8)}</p>
      <h2 className="font-display mt-2 text-xl font-bold">
        {KNOWN_STATUSES.has(order.data.status)
          ? t(`status.${order.data.status}`)
          : order.data.status}
      </h2>

      {status === "delivered" &&
        deliveries.data?.items.map((d) => <ArtifactReveal key={d.id} artifact={d.artifact} />)}

      {canRate && brandSlug && (
        <Link
          href={pathFor(locale, `/store/${brandSlug}?order=${order.data.id}#reviews`)}
          className={buttonStyles({ size: "sm", className: "mt-4" })}
        >
          {tr("writeCta")}
        </Link>
      )}

      {status === "delivered" && !user && email && brandSlug && (
        <GuestReviewPanel orderId={order.data.id} email={email} />
      )}
    </div>
  );
}

/** Turn `first_name` / `steam-login` into a readable "First Name" label. */
function humanizeKey(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function isScalar(v: unknown): v is string | number {
  return typeof v === "string" || typeof v === "number";
}

/** A key name or an opaque token-shaped value that the buyer will want to copy
 *  (a voucher code, activation key, login, top-up link…). */
function looksCopyable(key: string, value: string): boolean {
  if (/code|key|voucher|pin|serial|token|login|link|url|account|gift/i.test(key)) return true;
  return value.length >= 6 && /[A-Za-z0-9]/.test(value) && !/\s/.test(value);
}

/** One copyable deliverable rendered as a monospace chip with a copy button. */
function CopyChip({ value }: { value: string }) {
  const t = useTranslations("web.orders");
  const [copied, setCopied] = useState(false);
  const onCopy = () => {
    void navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => {
        setCopied(false);
      }, 1500);
    });
  };
  return (
    <button
      type="button"
      onClick={onCopy}
      className="border-border bg-bg hover:border-tx-dim group flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition"
    >
      <code className="text-foreground min-w-0 flex-1 truncate font-mono text-sm font-semibold">
        {value}
      </code>
      <span
        className={`inline-flex shrink-0 items-center gap-1.5 text-xs font-semibold ${
          copied ? "text-emerald-400" : "text-tx-dim group-hover:text-tx-mute"
        }`}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
        {copied ? t("copied") : t("copy")}
      </span>
    </button>
  );
}

/**
 * Clean, per-artifact reveal for a delivered order (replaces the raw JSON dump).
 * Renders each key/value pair with a readable label; copyable deliverables get a
 * monospace copy chip, and a wallet/balance top-up leads with a success line.
 * Defensive: `artifact` is `Record<string, unknown>` from the API.
 */
function ArtifactReveal({ artifact }: { artifact: Record<string, unknown> }) {
  const t = useTranslations("web.orders");
  const entries = Object.entries(artifact);
  if (entries.length === 0) return null;
  const walletCredited = entries.some(([k]) => /wallet|balance|credit/i.test(k));

  return (
    <div className="border-border bg-muted/40 mt-4 rounded-xl border p-4">
      {walletCredited && (
        <p className="mb-3 flex items-center gap-2 text-sm font-semibold text-emerald-400">
          <CheckCircle2 size={16} />
          {t("walletCredited")}
        </p>
      )}
      <dl className="flex flex-col gap-3">
        {entries.map(([key, value]) => {
          const str = isScalar(value) ? String(value) : null;
          return (
            <div key={key} className="flex flex-col gap-1.5">
              <dt className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
                {humanizeKey(key)}
              </dt>
              <dd>
                {str === null ? (
                  <code className="text-tx-mute block whitespace-pre-wrap break-all font-mono text-xs">
                    {JSON.stringify(value, null, 2)}
                  </code>
                ) : looksCopyable(key, str) ? (
                  <CopyChip value={str} />
                ) : (
                  <span className="text-foreground font-mono text-sm">{str}</span>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

/** Statuses with a ``web.orders.status.*`` catalog entry; raw codes fall through. */
const KNOWN_STATUSES = new Set([
  "pending_payment",
  "paid",
  "fulfilling",
  "fulfilled",
  "delivered",
  "failed",
  "refunded",
  "partially_refunded",
  "cancelled",
  "expired",
]);
