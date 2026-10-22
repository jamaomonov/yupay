import { Bell } from "lucide-react-native";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { TopBar } from "@/components/TopBar";
import { T } from "@/components/ui";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

/**
 * Notifications. Empty until the app registers for push (ADR-0102): order outcomes and
 * top-ups will be listed here.
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
      <View style={{ alignItems: "center", gap: 12, marginTop: 60 }}>
        <Bell size={32} color={c.dim} />
        <T tone="mute" style={{ textAlign: "center" }}>
          {t("notifications.empty")}
        </T>
      </View>
    </ScrollView>
  );
}
