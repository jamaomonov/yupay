import { ApiError } from "@yupay/api-client";
import { useQueryClient } from "@tanstack/react-query";
import * as Linking from "expo-linking";
import { router } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useRef, useState } from "react";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { MethodPicker } from "@/components/checkout/MethodPicker";
import { Field } from "@/components/Field";
import { TopBar } from "@/components/TopBar";
import { Button, Chip, T } from "@/components/ui";
import { createTopUp } from "@/lib/account";
import { PAY_METHODS, type PayMethod } from "@/lib/checkout";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { newKey, useProviders } from "@/lib/orders";
import { amountOf, checkAmount, QUICK_AMOUNTS, TOP_UP_MAX, TOP_UP_MIN } from "@/lib/wallet";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

/** Why the top-up did not start, in the buyer's words. */
function reason(err: unknown): string {
  if (err instanceof ApiError && err.status === 422) return "wallet.badAmount";
  if (err instanceof ApiError && err.status === 409) return "wallet.methodDown";
  return "wallet.failed";
}

/** An amount, an acquirer, pay; the balance moves when the acquirer settles. */
export default function TopUpScreen() {
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();

  const [amount, setAmount] = useState(0);
  const providers = useProviders();
  const methods = PAY_METHODS.filter(
    (method) => providers.data?.providers.find((p) => p.slug === method)?.status !== "maintenance",
  );
  const [picked, setPicked] = useState<PayMethod | null>(null);
  const method = picked !== null && methods.includes(picked) ? picked : (methods[0] ?? null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One key per amount and method: a retry replays the same top-up instead of a second one.
  const keyRef = useRef<{ signature: string; key: string } | null>(null);

  const check = checkAmount(amount);
  const hint =
    check === "low"
      ? t("wallet.min", { sum: formatSum(TOP_UP_MIN) })
      : check === "high"
        ? t("wallet.max", { sum: formatSum(TOP_UP_MAX) })
        : t("wallet.note");

  const submit = async () => {
    if (method === null || check !== "ok") return;
    const signature = `${amount.toString()}:${method}`;
    if (keyRef.current?.signature !== signature) keyRef.current = { signature, key: newKey() };
    setBusy(true);
    setError(null);
    try {
      const payment = await createTopUp({
        amount,
        provider: method,
        locale,
        idempotencyKey: keyRef.current.key,
      });
      if (payment.intent_url !== null) {
        if (payment.intent_url.startsWith("http"))
          await WebBrowser.openBrowserAsync(payment.intent_url);
        else await Linking.openURL(payment.intent_url);
      }
      await queryClient.invalidateQueries({ queryKey: ["account", "wallet"] });
      keyRef.current = null;
      if (router.canGoBack()) router.back();
      else router.replace("/wallet");
    } catch (err) {
      setError(t(reason(err)));
    } finally {
      setBusy(false);
    }
  };

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
        <TopBar title={t("wallet.topUpTitle")} fallback="/profile" />

        <View style={{ gap: 10 }}>
          <Field
            label={t("wallet.amount")}
            value={amount === 0 ? "" : formatSum(amount)}
            onChange={(text) => {
              setAmount(amountOf(text));
              setError(null);
            }}
            placeholder="100 000"
            keyboardType="number-pad"
            hint={hint}
            error={check === "low" || check === "high"}
          />
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
            {QUICK_AMOUNTS.map((sum) => (
              <Chip
                key={sum}
                label={formatSum(sum)}
                active={amount === sum}
                onPress={() => {
                  setAmount(sum);
                  setError(null);
                }}
              />
            ))}
          </View>
        </View>

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
          label={
            check === "ok"
              ? t("wallet.submit", { sum: formatSum(amount) })
              : t("wallet.enterAmount")
          }
          disabled={method === null || check !== "ok"}
          loading={busy}
          onPress={() => void submit()}
        />
      </View>
    </View>
  );
}
