import type { BrandOut } from "@yupay/api-client/types";
import { Image } from "expo-image";
import { router } from "expo-router";
import { Pressable, useWindowDimensions, View } from "react-native";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

const COLUMNS = 3;
const GAP = 10;

/** Brand tiles in three columns: square logo, one line of name. */
export function BrandGrid({ brands }: { brands: readonly BrandOut[] }) {
  const { c } = useTheme();
  const { width } = useWindowDimensions();
  const tile = Math.floor(
    (Math.min(width, 430) - 2 * space.gutter - (COLUMNS - 1) * GAP) / COLUMNS,
  );
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: GAP }}>
      {brands.map((brand) => (
        <Pressable
          key={brand.slug}
          accessibilityRole="link"
          onPress={() => router.push({ pathname: "/brand/[slug]", params: { slug: brand.slug } })}
          style={({ pressed }) => ({ width: tile, gap: 8, opacity: pressed ? 0.8 : 1 })}
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
          <T variant="label" numberOfLines={1} style={{ fontSize: 12 }}>
            {brand.name}
          </T>
        </Pressable>
      ))}
    </View>
  );
}
