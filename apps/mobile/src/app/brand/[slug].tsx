import type { SkuOut } from "@yupay/api-client/types";
import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Alert, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { BrandHeader } from "@/components/brand/BrandHeader";
import { PlayerFields } from "@/components/brand/PlayerFields";
import { SkuGrid } from "@/components/brand/SkuGrid";
import { Button, Chip, Notice, T } from "@/components/ui";
import { useBrand, usePlayerCheck, useProduct, type PlayerCheckResult } from "@/lib/api";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

export default function BrandScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();

  const brand = useBrand(slug, locale);
  const [productSlug, setProductSlug] = useState<string | null>(null);
  const activeSlug = productSlug ?? brand.data?.products[0]?.slug;
  const product = useProduct(activeSlug, locale);

  const [values, setValues] = useState<Record<string, string>>({});
  const [sku, setSku] = useState<SkuOut | null>(null);
  const [checkResult, setCheckResult] = useState<PlayerCheckResult | null>(null);
  const check = usePlayerCheck(slug);

  if (brand.isPending) {
    return <ActivityIndicator color={c.mute} style={{ marginTop: insets.top + 80 }} />;
  }
  if (brand.isError) {
    return (
      <View style={{ paddingTop: insets.top + 40, paddingHorizontal: space.gutter }}>
        <Notice
          text={t("common.loadError")}
          action={
            <Button kind="ghost" label={t("common.retry")} onPress={() => void brand.refetch()} />
          }
        />
      </View>
    );
  }

  const fields = product.data?.required_fields ?? [];
  const checkField = fields.find((field) => field.check != null);
  const skus = (product.data?.skus ?? []).filter((item) => !item.variable_amount);
  const missingField = fields.find(
    (field) => field.required !== false && !(values[field.key] ?? "").trim(),
  );

  const runCheck = () => {
    if (checkField === undefined) return;
    const serverKey = checkField.check?.server_field;
    const serverId = serverKey != null ? values[serverKey]?.trim() : undefined;
    check.mutate(
      { playerId: (values[checkField.key] ?? "").trim(), ...(serverId ? { serverId } : {}) },
      {
        onSuccess: setCheckResult,
        onError: () => setCheckResult({ status: "error" }),
      },
    );
  };

  const onChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setCheckResult(null);
  };

  const pickProduct = (next: string) => {
    setProductSlug(next);
    setSku(null);
  };

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: space.gutter, paddingBottom: 150 }}
        keyboardShouldPersistTaps="handled"
      >
        <BrandHeader brand={brand.data} />

        {brand.data.maintenance ? (
          <Notice text={t("brand.maintenance")} />
        ) : (
          <>
            {brand.data.products.length > 1 && (
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                style={{ marginTop: 16 }}
              >
                <View style={{ flexDirection: "row", gap: 6 }}>
                  {brand.data.products.map((item) => (
                    <Chip
                      key={item.slug}
                      label={item.name}
                      active={item.slug === activeSlug}
                      onPress={() => pickProduct(item.slug)}
                    />
                  ))}
                </View>
              </ScrollView>
            )}

            <View style={{ marginTop: 18 }}>
              <PlayerFields
                fields={fields}
                values={values}
                onChange={onChange}
                {...(checkField ? { onCheck: runCheck } : {})}
                checking={check.isPending}
                result={checkResult}
              />
            </View>

            <T variant="label" tone="mute" style={{ marginTop: 20, marginBottom: 8 }}>
              {t("brand.amount")}
            </T>
            {product.isPending ? (
              <ActivityIndicator color={c.mute} style={{ marginTop: 24 }} />
            ) : (
              <SkuGrid skus={skus} selectedId={sku?.id ?? null} onSelect={setSku} />
            )}
          </>
        )}
      </ScrollView>

      <View
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          paddingHorizontal: space.gutter,
          paddingTop: 12,
          paddingBottom: Math.max(insets.bottom, 16),
          backgroundColor: c.bg,
          borderTopWidth: 1,
          borderTopColor: c.border,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "baseline",
            marginBottom: 10,
          }}
        >
          <T variant="small" tone="mute">
            {sku ? (sku.denomination ?? sku.sku_code) : t("brand.pickAmount")}
          </T>
          {sku?.display_price && (
            <T variant="h2" style={{ fontSize: 17, fontVariant: ["tabular-nums"] }}>
              {formatSum(sku.display_price.amount)} {t("common.sum")}
            </T>
          )}
        </View>
        <Button
          label={missingField && sku ? t("brand.enterId") : t("brand.toPay")}
          disabled={!sku || missingField !== undefined}
          onPress={() => Alert.alert(t("brand.paySoon"))}
        />
      </View>
    </View>
  );
}
