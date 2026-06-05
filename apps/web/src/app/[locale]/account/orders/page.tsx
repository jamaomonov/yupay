"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect } from "react";

import type { OrderListOut } from "@/lib/orders-types";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";

const STATUS_LABELS: Record<string, string> = {
  pending_payment: "Ожидает оплаты",
  paid: "Оплачен",
  fulfilling: "Выполняется",
  fulfilled: "Выполнен",
  delivered: "Доставлен",
  failed: "Ошибка",
  cancelled: "Отменён",
  expired: "Истёк",
  refunded: "Возврат",
  partially_refunded: "Частичный возврат",
};

export default function OrdersPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  const { user, isLoading: authLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !user) {
      router.push(`/${locale}/login`);
    }
  }, [authLoading, user, router, locale]);

  const orders = useQuery({
    queryKey: ["orders"],
    queryFn: () => apiFetch<OrderListOut>("/orders"),
    enabled: Boolean(user),
  });

  if (authLoading) {
    return (
      <main className="mx-auto max-w-[560px] px-4 py-16">
        <p className="text-tx-dim text-sm">Загрузка…</p>
      </main>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <main className="mx-auto max-w-[560px] px-4 py-16">
      <div className="mb-6 flex items-center gap-3">
        <Link
          href={`/${locale}/account`}
          className={buttonStyles({ variant: "ghost", size: "xs" })}
        >
          ← Аккаунт
        </Link>
        <h1 className="font-display text-2xl font-bold tracking-[-0.02em]">Мои заказы</h1>
      </div>

      {orders.isLoading && <p className="text-tx-dim text-sm">Загрузка заказов…</p>}

      {orders.isError && (
        <p className="text-sm text-red-500">Не удалось загрузить заказы. Попробуйте позже.</p>
      )}

      {orders.data?.items.length === 0 && (
        <div className="border-border bg-card rounded-2xl border p-8 text-center">
          <p className="text-tx-dim text-sm">Заказов пока нет.</p>
        </div>
      )}

      {(orders.data?.items.length ?? 0) > 0 && (
        <ul className="space-y-3">
          {orders.data?.items.map((o) => (
            <li key={o.id}>
              <Link
                href={`/${locale}/orders/${o.id}`}
                className="border-border bg-card hover:border-tx-dim block rounded-xl border p-4 transition"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-sm font-semibold">#{o.id.slice(0, 8)}</p>
                    <p className="text-tx-dim mt-0.5 text-xs">
                      {new Intl.DateTimeFormat(locale).format(new Date(o.created_at))}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-0.5">
                    <span className="text-foreground text-sm font-semibold">${o.total_usd}</span>
                    <span className="text-tx-dim text-xs">
                      {STATUS_LABELS[o.status] ?? o.status}
                    </span>
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
