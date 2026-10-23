import type { SkuOut } from "@yupay/api-client/types";
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { AmountField } from "@/components/brand/AmountField";
import { BrandHeader } from "@/components/brand/BrandHeader";
import { PlayerFields } from "@/components/brand/PlayerFields";
import { SkuGrid } from "@/components/brand/SkuGrid";
import { Button, Chip, Notice, T } from "@/components/ui";
import { amountRule, checkCount, countLabel, lineOf, priceOf, skuKind } from "@/lib/amount";
import { useBrand, usePlayerCheck, useProduct, type PlayerCheckResult } from "@/lib/api";
import { checkBlocks, isFixedSku } from "@/lib/checkout";
import { formatSum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { loadPlayer, savePlayer } from "@/lib/player-memory";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

/** What the pay button buys: a tile, or a typed amount priced from its rate. */
interface Choice {
  sku: SkuOut;
  label: string;
  price: string;
  qty?: number;
  amountUsd?: string;
}

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
  // A typed amount (Steam dollars, Stars); 0 while nothing is typed. A tile and a typed
  // amount exclude each other.
  const [count, setCount] = useState(0);
  const [checkResult, setCheckResult] = useState<PlayerCheckResult | null>(null);
  const check = usePlayerCheck(slug);

  // The ID this game was last bought for comes back filled in; anything typed meanwhile wins.
  useEffect(() => {
    let live = true;
    void loadPlayer(slug).then((saved) => {
      if (live && Object.keys(saved).length > 0) setValues((prev) => ({ ...saved, ...prev }));
    });
    return () => {
      live = false;
    };
  }, [slug]);

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
  const skus = (product.data?.skus ?? []).filter(isFixedSku);
  const customSku = (product.data?.skus ?? []).find(
    (item) => skuKind(item) !== "fixed" && item.in_stock !== false,
  );
  const rule = customSku !== undefined ? amountRule(customSku) : null;
  const typed = sku === null && rule !== null && customSku !== undefined && count > 0;
  const choice: Choice | null =
    sku?.display_price != null
      ? { sku, label: sku.denomination ?? sku.sku_code, price: sku.display_price.amount }
      : typed && checkCount(count, rule) === "ok"
        ? {
            sku: customSku,
            label: countLabel(count, rule),
            price: String(priceOf(count, rule)),
            ...lineOf(count, rule),
          }
        : null;
  const pickHint =
    rule !== null && skus.length === 0
      ? rule.kind === "usd"
        ? t("brand.typeUsd")
        : t("brand.typeUnits")
      : t("brand.pickAmount");
  const missingField = fields.find(
    (field) => field.required !== false && !(values[field.key] ?? "").trim(),
  );

  const toCheckout = (result: PlayerCheckResult | null) => {
    if (choice === null || !brand.data) return;
    void savePlayer(brand.data.slug, values);
    const { qty, amountUsd } = choice;
    router.push({
      pathname: "/checkout",
      params: {
        brandSlug: brand.data.slug,
        brandName: brand.data.name,
        skuId: choice.sku.id,
        label: choice.label,
        price: choice.price,
        fields: JSON.stringify(values),
        ...(qty !== undefined && qty !== 1 ? { qty: String(qty) } : {}),
        ...(amountUsd !== undefined ? { amountUsd } : {}),
        ...(choice.sku.notice ? { notice: choice.sku.notice.text } : {}),
        ...(result?.status === "valid" && result.name ? { player: result.name } : {}),
      },
    });
  };

  /** `then` runs with the answer when it is not «not found» — the pay button checks first. */
  const runCheck = (then?: (result: PlayerCheckResult) => void) => {
    if (checkField === undefined) return;
    const serverKey = checkField.check?.server_field;
    const serverId = serverKey != null ? values[serverKey]?.trim() : undefined;
    const settle = (result: PlayerCheckResult) => {
      setCheckResult(result);
      if (then && !checkBlocks(result)) then(result);
    };
    check.mutate(
      { playerId: (values[checkField.key] ?? "").trim(), ...(serverId ? { serverId } : {}) },
      { onSuccess: settle, onError: () => settle({ status: "error" }) },
    );
  };

  const goPay = () => {
    if (checkField !== undefined && checkBlocks(checkResult)) {
      if (checkResult === null) runCheck(toCheckout);
      return;
    }
    toCheckout(checkResult);
  };

  const onChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setCheckResult(null);
  };

  const pickProduct = (next: string) => {
    setProductSlug(next);
    setSku(null);
    setCount(0);
  };

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView
        contentContainerStyle={{ paddingHorizontal: space.gutter, paddingBottom: 160 }}
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
                <View style={{ flexDirection: "row", gap: 8 }}>
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

            <View style={{ marginTop: 16 }}>
              <PlayerFields
                fields={fields}
                values={values}
                onChange={onChange}
                {...(checkField ? { onCheck: () => runCheck() } : {})}
                checking={check.isPending}
                result={checkResult}
              />
            </View>

            {product.isPending ? (
              <ActivityIndicator color={c.mute} style={{ marginTop: 44 }} />
            ) : (
              <>
                {skus.length > 0 && (
                  <>
                    <T variant="label" tone="mute" style={{ marginTop: 24, marginBottom: 8 }}>
                      {t("brand.amount")}
                    </T>
                    <SkuGrid
                      skus={skus}
                      selectedId={sku?.id ?? null}
                      onSelect={(next) => {
                        setSku(next);
                        setCount(0);
                      }}
                    />
                  </>
                )}
                {rule !== null && (
                  <>
                    <T variant="label" tone="mute" style={{ marginTop: 24, marginBottom: 8 }}>
                      {rule.kind === "usd" ? t("brand.amountUsd") : t("brand.amountUnits")}
                    </T>
                    <AmountField
                      rule={rule}
                      value={sku === null ? count : 0}
                      onChange={(next) => {
                        setCount(next);
                        setSku(null);
                      }}
                    />
                  </>
                )}
              </>
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
        {/* What is picked and its price; before that the button itself says what is missing. */}
        {choice && (
          <View
            style={{
              flexDirection: "row",
              justifyContent: "space-between",
              alignItems: "baseline",
              marginBottom: 12,
            }}
          >
            <T tone="mute">{choice.label}</T>
            <T variant="amount">
              {formatSum(choice.price)} {t("common.sum")}
            </T>
          </View>
        )}
        <Button
          label={choice === null ? pickHint : missingField ? t("brand.enterId") : t("brand.toPay")}
          disabled={
            choice === null || missingField !== undefined || checkResult?.status === "invalid"
          }
          loading={check.isPending}
          onPress={goPay}
        />
      </View>
    </View>
  );
}
