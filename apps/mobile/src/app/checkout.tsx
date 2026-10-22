import { ApiError } from "@yupay/api-client";
import { useQueryClient } from "@tanstack/react-query";
import * as Linking from "expo-linking";
import { router, useLocalSearchParams } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useMemo, useRef, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { MethodPicker } from "@/components/checkout/MethodPicker";
import { TopBar } from "@/components/TopBar";
import { Button, Card, T } from "@/components/ui";
import { spendable, useWallet } from "@/lib/account";
import { orderFingerprint, PAY_METHODS, type OrderLine, type PayMethod } from "@/lib/checkout";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { createIntent, createOrder, newKey, useProviders } from "@/lib/orders";
import { balanceOption, type BalanceOption } from "@/lib/wallet";
import { useTheme } from "@/theme/ThemeProvider";
import { radius, space } from "@/theme/tokens";

type Method = PayMethod | "wallet";

/** Route params from the brand screen; `fields` is the order form as JSON. */
type Params = {
  brandSlug: string;
  brandName: string;
  skuId: string;
  label: string;
  price: string;
  fields: string;
  player?: string;
  /** A typed Stars count. */
  qty?: string;
  /** Steam: typed dollars. */
  amountUsd?: string;
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

/**
 * «From balance»: picked when the balance covers the order, otherwise shown with what is
 * missing and a way to top up.
 */
function BalanceTile({
  option,
  balance,
  active,
  onSelect,
}: {
  option: BalanceOption;
  balance: string | null;
  active: boolean;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  const { c } = useTheme();
  const ready = option.state === "ready";
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected: active, disabled: !ready }}
      disabled={!ready}
      onPress={onSelect}
      style={{
        padding: 14,
        gap: 4,
        borderRadius: radius.tile,
        borderWidth: active ? 2 : 1,
        borderColor: active ? c.selBorder : c.border,
        backgroundColor: active ? c.selBg : c.card,
        opacity: ready ? 1 : 0.85,
      }}
    >
      <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 12 }}>
        <T variant="h2">{t("checkout.fromBalance")}</T>
        {balance !== null && (
          <T tone="mute" style={{ fontVariant: ["tabular-nums"] }}>
            {formatSum(balance)} {t("common.sum")}
          </T>
        )}
      </View>
      {option.state === "short" && (
        <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 12 }}>
          <T variant="small" tone="mute">
            {t("checkout.balanceShort", { sum: formatSum(option.missing) })}
          </T>
          <Pressable hitSlop={8} onPress={() => router.push("/topup")}>
            <T variant="small" tone="accent">
              {t("wallet.topUp")}
            </T>
          </Pressable>
        </View>
      )}
    </Pressable>
  );
}

/** Summary, payment method, pay — as the signed-in account. */
export default function CheckoutScreen() {
  const params = useLocalSearchParams<Params>();
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const fields = useMemo(() => parseFields(params.fields), [params.fields]);

  const providers = useProviders();
  const methods = PAY_METHODS.filter((method) => {
    const status = providers.data?.providers.find((p) => p.slug === method)?.status;
    // Unknown while loading or missing from the list: shown, the API refuses it if it must.
    return status !== "maintenance";
  });
  const wallet = useWallet();
  const balance = spendable(wallet.data);
  const walletStatus = providers.data?.providers.find((p) => p.slug === "wallet")?.status;
  const option = balanceOption(balance, params.price);
  const walletOk = option.state === "ready" && walletStatus !== "maintenance";
  const [picked, setPicked] = useState<Method | null>(null);
  // The balance first when it covers the order: no bank page, settles at once.
  const method: Method | null =
    picked === "wallet" && walletOk
      ? "wallet"
      : picked !== null && picked !== "wallet" && methods.includes(picked)
        ? picked
        : walletOk
          ? "wallet"
          : (methods[0] ?? null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One key per order contents: paying again for the same thing resumes the same order.
  const keyRef = useRef<{ fingerprint: string; key: string } | null>(null);

  const line: OrderLine = {
    skuId: params.skuId,
    fields,
    ...(params.qty ? { qty: Number(params.qty) } : {}),
    ...(params.amountUsd ? { amountUsd: params.amountUsd } : {}),
  };

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
      if (method === "wallet")
        void queryClient.invalidateQueries({ queryKey: ["account", "wallet"] });
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
          <View style={{ gap: 8 }}>
            {walletStatus !== "maintenance" && option.state !== "unknown" && (
              <BalanceTile
                option={option}
                balance={balance}
                active={method === "wallet"}
                onSelect={() => setPicked("wallet")}
              />
            )}
            {methods.length > 0 ? (
              <MethodPicker
                methods={methods}
                selected={method === "wallet" ? null : method}
                onSelect={setPicked}
              />
            ) : (
              <T tone="mute">{t("checkout.noMethods")}</T>
            )}
          </View>
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
