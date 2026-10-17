import type { BrandDetailOut } from "@yupay/api-client/types";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { router } from "expo-router";
import { ChevronLeft, Star } from "lucide-react-native";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

const HERO = 170;

/** Cover image fading into the page, the back button over it, logo and name below. */
export function BrandHeader({ brand }: { brand: BrandDetailOut }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View>
      <View
        style={{
          height: HERO + insets.top,
          marginHorizontal: -space.gutter,
          backgroundColor: c.muted,
        }}
      >
        {brand.hero_image_url !== null && (
          <Image
            source={brand.hero_image_url}
            style={{ position: "absolute", inset: 0 }}
            contentFit="cover"
          />
        )}
        <LinearGradient
          colors={["rgba(0,0,0,0.25)", "transparent", c.bg]}
          locations={[0, 0.45, 1]}
          style={{ position: "absolute", inset: 0 }}
        />
        <Pressable
          onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))}
          accessibilityRole="button"
          style={{
            position: "absolute",
            top: insets.top + 6,
            left: space.gutter,
            width: 40,
            height: 40,
            borderRadius: 12,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(0,0,0,0.35)",
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.15)",
          }}
        >
          <ChevronLeft size={20} color="#FFFFFF" />
        </Pressable>
      </View>

      <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 12, marginTop: -30 }}>
        <View
          style={{
            width: 58,
            height: 58,
            borderRadius: 17,
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
        </View>
        <View style={{ flex: 1, paddingBottom: 2 }}>
          <T variant="title" numberOfLines={1}>
            {brand.name}
          </T>
          {brand.rating != null && (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 }}>
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
