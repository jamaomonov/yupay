import { Image } from "expo-image";
import type { ReactNode } from "react";
import { Pressable, View } from "react-native";

import { Card, T } from "@/components/ui";
import type { PayMethod } from "@/lib/checkout";
import { useTheme } from "@/theme/ThemeProvider";

const MARKS: Record<PayMethod, { name: string; mark: number }> = {
  payme: { name: "Payme", mark: require("../../../assets/images/payment/payme-mark.png") },
  click: { name: "Click", mark: require("../../../assets/images/payment/click-mark.png") },
  uzum: { name: "Uzum", mark: require("../../../assets/images/payment/uzum-mark.png") },
  paynet: { name: "Paynet", mark: require("../../../assets/images/payment/paynet-mark.png") },
};

interface MethodRowProps {
  /** A 36-pt mark: a bank's logo, or an icon tile for the balance. */
  mark: ReactNode;
  title: string;
  /** A second line: the balance, what is missing. */
  hint?: ReactNode;
  /** Right of the title, before the radio. */
  value?: string;
  active: boolean;
  disabled?: boolean;
  first?: boolean;
  onPress: () => void;
}

/** One way to pay: mark, name, a radio. Every method is the same row, balance included. */
export function MethodRow({
  mark,
  title,
  hint,
  value,
  active,
  disabled,
  first,
  onPress,
}: MethodRowProps) {
  const { c } = useTheme();
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected: active, disabled: disabled === true }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 64,
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        paddingHorizontal: 16,
        paddingVertical: 12,
        borderTopWidth: first === true ? 0 : 1,
        borderTopColor: c.border,
        opacity: pressed ? 0.7 : 1,
      })}
    >
      {mark}
      <View style={{ flex: 1, gap: 2 }}>
        <T variant="h2" tone={disabled === true ? "mute" : "fg"}>
          {title}
        </T>
        {hint}
      </View>
      {value !== undefined && (
        <T tone="mute" style={{ fontVariant: ["tabular-nums"] }}>
          {value}
        </T>
      )}
      <View
        style={{
          width: 22,
          height: 22,
          borderRadius: 11,
          borderWidth: active ? 7 : 2,
          borderColor: active ? c.selBorder : c.border,
          backgroundColor: c.card,
        }}
      />
    </Pressable>
  );
}

interface MethodPickerProps {
  methods: readonly PayMethod[];
  selected: PayMethod | null;
  onSelect: (method: PayMethod) => void;
  /** Rows above the banks in the same card — the balance at checkout. */
  before?: ReactNode;
}

/** The acquirers as rows in one card, a brand mark and a radio each. */
export function MethodPicker({ methods, selected, onSelect, before }: MethodPickerProps) {
  return (
    <Card>
      {before}
      {methods.map((method, index) => (
        <MethodRow
          key={method}
          first={before === undefined && index === 0}
          mark={
            <Image
              source={MARKS[method].mark}
              style={{ width: 36, height: 36, borderRadius: 10 }}
              contentFit="contain"
            />
          }
          title={MARKS[method].name}
          active={method === selected}
          onPress={() => onSelect(method)}
        />
      ))}
    </Card>
  );
}
