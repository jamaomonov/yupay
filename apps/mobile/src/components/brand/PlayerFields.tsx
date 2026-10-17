import type { PublicFormField as FormField } from "@yupay/api-client/types";
import { Check, CircleAlert, Info } from "lucide-react-native";
import { useState } from "react";
import { ActivityIndicator, Pressable, TextInput, View } from "react-native";

import { Chip, T } from "@/components/ui";
import type { PlayerCheckResult } from "@/lib/api";
import { pickLocalized, useI18n } from "@/lib/i18n";
import { useTheme } from "@/theme/ThemeProvider";
import { fonts, radius } from "@/theme/tokens";

interface PlayerFieldsProps {
  fields: readonly FormField[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  /** Present when the product has a player check (`field.check`). */
  onCheck?: () => void;
  checking: boolean;
  result: PlayerCheckResult | null;
}

/** The order form a product asks for — player ID, server — with the live check. */
export function PlayerFields({
  fields,
  values,
  onChange,
  onCheck,
  checking,
  result,
}: PlayerFieldsProps) {
  return (
    <View style={{ gap: 14 }}>
      {fields.map((field) => (
        <Field
          key={field.key}
          field={field}
          value={values[field.key] ?? ""}
          onChange={(text) => onChange(field.key, text)}
          {...(field.check != null && onCheck !== undefined ? { onCheck } : {})}
          checking={checking}
        />
      ))}
      {result !== null && <CheckResult result={result} />}
    </View>
  );
}

interface FieldProps {
  field: FormField;
  value: string;
  onChange: (text: string) => void;
  onCheck?: () => void;
  checking: boolean;
}

function Field({ field, value, onChange, onCheck, checking }: FieldProps) {
  const { c } = useTheme();
  const { t, locale } = useI18n();
  const [helpOpen, setHelpOpen] = useState(false);
  const label = pickLocalized(field.label, locale) ?? field.key;
  const help = pickLocalized(field.help_text, locale);
  const placeholder = pickLocalized(field.placeholder, locale) ?? "";

  return (
    <View>
      <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 8 }}>
        <T variant="label" tone="mute">
          {label}
        </T>
        {help !== undefined && (
          <Pressable onPress={() => setHelpOpen((open) => !open)} hitSlop={8}>
            <T variant="label" tone="accent">
              {t("brand.whereId")}
            </T>
          </Pressable>
        )}
      </View>

      {field.options != null && field.options.length > 0 ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
          {field.options.map((option) => (
            <Chip
              key={option.value}
              label={pickLocalized(option.label, locale) ?? option.value}
              active={option.value === value}
              onPress={() => onChange(option.value)}
            />
          ))}
        </View>
      ) : (
        <View
          style={{
            height: 50,
            flexDirection: "row",
            alignItems: "center",
            gap: 10,
            paddingLeft: 14,
            paddingRight: 6,
            borderRadius: radius.control,
            borderWidth: 1,
            borderColor: c.border,
            backgroundColor: c.card,
          }}
        >
          <TextInput
            value={value}
            onChangeText={onChange}
            placeholder={placeholder}
            placeholderTextColor={c.dim}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType={field.type === "number" ? "number-pad" : "default"}
            style={{ flex: 1, height: "100%", fontFamily: fonts.medium, fontSize: 15, color: c.fg }}
          />
          {onCheck !== undefined && (
            <Pressable
              onPress={onCheck}
              disabled={checking || value.trim() === ""}
              style={({ pressed }) => ({
                height: 38,
                minWidth: 96,
                paddingHorizontal: 14,
                borderRadius: radius.small,
                backgroundColor: c.muted,
                alignItems: "center",
                justifyContent: "center",
                opacity: value.trim() === "" ? 0.5 : pressed ? 0.7 : 1,
              })}
            >
              {checking ? (
                <ActivityIndicator size="small" color={c.fg} />
              ) : (
                <T variant="label" style={{ fontFamily: fonts.semibold, fontSize: 13 }}>
                  {t("brand.check")}
                </T>
              )}
            </Pressable>
          )}
        </View>
      )}

      {helpOpen && help !== undefined && (
        <View style={{ marginTop: 8, padding: 12, borderRadius: 12, backgroundColor: c.muted }}>
          <T variant="small" tone="mute" style={{ lineHeight: 19 }}>
            {help}
          </T>
        </View>
      )}
    </View>
  );
}

function CheckResult({ result }: { result: PlayerCheckResult }) {
  const { c } = useTheme();
  const { t } = useI18n();

  const look =
    result.status === "valid"
      ? { fg: c.ok, bg: c.okBg, Icon: Check }
      : result.status === "invalid"
        ? { fg: c.danger, bg: c.dangerBg, Icon: CircleAlert }
        : { fg: c.warn, bg: c.warnBg, Icon: Info };

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingVertical: 10,
        paddingHorizontal: 12,
        borderRadius: 12,
        backgroundColor: look.bg,
        marginTop: -4,
      }}
    >
      <look.Icon size={16} color={look.fg} strokeWidth={2.4} />
      <T variant="small" style={{ color: look.fg, flex: 1 }}>
        {t(`check.${result.status}`)}
        {result.status === "valid" && result.name != null && (
          <T variant="small" style={{ fontFamily: fonts.semibold }}>
            {" "}
            {result.name}
          </T>
        )}
      </T>
    </View>
  );
}
