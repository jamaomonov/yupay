import Constants from "expo-constants";
import * as Linking from "expo-linking";
import { router } from "expo-router";
import {
  ChevronRight,
  Globe,
  LogOut,
  MessageCircle,
  Moon,
  UserRound,
  type LucideIcon,
} from "lucide-react-native";
import type { ReactNode } from "react";
import { Pressable, View } from "react-native";

import { Screen } from "@/components/Screen";
import { Card, Chip, T } from "@/components/ui";
import { LOCALE_NAMES, LOCALES, useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
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

/** A tappable row: icon, title, an optional second line, a chevron. */
function LinkRow({
  Icon,
  title,
  hint,
  onPress,
}: {
  Icon: LucideIcon;
  title: string;
  hint?: string;
  onPress: () => void;
}) {
  const { c } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        padding: 16,
        opacity: pressed ? 0.7 : 1,
      })}
    >
      <RowIcon Icon={Icon} />
      <View style={{ flex: 1 }}>
        <T variant="body" style={{ fontSize: 14.5 }} numberOfLines={1}>
          {title}
        </T>
        {hint !== undefined && (
          <T variant="small" tone="mute" numberOfLines={1}>
            {hint}
          </T>
        )}
      </View>
      <ChevronRight size={18} color={c.dim} />
    </Pressable>
  );
}

/** Who is signed in, with sign-out; or the way in. */
function Account() {
  const { t } = useI18n();
  const { c } = useTheme();
  const { user, signOut } = useSession();
  if (user === undefined) return null;
  if (user === null) {
    return (
      <Card style={{ marginTop: 6 }}>
        <LinkRow
          Icon={UserRound}
          title={t("profile.signIn")}
          hint={t("profile.signInHint")}
          onPress={() => router.push("/sign-in")}
        />
      </Card>
    );
  }
  return (
    <Card style={{ marginTop: 6 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 12, padding: 16 }}>
        <RowIcon Icon={UserRound} />
        <T variant="body" style={{ flex: 1, fontSize: 14.5 }} numberOfLines={1}>
          {user.display_name ?? user.email ?? ""}
        </T>
      </View>
      <View style={{ height: 1, backgroundColor: c.border }} />
      <LinkRow Icon={LogOut} title={t("profile.signOut")} onPress={() => void signOut()} />
    </Card>
  );
}

export default function ProfileScreen() {
  const { t, locale, setLocale } = useI18n();
  const { c, pref, setPref } = useTheme();
  const version = Constants.expoConfig?.version ?? "";

  return (
    <Screen title={t("profile.title")}>
      <Account />

      <Card style={{ marginTop: 10 }}>
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
        <LinkRow
          Icon={MessageCircle}
          title={t("profile.support")}
          hint={t("profile.supportHint")}
          onPress={() => void Linking.openURL(SUPPORT_URL)}
        />
      </Card>

      <T variant="small" tone="dim" style={{ textAlign: "center", marginTop: 24 }}>
        {t("profile.version", { version })}
      </T>
    </Screen>
  );
}
