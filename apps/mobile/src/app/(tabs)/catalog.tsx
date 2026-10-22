import { SearchX } from "lucide-react-native";
import { useState } from "react";
import { View } from "react-native";

import { BrandGrid, BrandGridSkeleton } from "@/components/BrandGrid";
import { EmptyArt } from "@/components/EmptyArt";
import { Screen } from "@/components/Screen";
import { SearchField } from "@/components/SearchField";
import { Button, Notice } from "@/components/ui";
import { useBrands } from "@/lib/api";
import { matches, sellable } from "@/lib/catalog";
import { useI18n } from "@/lib/i18n";

export default function CatalogScreen() {
  const { t, locale } = useI18n();
  const brands = useBrands(locale);
  const [query, setQuery] = useState("");

  const found = brands.data ? sellable(brands.data.items).filter((b) => matches(b, query)) : [];

  return (
    <Screen title={t("catalog.title")} onRefresh={() => brands.refetch()}>
      <SearchField placeholder={t("home.search")} value={query} onChangeText={setQuery} />
      <View style={{ height: 16 }} />
      {brands.isPending ? (
        <BrandGridSkeleton count={12} />
      ) : brands.isError ? (
        <Notice
          text={t("common.loadError")}
          action={
            <Button kind="ghost" label={t("common.retry")} onPress={() => void brands.refetch()} />
          }
        />
      ) : found.length === 0 ? (
        <Notice text={t("home.empty")} icon={<EmptyArt Icon={SearchX} />} />
      ) : (
        <BrandGrid brands={found} />
      )}
    </Screen>
  );
}
