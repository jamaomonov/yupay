import { Tabs, type BottomTabBarProps } from "expo-router/tabs";
import { House, LayoutGrid, ReceiptText, UserRound, type LucideIcon } from "lucide-react-native";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { fonts } from "@/theme/tokens";

const ICONS: Record<string, LucideIcon> = {
  index: House,
  catalog: LayoutGrid,
  orders: ReceiptText,
  profile: UserRound,
};

const LABELS: Record<string, string> = {
  index: "tabs.home",
  catalog: "tabs.catalog",
  orders: "tabs.orders",
  profile: "tabs.profile",
};

/** Four tabs with a lime dot under the active one (the agreed mockup). */
function TabBar({ state, navigation }: BottomTabBarProps) {
  const { c } = useTheme();
  const { t } = useI18n();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={{
        flexDirection: "row",
        justifyContent: "space-around",
        paddingTop: 9,
        paddingBottom: Math.max(insets.bottom, 10),
        backgroundColor: c.card,
        borderTopWidth: 1,
        borderTopColor: c.border,
      }}
    >
      {state.routes.map((route, index) => {
        const focused = state.index === index;
        const Icon = ICONS[route.name] ?? House;
        const color = focused ? c.fg : c.dim;
        return (
          <Pressable
            key={route.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: focused }}
            onPress={() => {
              if (!focused) navigation.navigate(route.name);
            }}
            style={{ alignItems: "center", gap: 4, width: 72 }}
          >
            <Icon size={22} color={color} strokeWidth={1.8} />
            <Text style={{ fontFamily: fonts.medium, fontSize: 10.5, color }}>
              {t(LABELS[route.name] ?? route.name)}
            </Text>
            <View
              style={{
                width: 4,
                height: 4,
                borderRadius: 2,
                backgroundColor: focused ? c.primary : "transparent",
              }}
            />
          </Pressable>
        );
      })}
    </View>
  );
}

export default function TabsLayout() {
  const { c } = useTheme();
  return (
    <Tabs
      screenOptions={{ headerShown: false, sceneStyle: { backgroundColor: c.bg } }}
      tabBar={(props) => <TabBar {...props} />}
    >
      <Tabs.Screen name="index" />
      <Tabs.Screen name="catalog" />
      <Tabs.Screen name="orders" />
      <Tabs.Screen name="profile" />
    </Tabs>
  );
}
