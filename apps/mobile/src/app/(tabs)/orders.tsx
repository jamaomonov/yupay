import { ReceiptText } from "lucide-react-native";
import { Alert, View } from "react-native";

import { Screen } from "@/components/Screen";
import { Button, Card, T } from "@/components/ui";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/theme/ThemeProvider";

/** Orders need an account; sign-in is the next step of the build (ADR-0100). */
export default function OrdersScreen() {
  const { t } = useI18n();
  const { c } = useTheme();
  return (
    <Screen title={t("orders.title")}>
      <Card style={{ padding: 24, alignItems: "center", gap: 10, marginTop: 8 }}>
        <View
          style={{
            width: 56,
            height: 56,
            borderRadius: 18,
            backgroundColor: c.muted,
            alignItems: "center",
            justifyContent: "center",
            marginBottom: 4,
          }}
        >
          <ReceiptText size={26} color={c.fg} strokeWidth={1.8} />
        </View>
        <T variant="h2" style={{ textAlign: "center" }}>
          {t("orders.signIn")}
        </T>
        <T variant="small" tone="mute" style={{ textAlign: "center" }}>
          {t("orders.signInHint")}
        </T>
        <View style={{ alignSelf: "stretch", marginTop: 10 }}>
          <Button label={t("orders.signInButton")} onPress={() => Alert.alert(t("common.soon"))} />
        </View>
      </Card>
    </Screen>
  );
}
