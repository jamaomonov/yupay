import Constants from "expo-constants";
import * as Linking from "expo-linking";
import { ChevronRight, Globe, MessageCircle, Moon, type LucideIcon } from "lucide-react-native";
import type { ReactNode } from "react";
import { Pressable, View } from "react-native";

import { Screen } from "@/components/Screen";
import { Card, Chip, T } from "@/components/ui";
import { LOCALE_NAMES, LOCALES, useI18n } from "@/lib/i18n";
import { useTheme, type ThemePref } from "@/theme/ThemeProvider";

const SUPPORT_URL = "https://t.me/yupay_support";
const THEMES: readonly ThemePref[] = ["system", "light", "dark"];
const THEME_LABELS: Record<ThemePref, string> = {
  system: "profile.themeSystem",
  light: "profile.themeLight",
  dark: "profile.themeDark",
};

function RowIcon({ Icon }: { Icon: LucideIcon }) {
  const { c } = useTheme();
  return (
    <View
      style={{
        width: 36,
        height: 36,
        borderRadius: 11,
        backgroundColor: c.muted,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Icon size={18} color={c.fg} strokeWidth={1.8} />
    </View>
  );
}

/** A settings block: icon and title, then its choices underneath. */
function Setting({
  Icon,
  title,
  children,
}: {
  Icon: LucideIcon;
  title: string;
  children: ReactNode;
}) {
  return (
    <View style={{ padding: 16, gap: 12 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
        <RowIcon Icon={Icon} />
        <T variant="body" style={{ fontSize: 14.5 }}>
          {title}
        </T>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>{children}</View>
    </View>
  );
}

export default function ProfileScreen() {
  const { t, locale, setLocale } = useI18n();
  const { c, pref, setPref } = useTheme();
  const version = Constants.expoConfig?.version ?? "";

  return (
    <Screen title={t("profile.title")}>
      <Card style={{ marginTop: 6 }}>
        <Setting Icon={Globe} title={t("profile.language")}>
          {LOCALES.map((code) => (
            <Chip
              key={code}
              label={LOCALE_NAMES[code]}
              active={code === locale}
              onPress={() => setLocale(code)}
            />
          ))}
        </Setting>
        <View style={{ height: 1, backgroundColor: c.border }} />
        <Setting Icon={Moon} title={t("profile.theme")}>
          {THEMES.map((option) => (
            <Chip
              key={option}
              label={t(THEME_LABELS[option])}
              active={option === pref}
              onPress={() => setPref(option)}
            />
          ))}
        </Setting>
      </Card>

      <Card style={{ marginTop: 10 }}>
        <Pressable
          onPress={() => void Linking.openURL(SUPPORT_URL)}
          style={({ pressed }) => ({
            flexDirection: "row",
            alignItems: "center",
            gap: 12,
            padding: 16,
            opacity: pressed ? 0.7 : 1,
          })}
        >
          <RowIcon Icon={MessageCircle} />
          <View style={{ flex: 1 }}>
            <T variant="body" style={{ fontSize: 14.5 }}>
              {t("profile.support")}
            </T>
            <T variant="small" tone="mute">
              {t("profile.supportHint")}
            </T>
          </View>
          <ChevronRight size={18} color={c.dim} />
        </Pressable>
      </Card>

      <T variant="small" tone="dim" style={{ textAlign: "center", marginTop: 24 }}>
        {t("profile.version", { version })}
      </T>
    </Screen>
  );
}
