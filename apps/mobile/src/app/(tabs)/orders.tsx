import type { BrandOut, OrderOut } from "@yupay/api-client/types";
import { Image } from "expo-image";
import { router } from "expo-router";
import { ChevronRight, ReceiptText, Wallet } from "lucide-react-native";
import { Pressable, View } from "react-native";

import { Screen } from "@/components/Screen";
import { Badge, Button, Card, Notice, Skeleton, T } from "@/components/ui";
import { useBrands } from "@/lib/api";
import { itemLabel, orderImage } from "@/lib/catalog";
import { stageOf, stageTone } from "@/lib/checkout";
import { useI18n } from "@/lib/i18n";
import { useAccountOrders } from "@/lib/orders";
import { useTheme } from "@/theme/ThemeProvider";

interface Row {
  id: string;
  /** `null` for a balance top-up: the screen names it. */
  title: string | null;
  topUp: boolean;
  at: string;
  status: string;
  image: string | null;
}

function fromOrder(order: OrderOut, brands: readonly BrandOut[] | undefined): Row {
  const display = order.items[0]?.display;
  const topUp = order.purpose === "wallet_topup";
  return {
    id: order.id,
    title: topUp
      ? null
      : display
        ? `${display.brand_name} · ${itemLabel(order.items[0])}`
        : `#${order.id.slice(0, 8)}`,
    topUp,
    at: order.created_at,
    status: order.status,
    image: topUp ? null : orderImage(display, brands),
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
            padding: 16,
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
            ) : row.topUp ? (
              <Wallet size={20} color={c.mute} strokeWidth={1.8} />
            ) : (
              <ReceiptText size={20} color={c.mute} strokeWidth={1.8} />
            )}
          </View>
          <View style={{ flex: 1, gap: 8 }}>
            <T variant="h2" numberOfLines={1}>
              {row.title ?? t("orders.topUp")}
            </T>
            <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
              <Badge
                label={t(`order.${stageOf(row.status)}`)}
                tone={stageTone(stageOf(row.status))}
              />
              <T variant="small" tone="mute">
                {date.format(new Date(row.at))}
              </T>
            </View>
          </View>
          <ChevronRight size={18} color={c.dim} />
        </Pressable>
      ))}
    </Card>
  );
}

function Loading() {
  return (
    <Card>
      {[0, 1, 2, 3].map((n) => (
        <View key={n} style={{ flexDirection: "row", gap: 12, padding: 16, alignItems: "center" }}>
          <Skeleton style={{ width: 44, height: 44, borderRadius: 12 }} />
          <View style={{ flex: 1, gap: 8 }}>
            <Skeleton style={{ width: "70%", height: 14 }} />
            <Skeleton style={{ width: "45%", height: 12 }} />
          </View>
        </View>
      ))}
    </Card>
  );
}

function Empty() {
  const { t } = useI18n();
  const { c } = useTheme();
  return (
    <Card style={{ padding: 24, alignItems: "center", gap: 12, marginTop: 8 }}>
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
      <View style={{ alignSelf: "stretch", marginTop: 4 }}>
        <Button label={t("common.toCatalog")} onPress={() => router.navigate("/catalog")} />
      </View>
    </Card>
  );
}

/** The account's orders: from the website, the mini app and this app alike. */
export default function OrdersScreen() {
  const { t, locale } = useI18n();
  const orders = useAccountOrders();
  const brands = useBrands(locale);
  const rows = (orders.data?.items ?? []).map((order) => fromOrder(order, brands.data?.items));

  return (
    <Screen title={t("orders.title")}>
      {orders.isPending ? (
        <Loading />
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
