import { router, useLocalSearchParams } from "expo-router";
import { Check } from "lucide-react-native";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { T } from "@/components/ui";
import { LOCALE_NAMES, LOCALES, useI18n } from "@/lib/i18n";
import { useTheme, type ThemePref } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

const THEMES: readonly ThemePref[] = ["system", "light", "dark"];

/** A sheet with the language or theme choices; picking one applies it and closes. */
export default function ChooseSheet() {
  const { kind } = useLocalSearchParams<{ kind: "language" | "theme" }>();
  const { t, locale, setLocale } = useI18n();
  const { c, pref, setPref } = useTheme();
  const insets = useSafeAreaInsets();

  const options =
    kind === "theme"
      ? THEMES.map((value) => ({
          key: value,
          label: t(`profile.theme_${value}`),
          active: value === pref,
          pick: () => setPref(value),
        }))
      : LOCALES.map((value) => ({
          key: value,
          label: LOCALE_NAMES[value],
          active: value === locale,
          pick: () => setLocale(value),
        }));

  return (
    <View
      style={{
        backgroundColor: c.card,
        paddingTop: 20,
        paddingBottom: Math.max(insets.bottom, 20),
        paddingHorizontal: space.gutter,
      }}
    >
      <T variant="title" style={{ marginBottom: 8 }}>
        {kind === "theme" ? t("profile.theme") : t("profile.language")}
      </T>
      {options.map((option, index) => (
        <Pressable
          key={option.key}
          onPress={() => {
            option.pick();
            router.back();
          }}
          style={({ pressed }) => ({
            flexDirection: "row",
            alignItems: "center",
            paddingVertical: 16,
            borderTopWidth: index === 0 ? 0 : 1,
            borderTopColor: c.border,
            opacity: pressed ? 0.7 : 1,
          })}
        >
          <T variant="h2" style={{ flex: 1 }}>
            {option.label}
          </T>
          {option.active && <Check size={20} color={c.accent} />}
        </Pressable>
      ))}
    </View>
  );
}
