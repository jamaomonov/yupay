"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, use } from "react";

import { OrderStatus } from "@/components/order/OrderStatus";
import { OrderStatusSkeleton } from "@/components/order/OrderStatusSkeleton";

function OrderPageInner({ orderId }: { orderId: string }) {
  const rawEmail = useSearchParams().get("email");
  const props = rawEmail ? { orderId, email: rawEmail } : { orderId };
  return <OrderStatus {...props} />;
}

export default function OrderPage({ params }: { params: Promise<{ orderId: string }> }) {
  const { orderId } = use(params);
  return (
    <main className="mx-auto max-w-[560px] px-4 pb-16 pt-[120px]">
      {/* Same skeleton the component uses for its own loading state, so the
          Suspense boundary and the data fetch look like one continuous load. */}
      <Suspense fallback={<OrderStatusSkeleton />}>
        <OrderPageInner orderId={orderId} />
      </Suspense>
    </main>
  );
}
