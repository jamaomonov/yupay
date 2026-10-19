import { router } from "expo-router";
import { ChevronLeft } from "lucide-react-native";
import { Pressable, View } from "react-native";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";
import { radius } from "@/theme/tokens";

interface TopBarProps {
  title: string;
  /** Where «back» goes when there is no history, e.g. after `router.replace`. */
  fallback?: "/" | "/orders" | "/profile";
}

/** A pushed screen's header: back button and a title. */
export function TopBar({ title, fallback = "/" }: TopBarProps) {
  const { c } = useTheme();
  return (
    <View style={{ height: 52, flexDirection: "row", alignItems: "center", gap: 10 }}>
      <Pressable
        accessibilityRole="button"
        hitSlop={8}
        onPress={() => (router.canGoBack() ? router.back() : router.replace(fallback))}
        style={{
          width: 38,
          height: 38,
          borderRadius: radius.small,
          backgroundColor: c.muted,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <ChevronLeft size={20} color={c.fg} />
      </Pressable>
      <T variant="title" numberOfLines={1} style={{ flex: 1 }}>
        {title}
      </T>
    </View>
  );
}
