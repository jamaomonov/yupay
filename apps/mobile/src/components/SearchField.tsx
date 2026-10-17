import { Search } from "lucide-react-native";
import { Pressable, TextInput, View } from "react-native";

import { T } from "@/components/ui";
import { useTheme } from "@/theme/ThemeProvider";
import { fonts, radius } from "@/theme/tokens";

interface SearchFieldProps {
  placeholder: string;
  value?: string;
  onChangeText?: (text: string) => void;
  /** Render as a button (the home screen hands the search to the catalog). */
  onPress?: () => void;
  autoFocus?: boolean;
}

export function SearchField({
  placeholder,
  value,
  onChangeText,
  onPress,
  autoFocus,
}: SearchFieldProps) {
  const { c } = useTheme();
  const box = {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: 10,
    height: 46,
    paddingHorizontal: 14,
    borderRadius: radius.control,
    backgroundColor: c.card,
    borderWidth: 1,
    borderColor: c.border,
  };

  if (onPress !== undefined) {
    return (
      <Pressable onPress={onPress} style={box}>
        <Search size={18} color={c.dim} />
        <T tone="dim">{placeholder}</T>
      </Pressable>
    );
  }

  return (
    <View style={box}>
      <Search size={18} color={c.dim} />
      <TextInput
        value={value ?? ""}
        {...(onChangeText === undefined ? {} : { onChangeText })}
        placeholder={placeholder}
        placeholderTextColor={c.dim}
        autoFocus={autoFocus === true}
        autoCorrect={false}
        style={{ flex: 1, fontFamily: fonts.medium, fontSize: 14, color: c.fg, height: "100%" }}
      />
    </View>
  );
}
