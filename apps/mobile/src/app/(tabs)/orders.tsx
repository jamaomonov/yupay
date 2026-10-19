import { useQueries } from "@tanstack/react-query";
import type { OrderOut } from "@yupay/api-client/types";
import { router, useFocusEffect } from "expo-router";
import { ChevronRight, ReceiptText } from "lucide-react-native";
import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";

import { Screen } from "@/components/Screen";
import { Button, Card, T } from "@/components/ui";
import { stageOf } from "@/lib/checkout";
import { readGuestOrders, type GuestOrder } from "@/lib/guest-orders";
import { useI18n } from "@/lib/i18n";
import { fetchOrder, useAccountOrders } from "@/lib/orders";
import { useSession } from "@/lib/session";
import { useTheme } from "@/theme/ThemeProvider";

interface Row {
  id: string;
  title: string;
  at: string;
  status: string | undefined;
}

function fromOrder(order: OrderOut): Row {
  const display = order.items[0]?.display;
  const label = display?.denomination ?? display?.product_name ?? "";
  return {
    id: order.id,
    title: display ? `${display.brand_name} · ${label}` : `#${order.id.slice(0, 8)}`,
    at: order.created_at,
    status: order.status,
  };
}

function OrderList({ rows }: { rows: Row[] }) {
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const date = new Intl.DateTimeFormat(locale === "uz" ? "uz-Latn-UZ" : locale, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <Card>
      {rows.map((row, index) => (
        <Pressable
          key={row.id}
          onPress={() => router.push({ pathname: "/order/[id]", params: { id: row.id } })}
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
            <T numberOfLines={1}>{row.title}</T>
            <T variant="small" tone="mute">
              {date.format(new Date(row.at))}
              {row.status !== undefined ? ` · ${t(`order.${stageOf(row.status)}`)}` : ""}
            </T>
          </View>
          <ChevronRight size={18} color={c.dim} />
        </Pressable>
      ))}
    </Card>
  );
}

function Empty() {
  const { t } = useI18n();
  const { c } = useTheme();
  return (
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
  );
}

/** The account's orders when signed in; the ones placed on this phone without an account. */
export default function OrdersScreen() {
  const { t } = useI18n();
  const { c } = useTheme();
  const { user } = useSession();
  const [guest, setGuest] = useState<GuestOrder[] | null>(null);

  useFocusEffect(
    useCallback(() => {
      void readGuestOrders().then(setGuest);
    }, []),
  );

  const account = useAccountOrders(user != null);
  const guestStatuses = useQueries({
    queries: (guest ?? []).map((order) => ({
      queryKey: ["order", order.id],
      queryFn: () => fetchOrder(order.id, order.email),
      staleTime: 15_000,
    })),
  });

  const accountRows = (account.data?.items ?? []).map(fromOrder);
  const accountIds = new Set(accountRows.map((row) => row.id));
  const guestRows: Row[] = (guest ?? [])
    .map((order, index) => ({
      id: order.id,
      title: `${order.brand} · ${order.label}`,
      at: order.at,
      status: guestStatuses[index]?.data?.status,
    }))
    .filter((row) => !accountIds.has(row.id));

  const loading = user === undefined || guest === null || (user != null && account.isPending);

  return (
    <Screen title={t("orders.title")}>
      {loading ? (
        <ActivityIndicator color={c.mute} style={{ marginTop: 40 }} />
      ) : (
        <View style={{ gap: 10 }}>
          {accountRows.length === 0 && guestRows.length === 0 && <Empty />}
          {accountRows.length > 0 && <OrderList rows={accountRows} />}
          {guestRows.length > 0 && (
            <>
              {user != null && (
                <T variant="label" tone="mute" style={{ marginTop: 8 }}>
                  {t("orders.guestTitle")}
                </T>
              )}
              <OrderList rows={guestRows} />
            </>
          )}
        </View>
      )}

      {user === null && (
        <View style={{ marginTop: 16, gap: 10 }}>
          <T variant="small" tone="mute" style={{ textAlign: "center" }}>
            {t("orders.more")}
          </T>
          <Button
            kind="ghost"
            label={t("orders.signInButton")}
            onPress={() => router.push("/sign-in")}
          />
        </View>
      )}
    </Screen>
  );
}
