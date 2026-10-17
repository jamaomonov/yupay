import { router } from "expo-router";
import { ActivityIndicator, Pressable, View } from "react-native";

import { BrandGrid } from "@/components/BrandGrid";
import { Logo } from "@/components/Logo";
import { Screen } from "@/components/Screen";
import { SearchField } from "@/components/SearchField";
import { Button, Notice, T } from "@/components/ui";
import { useBrands } from "@/lib/api";
import { sellable } from "@/lib/catalog";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/theme/ThemeProvider";

const POPULAR = 9;

export default function HomeScreen() {
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const brands = useBrands(locale);

  const openCatalog = () => router.navigate("/catalog");

  return (
    <Screen
      header={
        <View style={{ height: 48, justifyContent: "center", marginBottom: 8 }}>
          <Logo />
        </View>
      }
    >
      <SearchField placeholder={t("home.search")} onPress={openCatalog} />

      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginTop: 24,
          marginBottom: 12,
        }}
      >
        <T variant="h2">{t("home.popular")}</T>
        <Pressable onPress={openCatalog} hitSlop={10}>
          <T variant="label" tone="accent">
            {t("home.all")}
          </T>
        </Pressable>
      </View>

      {brands.isPending ? (
        <ActivityIndicator color={c.mute} style={{ marginTop: 40 }} />
      ) : brands.isError ? (
        <Notice
          text={t("common.loadError")}
          action={
            <Button kind="ghost" label={t("common.retry")} onPress={() => void brands.refetch()} />
          }
        />
      ) : (
        <BrandGrid brands={sellable(brands.data.items).slice(0, POPULAR)} />
      )}
    </Screen>
  );
}
