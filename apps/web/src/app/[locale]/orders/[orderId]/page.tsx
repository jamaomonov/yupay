"use client";

import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, use } from "react";

import { OrderStatus } from "@/components/order/OrderStatus";

function OrderPageInner({ orderId }: { orderId: string }) {
  const rawEmail = useSearchParams().get("email");
  const props = rawEmail ? { orderId, email: rawEmail } : { orderId };
  return <OrderStatus {...props} />;
}

export default function OrderPage({ params }: { params: Promise<{ orderId: string }> }) {
  const { orderId } = use(params);
  const t = useTranslations("web.orders");
  return (
    <main className="mx-auto max-w-[560px] px-4 py-16">
      <Suspense fallback={<p className="text-tx-mute">{t("loading")}</p>}>
        <OrderPageInner orderId={orderId} />
      </Suspense>
    </main>
  );
}
