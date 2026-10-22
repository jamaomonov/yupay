import { useState, type ReactNode } from "react";
import { RefreshControl, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { FadeIn } from "@/components/FadeIn";
import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

interface ScreenProps {
  children: ReactNode;
  /** A large Unbounded heading; omit when the screen draws its own header. */
  title?: string;
  header?: ReactNode;
  /** Pull down to call it; the spinner stays until it settles. */
  onRefresh?: () => Promise<unknown>;
}

/** A tab screen: safe top inset, the gutter, vertical scroll. */
export function Screen({ children, title, header, onRefresh }: ScreenProps) {
  const insets = useSafeAreaInsets();
  const { c } = useTheme();
  const [refreshing, setRefreshing] = useState(false);
  const refresh = async () => {
    if (onRefresh === undefined) return;
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setRefreshing(false);
    }
  };
  return (
    <ScrollView
      {...(onRefresh !== undefined
        ? {
            refreshControl: (
              <RefreshControl
                refreshing={refreshing}
                onRefresh={() => void refresh()}
                tintColor={c.mute}
                colors={[c.fg]}
                progressBackgroundColor={c.card}
              />
            ),
          }
        : {})}
      contentContainerStyle={{
        paddingTop: insets.top + 4,
        paddingHorizontal: space.gutter,
        paddingBottom: 32,
      }}
      keyboardShouldPersistTaps="handled"
    >
      {header}
      {title !== undefined && (
        <View style={{ height: 48, justifyContent: "center", marginBottom: 8 }}>
          <T variant="display">{title}</T>
        </View>
      )}
      <FadeIn>{children}</FadeIn>
    </ScrollView>
  );
}
