import { useState } from "react";
import { ActivityIndicator, View } from "react-native";

import { BrandGrid } from "@/components/BrandGrid";
import { Screen } from "@/components/Screen";
import { SearchField } from "@/components/SearchField";
import { Button, Notice } from "@/components/ui";
import { useBrands } from "@/lib/api";
import { matches, sellable } from "@/lib/catalog";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/theme/ThemeProvider";

export default function CatalogScreen() {
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const brands = useBrands(locale);
  const [query, setQuery] = useState("");

  const found = brands.data ? sellable(brands.data.items).filter((b) => matches(b, query)) : [];

  return (
    <Screen title={t("catalog.title")}>
      <SearchField placeholder={t("home.search")} value={query} onChangeText={setQuery} />
      <View style={{ height: 18 }} />
      {brands.isPending ? (
        <ActivityIndicator color={c.mute} style={{ marginTop: 40 }} />
      ) : brands.isError ? (
        <Notice
          text={t("common.loadError")}
          action={
            <Button kind="ghost" label={t("common.retry")} onPress={() => void brands.refetch()} />
          }
        />
      ) : found.length === 0 ? (
        <Notice text={t("home.empty")} />
      ) : (
        <BrandGrid brands={found} />
      )}
    </Screen>
  );
}
