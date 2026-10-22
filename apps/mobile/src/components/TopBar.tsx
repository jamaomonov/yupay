import { router } from "expo-router";
import { ChevronLeft } from "lucide-react-native";
import { Pressable, View } from "react-native";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";
import { radius, TOUCH } from "@/theme/tokens";

interface TopBarProps {
  title: string;
  /** Where «back» goes when there is no history, e.g. after `router.replace`. */
  fallback?: "/" | "/orders" | "/profile";
}

/** A pushed screen's header: back button and a title. */
export function TopBar({ title, fallback = "/" }: TopBarProps) {
  const { c } = useTheme();
  return (
    <View style={{ height: 56, flexDirection: "row", alignItems: "center", gap: 12 }}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Back"
        onPress={() => (router.canGoBack() ? router.back() : router.replace(fallback))}
        style={{
          width: TOUCH,
          height: TOUCH,
          borderRadius: radius.control,
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
