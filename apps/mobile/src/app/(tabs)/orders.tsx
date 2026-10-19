import { useQueries } from "@tanstack/react-query";
import { router, useFocusEffect } from "expo-router";
import { ChevronRight, ReceiptText } from "lucide-react-native";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";

import { Screen } from "@/components/Screen";
import { Card, T } from "@/components/ui";
import { stageOf } from "@/lib/checkout";
import { readGuestOrders, type GuestOrder } from "@/lib/guest-orders";
import { useI18n } from "@/lib/i18n";
import { fetchOrder } from "@/lib/orders";
import { useTheme } from "@/theme/ThemeProvider";

/** Orders placed on this phone. Orders from the website and Telegram need sign-in (next step). */
export default function OrdersScreen() {
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const [orders, setOrders] = useState<GuestOrder[] | null>(null);

  useFocusEffect(
    useCallback(() => {
      void readGuestOrders().then(setOrders);
    }, []),
  );

  const statuses = useQueries({
    queries: (orders ?? []).map((order) => ({
      queryKey: ["order", order.id],
      queryFn: () => fetchOrder(order.id, order.email),
      staleTime: 15_000,
    })),
  });

  const date = new Intl.DateTimeFormat(locale === "uz" ? "uz-Latn-UZ" : locale, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <Screen title={t("orders.title")}>
      {orders !== null && orders.length === 0 && (
        <Card style={{ padding: 24, alignItems: "center", gap: 10, marginTop: 8 }}>
          <View
            style={{
              width: 56,
              height: 56,
              borderRadius: 18,
              backgroundColor: c.muted,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <ReceiptText size={26} color={c.fg} strokeWidth={1.8} />
          </View>
          <T variant="h2" style={{ textAlign: "center" }}>
            {t("orders.empty")}
          </T>
        </Card>
      )}

      {orders !== null && orders.length > 0 && (
        <Card>
          {orders.map((order, index) => {
            const status = statuses[index]?.data?.status;
            return (
              <Pressable
                key={order.id}
                onPress={() => router.push({ pathname: "/order/[id]", params: { id: order.id } })}
                style={({ pressed }) => ({
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 12,
                  padding: 14,
                  borderTopWidth: index === 0 ? 0 : 1,
                  borderTopColor: c.border,
                  opacity: pressed ? 0.7 : 1,
                })}
              >
                <View style={{ flex: 1, gap: 3 }}>
                  <T numberOfLines={1}>
                    {order.brand} · {order.label}
                  </T>
                  <T variant="small" tone="mute">
                    {date.format(new Date(order.at))}
                    {status !== undefined ? ` · ${t(`order.${stageOf(status)}`)}` : ""}
                  </T>
                </View>
                <ChevronRight size={18} color={c.dim} />
              </Pressable>
            );
          })}
        </Card>
      )}

      <T variant="small" tone="mute" style={{ textAlign: "center", marginTop: 16 }}>
        {t("orders.more")}
      </T>
    </Screen>
  );
}
