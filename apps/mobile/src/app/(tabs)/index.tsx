import { router } from "expo-router";
import { Pressable, View } from "react-native";

import { BrandGrid, BrandGridSkeleton } from "@/components/BrandGrid";
import { HomeHeader } from "@/components/HomeHeader";
import { Screen } from "@/components/Screen";
import { Button, Notice, T } from "@/components/ui";
import { useBrands } from "@/lib/api";
import { sellable } from "@/lib/catalog";
import { useI18n } from "@/lib/i18n";
import { TOUCH } from "@/theme/tokens";

const POPULAR = 9;

export default function HomeScreen() {
  const { t, locale } = useI18n();
  const brands = useBrands(locale);

  const openCatalog = () => router.navigate("/catalog");

  return (
    <Screen header={<HomeHeader />}>
      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: 8,
          marginBottom: 8,
        }}
      >
        <T variant="title">{t("home.popular")}</T>
        <Pressable
          accessibilityRole="link"
          onPress={openCatalog}
          style={{ minHeight: TOUCH, paddingLeft: 16, justifyContent: "center" }}
        >
          <T variant="h2" tone="accent">
            {t("home.all")}
          </T>
        </Pressable>
      </View>

      {brands.isPending ? (
        <BrandGridSkeleton />
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
