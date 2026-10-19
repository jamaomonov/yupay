import * as Linking from "expo-linking";
import { router, useLocalSearchParams } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { CircleAlert, CircleCheck, Clock, Loader, Undo2, XCircle } from "lucide-react-native";
import { useEffect, useState, type ComponentType } from "react";
import { ActivityIndicator, AppState, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { TopBar } from "@/components/TopBar";
import { Button, Card, Notice, T } from "@/components/ui";
import { PAY_METHODS, stageOf, type OrderStage, type PayMethod } from "@/lib/checkout";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { createIntent, useOrder } from "@/lib/orders";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

const SUPPORT_URL = "https://t.me/yupay_support";

type Tone = "ok" | "warn" | "danger" | "mute";
interface IconProps {
  size: number;
  color: string;
}

const STAGE: Record<OrderStage, { icon: ComponentType<IconProps>; tone: Tone; hint: boolean }> = {
  awaiting: { icon: Clock, tone: "warn", hint: true },
  working: { icon: Loader, tone: "warn", hint: true },
  done: { icon: CircleCheck, tone: "ok", hint: true },
  failed: { icon: CircleAlert, tone: "danger", hint: true },
  closed: { icon: XCircle, tone: "mute", hint: true },
  refunded: { icon: Undo2, tone: "mute", hint: false },
};

function isPayMethod(value: string | null | undefined): value is PayMethod {
  return (PAY_METHODS as readonly (string | null | undefined)[]).includes(value);
}

/** One order: what was bought and where it stands, asked again until it settles. */
export default function OrderScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();

  const order = useOrder(id);
  const refetch = order.refetch;
  // Back from the bank's app: ask at once instead of waiting for the next tick.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active") void refetch();
    });
    return () => sub.remove();
  }, [refetch]);

  const [paying, setPaying] = useState(false);
  const payAgain = async () => {
    if (!order.data) return;
    const provider = isPayMethod(order.data.payment_provider)
      ? order.data.payment_provider
      : "payme";
    setPaying(true);
    try {
      const intent = await createIntent({ orderId: id, provider, locale });
      if (intent.intent_url?.startsWith("http"))
        await WebBrowser.openBrowserAsync(intent.intent_url);
      else if (intent.intent_url) await Linking.openURL(intent.intent_url);
      await refetch();
    } finally {
      setPaying(false);
    }
  };

  const body = () => {
    if (order.isPending) {
      return <ActivityIndicator color={c.mute} style={{ marginTop: 60 }} />;
    }
    if (order.isError || !order.data) {
      return (
        <Notice
          text={t("common.loadError")}
          action={<Button kind="ghost" label={t("common.retry")} onPress={() => void refetch()} />}
        />
      );
    }

    const stage = stageOf(order.data.status);
    const display = order.data.items[0]?.display;
    const brand = display?.brand_name ?? "";
    const label = display?.denomination ?? display?.product_name ?? "";
    const look = STAGE[stage];
    const Icon = look.icon;
    const color = look.tone === "mute" ? c.mute : c[look.tone];
    const background = look.tone === "mute" ? c.muted : c[`${look.tone}Bg`];

    return (
      <View style={{ gap: 14 }}>
        <Card style={{ padding: 20, alignItems: "center", gap: 10 }}>
          <View
            style={{
              width: 56,
              height: 56,
              borderRadius: 18,
              backgroundColor: background,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Icon size={26} color={color} />
          </View>
          <T variant="h2" style={{ fontSize: 17, textAlign: "center" }}>
            {t(`order.${stage}`)}
          </T>
          {look.hint && (
            <T variant="small" tone="mute" style={{ textAlign: "center" }}>
              {t(`order.${stage}Hint`)}
            </T>
          )}
        </Card>

        <Card style={{ padding: 16, gap: 10 }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 12 }}>
            <T tone="mute">{brand}</T>
            <T numberOfLines={1} style={{ flexShrink: 1 }}>
              {label}
            </T>
          </View>
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <T tone="mute">{t("checkout.total")}</T>
            <T style={{ fontVariant: ["tabular-nums"] }}>
              {formatSum(order.data.total_charged)} {t("common.sum")}
            </T>
          </View>
          <T variant="small" tone="dim">
            #{order.data.id}
          </T>
        </Card>

        {stage === "awaiting" && (
          <Button label={t("order.pay")} loading={paying} onPress={() => void payAgain()} />
        )}
        {stage === "failed" && (
          <Button label={t("order.support")} onPress={() => void Linking.openURL(SUPPORT_URL)} />
        )}
        {(stage === "done" || stage === "closed" || stage === "refunded") && (
          <Button kind="ghost" label={t("order.home")} onPress={() => router.replace("/")} />
        )}
      </View>
    );
  };

  return (
    <ScrollView
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={{
        paddingTop: insets.top + 4,
        paddingHorizontal: space.gutter,
        paddingBottom: 32,
        gap: 14,
      }}
    >
      <TopBar title={t("order.title")} fallback="/orders" />
      {body()}
    </ScrollView>
  );
}
