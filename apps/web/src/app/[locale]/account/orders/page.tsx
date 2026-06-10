"use client";

import { formatMoney } from "@yupay/utils";
import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { use, useEffect } from "react";

import type { OrderListOut, OrderOut } from "@/lib/orders-types";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";
import { useLoginModal } from "@/store/useLoginModal";

const STATUS_CLS: Record<string, string> = {
  pending_payment: "bg-amber-500/15 text-amber-400",
  paid: "bg-emerald-500/15 text-emerald-400",
  fulfilling: "bg-sky-500/15 text-sky-400",
  fulfilled: "bg-emerald-500/15 text-emerald-400",
  delivered: "bg-emerald-500/15 text-emerald-400",
  failed: "bg-red-500/15 text-red-400",
  cancelled: "bg-tx-dim/15 text-tx-dim",
  expired: "bg-tx-dim/15 text-tx-dim",
  refunded: "bg-tx-dim/15 text-tx-dim",
  partially_refunded: "bg-tx-dim/15 text-tx-dim",
};

// Hide checkouts the customer never paid for — these clutter the history with
// "clicked Pay, didn't finish" rows (the scheduler eventually expires them).
const HIDDEN_STATUSES = new Set(["pending_payment", "expired"]);

function orderTitle(o: OrderOut, fallback: string): string {
  const d = o.items[0]?.display;
  if (!d) return fallback;
  const name = d.brand_name || d.product_name;
  const denom = d.denomination ? ` · ${d.denomination}` : "";
  const extra = o.items.length > 1 ? ` +${String(o.items.length - 1)}` : "";
  return `${name}${denom}${extra}`;
}

export default function OrdersPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  const t = useTranslations("web.orders");
  const { user, isLoading: authLoading } = useAuth();
  const router = useRouter();
  const openLogin = useLoginModal((s) => s.open);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace(`/${locale}`);
      openLogin();
    }
  }, [authLoading, user, router, locale, openLogin]);

  const orders = useQuery({
    queryKey: ["orders"],
    queryFn: () => apiFetch<OrderListOut>("/orders"),
    enabled: Boolean(user),
  });

  if (authLoading || !user) {
    return (
      <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
        {authLoading && <p className="text-tx-dim text-sm">{t("loading")}</p>}
      </main>
    );
  }

  const items = (orders.data?.items ?? []).filter((o) => !HIDDEN_STATUSES.has(o.status));
  const settled = !orders.isLoading && !orders.isError;

  return (
    <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
      <h1 className="font-display mb-6 text-3xl font-bold tracking-[-0.02em]">{t("title")}</h1>

      {orders.isLoading && <p className="text-tx-dim text-sm">{t("listLoading")}</p>}

      {orders.isError && <p className="text-sm text-red-400">{t("listError")}</p>}

      {settled && items.length === 0 && (
        <div className="border-border bg-card rounded-2xl border p-10 text-center">
          <p className="text-tx-mute mb-5">{t("empty")}</p>
          <Link href={`/${locale}/store`} className={buttonStyles({ size: "sm" })}>
            {t("toCatalog")}
          </Link>
        </div>
      )}

      {items.length > 0 && (
        <ul className="space-y-3">
          {items.map((o) => {
            const cls = STATUS_CLS[o.status] ?? "bg-tx-dim/15 text-tx-dim";
            const label = o.status in STATUS_CLS ? t(`status.${o.status}`) : o.status;
            const img = o.items[0]?.display?.image_url;
            return (
              <li key={o.id}>
                <Link
                  href={`/${locale}/orders/${o.id}`}
                  className="border-border bg-card hover:border-tx-dim flex items-center gap-4 rounded-2xl border p-4 transition"
                >
                  <span className="bg-muted relative h-12 w-12 shrink-0 overflow-hidden rounded-xl">
                    {img && (
                      <Image
                        src={img}
                        alt=""
                        fill
                        unoptimized
                        sizes="48px"
                        className="object-contain"
                      />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-foreground truncate font-semibold">
                      {orderTitle(o, t("fallbackTitle", { id: o.id.slice(0, 8) }))}
                    </p>
                    <p className="text-tx-dim mt-0.5 text-xs">
                      #{o.id.slice(0, 8)} ·{" "}
                      {new Intl.DateTimeFormat(locale).format(new Date(o.created_at))}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    <span className="font-display text-foreground font-bold">
                      {formatMoney(o.total_usd, "USD", locale)}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
                      {label}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
