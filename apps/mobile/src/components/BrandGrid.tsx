import type { BrandOut } from "@yupay/api-client/types";
import { Image } from "expo-image";
import { router } from "expo-router";
import { Pressable, useWindowDimensions, View } from "react-native";

import { Skeleton, T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

const COLUMNS = 3;
const GAP = 12;

function useTile(): number {
  const { width } = useWindowDimensions();
  return Math.floor((Math.min(width, 430) - 2 * space.gutter - (COLUMNS - 1) * GAP) / COLUMNS);
}

/** The grid's shape while the catalogue loads. */
export function BrandGridSkeleton({ count = 9 }: { count?: number }) {
  const tile = useTile();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: GAP }}>
      {Array.from({ length: count }, (_, n) => (
        <View key={n} style={{ width: tile, gap: 8 }}>
          <Skeleton style={{ aspectRatio: 1, borderRadius: 18 }} />
          <Skeleton style={{ width: "70%", height: 12 }} />
        </View>
      ))}
    </View>
  );
}

/** Brand tiles in three columns: square logo, the name on up to two lines. */
export function BrandGrid({ brands }: { brands: readonly BrandOut[] }) {
  const { c } = useTheme();
  const tile = useTile();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: GAP }}>
      {brands.map((brand) => (
        <Pressable
          key={brand.slug}
          accessibilityRole="link"
          onPress={() => router.push({ pathname: "/brand/[slug]", params: { slug: brand.slug } })}
          style={({ pressed }) => ({
            width: tile,
            gap: 8,
            opacity: pressed ? 0.8 : 1,
            transform: [{ scale: pressed ? 0.97 : 1 }],
          })}
        >
          <View
            style={{
              aspectRatio: 1,
              borderRadius: 18,
              overflow: "hidden",
              backgroundColor: c.muted,
              borderWidth: 1,
              borderColor: c.border,
            }}
          >
            {brand.logo_url !== null && (
              <Image
                source={brand.logo_url}
                style={{ width: "100%", height: "100%" }}
                contentFit="cover"
                transition={150}
              />
            )}
          </View>
          <T variant="label" numberOfLines={2}>
            {brand.name}
          </T>
        </Pressable>
      ))}
    </View>
  );
}
