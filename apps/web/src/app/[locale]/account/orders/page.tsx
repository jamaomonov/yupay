"use client";

import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect } from "react";

import type { OrderListOut, OrderOut } from "@/lib/orders-types";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";
import { useLoginModal } from "@/store/useLoginModal";

const STATUS: Record<string, { label: string; cls: string }> = {
  pending_payment: { label: "Ожидает оплаты", cls: "bg-amber-500/15 text-amber-400" },
  paid: { label: "Оплачен", cls: "bg-emerald-500/15 text-emerald-400" },
  fulfilling: { label: "Выполняется", cls: "bg-sky-500/15 text-sky-400" },
  fulfilled: { label: "Выполнен", cls: "bg-emerald-500/15 text-emerald-400" },
  delivered: { label: "Доставлен", cls: "bg-emerald-500/15 text-emerald-400" },
  failed: { label: "Ошибка", cls: "bg-red-500/15 text-red-400" },
  cancelled: { label: "Отменён", cls: "bg-tx-dim/15 text-tx-dim" },
  expired: { label: "Истёк", cls: "bg-tx-dim/15 text-tx-dim" },
  refunded: { label: "Возврат", cls: "bg-tx-dim/15 text-tx-dim" },
  partially_refunded: { label: "Частичный возврат", cls: "bg-tx-dim/15 text-tx-dim" },
};

// Hide checkouts the customer never paid for — these clutter the history with
// "clicked Pay, didn't finish" rows (the scheduler eventually expires them).
const HIDDEN_STATUSES = new Set(["pending_payment", "expired"]);

function orderTitle(o: OrderOut): string {
  const d = o.items[0]?.display;
  if (!d) return `Заказ #${o.id.slice(0, 8)}`;
  const name = d.brand_name || d.product_name;
  const denom = d.denomination ? ` · ${d.denomination}` : "";
  const extra = o.items.length > 1 ? ` +${String(o.items.length - 1)}` : "";
  return `${name}${denom}${extra}`;
}

export default function OrdersPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
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
        {authLoading && <p className="text-tx-dim text-sm">Загрузка…</p>}
      </main>
    );
  }

  const items = (orders.data?.items ?? []).filter((o) => !HIDDEN_STATUSES.has(o.status));
  const settled = !orders.isLoading && !orders.isError;

  return (
    <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
      <h1 className="font-display mb-6 text-3xl font-bold tracking-[-0.02em]">Мои заказы</h1>

      {orders.isLoading && <p className="text-tx-dim text-sm">Загрузка заказов…</p>}

      {orders.isError && (
        <p className="text-sm text-red-400">Не удалось загрузить заказы. Попробуйте позже.</p>
      )}

      {settled && items.length === 0 && (
        <div className="border-border bg-card rounded-2xl border p-10 text-center">
          <p className="text-tx-mute mb-5">Заказов пока нет.</p>
          <Link href={`/${locale}/store`} className={buttonStyles({ size: "sm" })}>
            В каталог
          </Link>
        </div>
      )}

      {items.length > 0 && (
        <ul className="space-y-3">
          {items.map((o) => {
            const st = STATUS[o.status] ?? { label: o.status, cls: "bg-tx-dim/15 text-tx-dim" };
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
                    <p className="text-foreground truncate font-semibold">{orderTitle(o)}</p>
                    <p className="text-tx-dim mt-0.5 text-xs">
                      #{o.id.slice(0, 8)} ·{" "}
                      {new Intl.DateTimeFormat(locale).format(new Date(o.created_at))}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5">
                    <span className="font-display text-foreground font-bold">${o.total_usd}</span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${st.cls}`}
                    >
                      {st.label}
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
