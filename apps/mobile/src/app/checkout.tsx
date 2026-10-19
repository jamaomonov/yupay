import { ApiError } from "@yupay/api-client";
import * as Linking from "expo-linking";
import { router, useLocalSearchParams } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useMemo, useRef, useState } from "react";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { MethodPicker } from "@/components/checkout/MethodPicker";
import { TopBar } from "@/components/TopBar";
import { Button, Card, T } from "@/components/ui";
import { orderFingerprint, PAY_METHODS, type PayMethod } from "@/lib/checkout";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { createIntent, createOrder, newKey, useProviders } from "@/lib/orders";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

/** Route params from the brand screen; `fields` is the order form as JSON. */
type Params = {
  brandSlug: string;
  brandName: string;
  skuId: string;
  label: string;
  price: string;
  fields: string;
  player?: string;
};

function parseFields(raw: string | undefined): Record<string, string> {
  try {
    const value: unknown = JSON.parse(raw ?? "{}");
    return typeof value === "object" && value !== null ? (value as Record<string, string>) : {};
  } catch {
    return {};
  }
}

/**
 * Opens the acquirer's page and waits for the buyer to come back. A web page opens in the
 * in-app browser and resolves when it closes; an app link (Uzum) leaves the app.
 */
async function openPayment(url: string): Promise<void> {
  if (url.startsWith("http")) await WebBrowser.openBrowserAsync(url);
  else await Linking.openURL(url);
}

/** Summary, payment method, pay — as the signed-in account. */
export default function CheckoutScreen() {
  const params = useLocalSearchParams<Params>();
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const fields = useMemo(() => parseFields(params.fields), [params.fields]);

  const providers = useProviders();
  const methods = PAY_METHODS.filter((method) => {
    const status = providers.data?.providers.find((p) => p.slug === method)?.status;
    // Unknown while loading or missing from the list: shown, the API refuses it if it must.
    return status !== "maintenance";
  });
  const [picked, setPicked] = useState<PayMethod | null>(null);
  const method = picked !== null && methods.includes(picked) ? picked : (methods[0] ?? null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One key per order contents: paying again for the same thing resumes the same order.
  const keyRef = useRef<{ fingerprint: string; key: string } | null>(null);

  const line = { skuId: params.skuId, fields };

  const pay = async () => {
    if (method === null) return;
    const fingerprint = orderFingerprint(line);
    if (keyRef.current?.fingerprint !== fingerprint)
      keyRef.current = { fingerprint, key: newKey() };
    setBusy(true);
    setError(null);
    try {
      const order = await createOrder(line, keyRef.current.key);
      const intent = await createIntent({ orderId: order.id, provider: method, locale });
      if (intent.intent_url !== null) await openPayment(intent.intent_url);
      router.replace({ pathname: "/order/[id]", params: { id: order.id } });
    } catch (err) {
      // 409 on the intent: the order behind the key expired. A fresh key opens a new one.
      if (err instanceof ApiError && err.status === 409) {
        keyRef.current = null;
        setError(t("checkout.stale"));
      } else {
        setError(t("checkout.error"));
      }
    } finally {
      setBusy(false);
    }
  };

  const rows: [string, string][] = [
    [params.brandName, params.label],
    ...(params.player ? [[t("checkout.player"), params.player] as [string, string]] : []),
  ];

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView
        contentContainerStyle={{
          paddingTop: insets.top + 4,
          paddingHorizontal: space.gutter,
          paddingBottom: 150,
          gap: 18,
        }}
        keyboardShouldPersistTaps="handled"
      >
        <TopBar title={t("checkout.title")} />

        <Card style={{ padding: 16, gap: 10 }}>
          {rows.map(([name, value]) => (
            <View
              key={name}
              style={{ flexDirection: "row", justifyContent: "space-between", gap: 12 }}
            >
              <T tone="mute">{name}</T>
              <T numberOfLines={1} style={{ flexShrink: 1 }}>
                {value}
              </T>
            </View>
          ))}
          <View style={{ height: 1, backgroundColor: c.border }} />
          <View
            style={{
              flexDirection: "row",
              justifyContent: "space-between",
              alignItems: "baseline",
            }}
          >
            <T tone="mute">{t("checkout.total")}</T>
            <T variant="h2" style={{ fontSize: 17, fontVariant: ["tabular-nums"] }}>
              {formatSum(params.price)} {t("common.sum")}
            </T>
          </View>
        </Card>

        <View>
          <T variant="label" tone="mute" style={{ marginBottom: 8 }}>
            {t("checkout.method")}
          </T>
          {methods.length > 0 ? (
            <MethodPicker methods={methods} selected={method} onSelect={setPicked} />
          ) : (
            <T tone="mute">{t("checkout.noMethods")}</T>
          )}
        </View>

        {error !== null && <T tone="danger">{error}</T>}
      </ScrollView>

      <View
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          paddingHorizontal: space.gutter,
          paddingTop: 12,
          paddingBottom: Math.max(insets.bottom, 16),
          backgroundColor: c.bg,
          borderTopWidth: 1,
          borderTopColor: c.border,
        }}
      >
        <Button
          label={t("checkout.pay", { sum: formatSum(params.price) })}
          disabled={method === null}
          loading={busy}
          onPress={() => void pay()}
        />
      </View>
    </View>
  );
}
