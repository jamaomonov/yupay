"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, use } from "react";

import { OrderStatus } from "@/components/order/OrderStatus";

function OrderPageInner({ orderId }: { orderId: string }) {
  const rawEmail = useSearchParams().get("email");
  const props = rawEmail ? { orderId, email: rawEmail } : { orderId };
  return <OrderStatus {...props} />;
}

export default function OrderPage({ params }: { params: Promise<{ orderId: string }> }) {
  const { orderId } = use(params);
  return (
    <main className="mx-auto max-w-[560px] px-4 py-16">
      <Suspense fallback={<p className="text-tx-mute">Загрузка…</p>}>
        <OrderPageInner orderId={orderId} />
      </Suspense>
    </main>
  );
}
