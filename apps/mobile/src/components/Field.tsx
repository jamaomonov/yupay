import { TextInput, View, type TextInputProps } from "react-native";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";
import { fonts, radius } from "@/theme/tokens";

interface FieldProps extends Pick<
  TextInputProps,
  "autoComplete" | "keyboardType" | "secureTextEntry" | "textContentType" | "placeholder"
> {
  label: string;
  value: string;
  onChange: (text: string) => void;
  /** Shown under the input; red when `error` is set. */
  hint?: string;
  error?: boolean;
}

/** A labelled text input in the app's style. */
export function Field({ label, value, onChange, hint, error, ...input }: FieldProps) {
  const { c } = useTheme();
  return (
    <View>
      <T variant="label" tone="mute" style={{ marginBottom: 8 }}>
        {label}
      </T>
      <TextInput
        maxFontSizeMultiplier={1.2}
        value={value}
        onChangeText={onChange}
        placeholderTextColor={c.dim}
        autoCapitalize="none"
        autoCorrect={false}
        {...input}
        style={{
          height: 52,
          paddingHorizontal: 16,
          borderRadius: radius.control,
          borderWidth: 1,
          borderColor: error === true ? c.danger : c.border,
          backgroundColor: c.card,
          fontFamily: fonts.medium,
          fontSize: 15,
          color: c.fg,
        }}
      />
      {hint !== undefined && (
        <T variant="small" tone={error === true ? "danger" : "mute"} style={{ marginTop: 8 }}>
          {hint}
        </T>
      )}
    </View>
  );
}
