"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useSyncExternalStore } from "react";

import { OrderStatus } from "@/components/order/OrderStatus";
import { OrderStatusSkeleton } from "@/components/order/OrderStatusSkeleton";
import { guestEmailFor, rememberGuestEmail } from "@/lib/guest-orders";

const noSubscription = () => () => undefined;

function OrderPageInner({ orderId }: { orderId: string }) {
  const searchParams = useSearchParams();
  const fromLink = searchParams.get("email");
  // Read on the client only: storage does not exist while prerendering, and a
  // guest's email must not be guessed into the server HTML.
  const stored = useSyncExternalStore(
    noSubscription,
    () => guestEmailFor(orderId),
    () => null,
  );

  useEffect(() => {
    if (fromLink === null) return;
    // An emailed link or an acquirer's return still carries `?email=`. Keep it
    // in this browser and take it out of the address bar, so later SPA
    // navigations and analytics hits never see it.
    rememberGuestEmail(orderId, fromLink);
    const url = new URL(window.location.href);
    url.searchParams.delete("email");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  }, [fromLink, orderId]);

  const email = fromLink ?? stored;
  const props = email ? { orderId, email } : { orderId };
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
