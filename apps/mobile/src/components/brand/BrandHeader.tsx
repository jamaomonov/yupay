import type { BrandDetailOut } from "@yupay/api-client/types";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { router } from "expo-router";
import { ChevronLeft, Star } from "lucide-react-native";
import { useEffect, useState } from "react";
import { Animated, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";
import { space, TOUCH } from "@/theme/tokens";

const HERO = 170;

/** Cover gradients for a game with neither a cover nor a logo; the slug picks one, always the same. */
const COVERS: readonly (readonly [string, string])[] = [
  ["#3B2A7A", "#141833"],
  ["#11546B", "#0F1A2E"],
  ["#6B2A4E", "#1A1326"],
  ["#2F5A1F", "#111A14"],
  ["#6B4A12", "#1C160C"],
];

function coverOf(slug: string): readonly [string, string] {
  let sum = 0;
  for (const ch of slug) sum += ch.codePointAt(0) ?? 0;
  return COVERS[sum % COVERS.length] ?? ["#3B2A7A", "#141833"];
}

/** The logo arrives from below and a little small, as if it flew in from the grid tile. */
function useArrival() {
  const [arrive] = useState(() => new Animated.Value(0));
  const [style] = useState(() => ({
    opacity: arrive,
    transform: [
      { translateY: arrive.interpolate({ inputRange: [0, 1], outputRange: [24, 0] }) },
      { scale: arrive.interpolate({ inputRange: [0, 1], outputRange: [0.7, 1] }) },
    ],
  }));
  useEffect(() => {
    Animated.spring(arrive, {
      toValue: 1,
      friction: 7,
      tension: 70,
      useNativeDriver: true,
    }).start();
  }, [arrive]);
  return style;
}

/** Cover image fading into the page, the back button over it, logo and name below. */
export function BrandHeader({ brand }: { brand: BrandDetailOut }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const arrival = useArrival();
  const cover = coverOf(brand.slug);

  return (
    <View>
      <View
        style={{
          height: HERO + insets.top,
          marginHorizontal: -space.gutter,
          backgroundColor: c.muted,
          // The blurred-logo cover is drawn larger than the box; it must not spill under the name.
          overflow: "hidden",
        }}
      >
        {brand.hero_image_url !== null ? (
          <Image
            source={brand.hero_image_url}
            style={{ position: "absolute", inset: 0 }}
            contentFit="cover"
            transition={200}
          />
        ) : brand.logo_url !== null ? (
          // No cover: the logo itself, blurred to a wash of its own colours.
          <Image
            source={brand.logo_url}
            style={{ position: "absolute", inset: 0, transform: [{ scale: 1.4 }] }}
            contentFit="cover"
            blurRadius={40}
          />
        ) : (
          <LinearGradient
            colors={[cover[0], cover[1]]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={{ position: "absolute", inset: 0 }}
          />
        )}
        <LinearGradient
          colors={["rgba(0,0,0,0.45)", "transparent", c.bg]}
          locations={[0, 0.45, 1]}
          style={{ position: "absolute", inset: 0 }}
        />
        <Pressable
          onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))}
          accessibilityRole="button"
          style={{
            position: "absolute",
            top: insets.top + 8,
            left: space.gutter,
            width: TOUCH,
            height: TOUCH,
            borderRadius: 14,
            alignItems: "center",
            justifyContent: "center",
            // Dark on any cover: a light hero image used to swallow the button.
            backgroundColor: "rgba(6,7,18,0.6)",
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.2)",
          }}
        >
          <ChevronLeft size={22} color="#FFFFFF" />
        </Pressable>
      </View>

      <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 12, marginTop: -32 }}>
        <Animated.View
          style={{
            ...arrival,
            width: 64,
            height: 64,
            borderRadius: 18,
            overflow: "hidden",
            borderWidth: 2,
            borderColor: c.bg,
            backgroundColor: c.muted,
          }}
        >
          {brand.logo_url !== null && (
            <Image
              source={brand.logo_url}
              style={{ width: "100%", height: "100%" }}
              contentFit="cover"
            />
          )}
        </Animated.View>
        <View style={{ flex: 1, paddingBottom: 4 }}>
          <T variant="title" numberOfLines={1}>
            {brand.name}
          </T>
          {brand.rating != null && (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 }}>
              <Star size={13} color="#FFB800" fill="#FFB800" />
              <T variant="small" tone="mute">
                {brand.rating.avg.toFixed(1)} · {brand.rating.count}
              </T>
            </View>
          )}
        </View>
      </View>
    </View>
  );
}
