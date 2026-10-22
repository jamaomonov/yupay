import type { BrandOut, OrderOut } from "@yupay/api-client/types";
import { Image } from "expo-image";
import { router } from "expo-router";
import { ChevronRight, ReceiptText } from "lucide-react-native";
import { ActivityIndicator, Pressable, View } from "react-native";

import { Screen } from "@/components/Screen";
import { Button, Card, Notice, T } from "@/components/ui";
import { useBrands } from "@/lib/api";
import { itemLabel, orderImage } from "@/lib/catalog";
import { stageOf } from "@/lib/checkout";
import { useI18n } from "@/lib/i18n";
import { useAccountOrders } from "@/lib/orders";
import { useTheme } from "@/theme/ThemeProvider";

interface Row {
  id: string;
  title: string;
  at: string;
  status: string | undefined;
  image: string | null;
}

function fromOrder(order: OrderOut, brands: readonly BrandOut[] | undefined): Row {
  const display = order.items[0]?.display;
  const label = itemLabel(order.items[0]);
  return {
    id: order.id,
    title: display ? `${display.brand_name} · ${label}` : `#${order.id.slice(0, 8)}`,
    at: order.created_at,
    status: order.status,
    image: orderImage(display, brands),
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
          <View
            style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              overflow: "hidden",
              backgroundColor: c.muted,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {row.image !== null ? (
              <Image
                source={row.image}
                style={{ width: "100%", height: "100%" }}
                contentFit="cover"
                transition={150}
              />
            ) : (
              <ReceiptText size={20} color={c.dim} strokeWidth={1.8} />
            )}
          </View>
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

/** The account's orders: from the website, the mini app and this app alike. */
export default function OrdersScreen() {
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const orders = useAccountOrders();
  const brands = useBrands(locale);
  const rows = (orders.data?.items ?? []).map((order) => fromOrder(order, brands.data?.items));

  return (
    <Screen title={t("orders.title")}>
      {orders.isPending ? (
        <ActivityIndicator color={c.mute} style={{ marginTop: 40 }} />
      ) : orders.isError ? (
        <Notice
          text={t("common.loadError")}
          action={
            <Button kind="ghost" label={t("common.retry")} onPress={() => void orders.refetch()} />
          }
        />
      ) : rows.length === 0 ? (
        <Empty />
      ) : (
        <OrderList rows={rows} />
      )}
    </Screen>
  );
}
