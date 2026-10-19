import { Image } from "expo-image";
import { Pressable, View } from "react-native";

import { T } from "@/components/ui";
import type { PayMethod } from "@/lib/checkout";
import { useTheme } from "@/theme/ThemeProvider";
import { radius } from "@/theme/tokens";

const MARKS: Record<PayMethod, { name: string; mark: number }> = {
  payme: { name: "Payme", mark: require("../../../assets/images/payment/payme-mark.png") },
  click: { name: "Click", mark: require("../../../assets/images/payment/click-mark.png") },
  uzum: { name: "Uzum", mark: require("../../../assets/images/payment/uzum-mark.png") },
};

interface MethodPickerProps {
  methods: readonly PayMethod[];
  selected: PayMethod | null;
  onSelect: (method: PayMethod) => void;
}

/** The acquirers side by side, a brand mark over the name. */
export function MethodPicker({ methods, selected, onSelect }: MethodPickerProps) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: "row", gap: 8 }}>
      {methods.map((method) => {
        const active = method === selected;
        return (
          <Pressable
            key={method}
            accessibilityRole="radio"
            accessibilityState={{ selected: active }}
            onPress={() => onSelect(method)}
            style={{
              flex: 1,
              alignItems: "center",
              gap: 8,
              paddingVertical: 14,
              borderRadius: radius.tile,
              borderWidth: active ? 2 : 1,
              borderColor: active ? c.selBorder : c.border,
              backgroundColor: active ? c.selBg : c.card,
            }}
          >
            <Image
              source={MARKS[method].mark}
              style={{ width: 36, height: 36, borderRadius: 9 }}
              contentFit="contain"
            />
            <T variant="label">{MARKS[method].name}</T>
          </Pressable>
        );
      })}
    </View>
  );
}
