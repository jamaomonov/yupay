import type { BrandDetailOut } from "@yupay/api-client/types";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { router } from "expo-router";
import { ChevronLeft, Star } from "lucide-react-native";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";
import { space, TOUCH } from "@/theme/tokens";

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
        <View
          style={{
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
        </View>
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
