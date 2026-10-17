import type { ReactNode } from "react";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { T } from "@/components/ui";
import { space } from "@/theme/tokens";

interface ScreenProps {
  children: ReactNode;
  /** A large Unbounded heading; omit when the screen draws its own header. */
  title?: string;
  header?: ReactNode;
}

/** A tab screen: safe top inset, the gutter, vertical scroll. */
export function Screen({ children, title, header }: ScreenProps) {
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      contentContainerStyle={{
        paddingTop: insets.top + 4,
        paddingHorizontal: space.gutter,
        paddingBottom: 32,
      }}
      keyboardShouldPersistTaps="handled"
    >
      {header}
      {title !== undefined && (
        <View style={{ height: 48, justifyContent: "center", marginBottom: 6 }}>
          <T variant="display">{title}</T>
        </View>
      )}
      {children}
    </ScrollView>
  );
}
