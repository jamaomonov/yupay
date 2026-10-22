import * as Linking from "expo-linking";
import { Bell, BellRing } from "lucide-react-native";
import { useEffect, useState } from "react";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { EmptyArt } from "@/components/EmptyArt";
import { TopBar } from "@/components/TopBar";
import { Button, Card, T } from "@/components/ui";
import { useI18n } from "@/lib/i18n";
import { pushState, registerPush, type PushState } from "@/lib/push";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

/** Whether pushes reach this phone, with a way to turn them on. */
function PushCard() {
  const { t } = useI18n();
  const { c } = useTheme();
  const [state, setState] = useState<PushState | null>(null);

  useEffect(() => {
    let live = true;
    void pushState()
      .catch((): PushState => "unsupported")
      .then((next) => {
        if (live) setState(next);
      });
    return () => {
      live = false;
    };
  }, []);

  if (state === null || state === "unsupported") return null;
  const on = state === "granted";
  return (
    <Card style={{ padding: 16, gap: 12 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
        <View
          style={{
            width: 40,
            height: 40,
            borderRadius: 12,
            backgroundColor: on ? c.okBg : c.muted,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <BellRing size={20} color={on ? c.ok : c.fg} />
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <T variant="h2">{on ? t("notifications.on") : t("notifications.off")}</T>
          <T variant="small" tone="mute">
            {state === "denied" ? t("notifications.denied") : t("notifications.what")}
          </T>
        </View>
      </View>
      {state === "ask" && (
        <Button
          label={t("notifications.enable")}
          onPress={() =>
            void registerPush({ ask: true, channelName: t("notifications.channel") }).then(setState)
          }
        />
      )}
      {state === "denied" && (
        <Button
          kind="ghost"
          label={t("notifications.settings")}
          onPress={() => void Linking.openSettings()}
        />
      )}
    </Card>
  );
}

/**
 * Notifications: whether pushes are on (ADR-0102). The pushes themselves live in the phone's
 * notification centre; this screen lists nothing yet.
 */
export default function NotificationsScreen() {
  const { t } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={{
        paddingTop: insets.top + 4,
        paddingHorizontal: space.gutter,
        paddingBottom: 32,
        gap: 16,
      }}
    >
      <TopBar title={t("notifications.title")} />
      <PushCard />
      <View style={{ alignItems: "center", gap: 16, marginTop: 32 }}>
        <EmptyArt Icon={Bell} />
        <T tone="mute" style={{ textAlign: "center" }}>
          {t("notifications.empty")}
        </T>
      </View>
    </ScrollView>
  );
}
