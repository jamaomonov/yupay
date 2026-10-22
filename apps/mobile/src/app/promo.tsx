import { useQueryClient } from "@tanstack/react-query";
import { Gift } from "lucide-react-native";
import { useState } from "react";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { EmptyArt } from "@/components/EmptyArt";
import { Field } from "@/components/Field";
import { TopBar } from "@/components/TopBar";
import { Button, Card, T } from "@/components/ui";
import { promoErrorKey, redeemPromo } from "@/lib/account";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

/** A promo code credits the balance (`POST /promo/redeem`). */
export default function PromoScreen() {
  const { t } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const apply = async () => {
    setBusy(true);
    setResult(null);
    try {
      const out = await redeemPromo(code);
      setResult({ ok: true, text: t("promo.success", { amount: formatSum(out.amount) }) });
      setCode("");
      await queryClient.invalidateQueries({ queryKey: ["account", "wallet"] });
    } catch (err) {
      setResult({ ok: false, text: t(promoErrorKey(err)) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={{
        paddingTop: insets.top + 4,
        paddingHorizontal: space.gutter,
        paddingBottom: 32,
        gap: 16,
      }}
      keyboardShouldPersistTaps="handled"
    >
      <TopBar title={t("promo.title")} fallback="/profile" />
      <View style={{ alignItems: "center" }}>
        <EmptyArt Icon={Gift} />
      </View>
      <Field
        label={t("promo.label")}
        value={code}
        onChange={(text) => {
          setCode(text);
          setResult(null);
        }}
        placeholder={t("promo.placeholder")}
      />
      {result !== null && (
        <Card style={{ padding: 16 }}>
          <T tone={result.ok ? "ok" : "danger"}>{result.text}</T>
        </Card>
      )}
      <Button
        label={t("promo.apply")}
        disabled={code.trim() === ""}
        loading={busy}
        onPress={() => void apply()}
      />
    </ScrollView>
  );
}
