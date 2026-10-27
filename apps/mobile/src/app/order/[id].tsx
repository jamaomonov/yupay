import * as Clipboard from "expo-clipboard";
import { Image } from "expo-image";
import * as Linking from "expo-linking";
import { router, useLocalSearchParams } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import {
  CircleAlert,
  CircleCheck,
  Clock,
  Copy,
  Loader,
  Undo2,
  XCircle,
  type LucideIcon,
} from "lucide-react-native";
import { useEffect, useState } from "react";
import { AppState, Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { StatusMark } from "@/components/order/StatusMark";
import { Steps } from "@/components/order/Steps";
import { TopBar } from "@/components/TopBar";
import { Button, Card, Notice, Skeleton, T } from "@/components/ui";
import { useBrands } from "@/lib/api";
import { itemLabel, orderImage } from "@/lib/catalog";
import {
  opensInAppBrowser,
  PAY_METHODS,
  stageOf,
  stageTone,
  type OrderStage,
  type PayMethod,
} from "@/lib/checkout";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { createIntent, useOrder } from "@/lib/orders";
import { useTheme } from "@/theme/ThemeProvider";
import { space, TOUCH } from "@/theme/tokens";

const SUPPORT_URL = "https://t.me/yupay_support";

const STAGE: Record<OrderStage, { icon: LucideIcon; hint: boolean }> = {
  awaiting: { icon: Clock, hint: true },
  working: { icon: Loader, hint: true },
  done: { icon: CircleCheck, hint: true },
  failed: { icon: CircleAlert, hint: true },
  closed: { icon: XCircle, hint: true },
  refunded: { icon: Undo2, hint: false },
};

/** Where the three-step line stands; `null` hides it for an order that did not go through. */
const STEP: Partial<Record<OrderStage, 0 | 1 | 2>> = { awaiting: 0, working: 1, done: 2 };

/** An order delivered this recently was just bought: the screen celebrates it. */
const FRESH_MS = 3 * 60_000;

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
  const brands = useBrands(locale);
  const refetch = order.refetch;
  const [copied, setCopied] = useState(false);
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
      if (intent.intent_url && opensInAppBrowser(intent.intent_url))
        await WebBrowser.openBrowserAsync(intent.intent_url);
      else if (intent.intent_url) await Linking.openURL(intent.intent_url);
      await refetch();
    } finally {
      setPaying(false);
    }
  };

  const body = () => {
    if (order.isPending) {
      return (
        <View style={{ gap: 12 }}>
          <Skeleton style={{ height: 180, borderRadius: 20 }} />
          <Skeleton style={{ height: 120, borderRadius: 20 }} />
        </View>
      );
    }
    if (order.isError || !order.data) {
      return (
        <Notice
          text={t("common.loadError")}
          action={<Button kind="ghost" label={t("common.retry")} onPress={() => void refetch()} />}
        />
      );
    }

    const data = order.data;
    const stage = stageOf(data.status);
    const item = data.items[0];
    const display = item?.display;
    const topUp = data.purpose === "wallet_topup";
    const label = topUp ? t("orders.topUp") : itemLabel(item);
    const image = topUp ? null : orderImage(display, brands.data?.items);
    const look = STAGE[stage];
    const tone = stageTone(stage);
    const color = tone === "mute" ? c.mute : c[tone];
    const background = tone === "mute" ? c.muted : c[`${tone}Bg`];
    // Read just after it was delivered — the screen polled it there, or the buyer came back
    // from the bank to it: the moment to celebrate. An old order opens quietly.
    const delivered = data.delivered_at ? Date.parse(data.delivered_at) : 0;
    const celebrate = stage === "done" && order.dataUpdatedAt - delivered < FRESH_MS;
    const step = STEP[stage];
    const date = new Intl.DateTimeFormat(locale === "uz" ? "uz-Latn-UZ" : locale, {
      day: "numeric",
      month: "long",
      hour: "2-digit",
      minute: "2-digit",
    });
    const buyAgain =
      display != null && !topUp && (stage === "done" || stage === "closed" || stage === "refunded");

    const copyId = async () => {
      await Clipboard.setStringAsync(data.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    };

    return (
      <View style={{ gap: 12 }}>
        <Card style={{ padding: 24, alignItems: "center", gap: 12 }}>
          <StatusMark
            Icon={look.icon}
            color={color}
            background={background}
            celebrate={celebrate}
          />
          <T variant="title" style={{ textAlign: "center" }}>
            {t(`order.${stage}`)}
          </T>
          {look.hint && (
            <T tone="mute" style={{ textAlign: "center" }}>
              {t(`order.${stage}Hint`)}
            </T>
          )}
          {step !== undefined && (
            <View style={{ alignSelf: "stretch", marginTop: 12 }}>
              <Steps
                labels={[t("order.stepPaid"), t("order.stepCredit"), t("order.stepDone")]}
                at={step}
              />
            </View>
          )}
        </Card>

        <Card style={{ padding: 16, gap: 16 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
            {image !== null && (
              <Image
                source={image}
                style={{ width: 48, height: 48, borderRadius: 12, backgroundColor: c.muted }}
                contentFit="cover"
              />
            )}
            <View style={{ flex: 1, gap: 2 }}>
              {display != null && !topUp && (
                <T variant="small" tone="mute" numberOfLines={1}>
                  {display.brand_name}
                </T>
              )}
              <T variant="amount" numberOfLines={1}>
                {label}
              </T>
            </View>
          </View>
          <View style={{ height: 1, backgroundColor: c.border }} />
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <T tone="mute">{t("checkout.total")}</T>
            <T variant="h2" style={{ fontVariant: ["tabular-nums"] }}>
              {formatSum(data.total_charged)} {t("common.sum")}
            </T>
          </View>
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <T tone="mute">{t("order.date")}</T>
            <T>{date.format(new Date(data.created_at))}</T>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t("order.copy")}
            onPress={() => void copyId()}
            style={{
              minHeight: TOUCH,
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
            }}
          >
            <T tone="mute">{t("order.number")}</T>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexShrink: 1 }}>
              <T numberOfLines={1} style={{ flexShrink: 1, fontVariant: ["tabular-nums"] }}>
                {copied ? t("order.copied") : `#${data.id.slice(0, 8)}`}
              </T>
              <Copy size={16} color={c.mute} />
            </View>
          </Pressable>
        </Card>

        {stage === "awaiting" && (
          <Button label={t("order.pay")} loading={paying} onPress={() => void payAgain()} />
        )}
        {stage === "failed" && (
          <Button label={t("order.support")} onPress={() => void Linking.openURL(SUPPORT_URL)} />
        )}
        {buyAgain && (
          <Button
            label={t("order.again")}
            onPress={() =>
              router.push({ pathname: "/brand/[slug]", params: { slug: display.brand_slug } })
            }
          />
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
        gap: 12,
      }}
    >
      <TopBar title={t("order.title")} fallback="/orders" />
      {body()}
    </ScrollView>
  );
}
