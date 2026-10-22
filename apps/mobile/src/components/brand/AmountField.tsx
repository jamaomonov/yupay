import { TextInput, View } from "react-native";

import { T } from "@/components/ui";
import { checkCount, countLabel, parseCount, type AmountRule } from "@/lib/amount";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { fonts, radius } from "@/theme/tokens";

interface AmountFieldProps {
  rule: AmountRule;
  value: number;
  onChange: (value: number) => void;
}

/** A typed amount: dollars for Steam, a count for Stars. */
export function AmountField({ rule, value, onChange }: AmountFieldProps) {
  const { t } = useI18n();
  const { c } = useTheme();
  const check = checkCount(value, rule);
  const bounds = { min: countLabel(rule.min, rule), max: countLabel(rule.max, rule) };
  const hint =
    check === "low"
      ? t("brand.tooLow", bounds)
      : check === "high"
        ? t("brand.tooHigh", bounds)
        : t("brand.range", bounds);
  const wrong = check === "low" || check === "high";

  return (
    <View style={{ gap: 8 }}>
      <View
        style={{
          height: 52,
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: 16,
          borderRadius: radius.control,
          borderWidth: 1,
          borderColor: wrong ? c.danger : c.border,
          backgroundColor: c.card,
        }}
      >
        <TextInput
          value={value === 0 ? "" : String(value)}
          onChangeText={(text) => onChange(parseCount(text))}
          keyboardType="number-pad"
          placeholder={String(rule.placeholder)}
          placeholderTextColor={c.dim}
          accessibilityLabel={rule.kind === "usd" ? t("brand.amountUsd") : t("brand.amountUnits")}
          style={{
            flex: 1,
            height: "100%",
            fontFamily: fonts.semibold,
            fontSize: 17,
            color: c.fg,
          }}
        />
        <T tone="mute" style={{ fontFamily: fonts.semibold }}>
          {rule.unit}
        </T>
      </View>
      <T variant="small" tone={wrong ? "danger" : "mute"}>
        {hint}
      </T>
    </View>
  );
}
