/**
 * The app's small building blocks: text, card, button, chip. Every colour comes from the
 * theme, so a screen never decides light or dark by itself.
 */
import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  Text,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from "react-native";

import { useTheme } from "@/theme/ThemeProvider";
import { fonts, radius } from "@/theme/tokens";

type Variant = "display" | "title" | "h2" | "body" | "label" | "small";
type Tone = "fg" | "mute" | "dim" | "accent" | "ok" | "warn" | "danger";

const VARIANTS: Record<Variant, TextStyle> = {
  display: { fontFamily: fonts.display, fontSize: 24, letterSpacing: -0.5 },
  title: { fontFamily: fonts.display, fontSize: 20, letterSpacing: -0.4 },
  h2: { fontFamily: fonts.semibold, fontSize: 15 },
  body: { fontFamily: fonts.medium, fontSize: 14 },
  label: { fontFamily: fonts.medium, fontSize: 12.5 },
  small: { fontFamily: fonts.regular, fontSize: 12.5 },
};

interface TProps {
  children: ReactNode;
  variant?: Variant;
  tone?: Tone;
  style?: StyleProp<TextStyle>;
  numberOfLines?: number;
}

export function T({ children, variant = "body", tone = "fg", style, numberOfLines }: TProps) {
  const { c } = useTheme();
  return (
    <Text
      {...(numberOfLines === undefined ? {} : { numberOfLines })}
      style={[VARIANTS[variant], { color: c[tone] }, style]}
    >
      {children}
    </Text>
  );
}

interface CardProps {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}

export function Card({ children, style }: CardProps) {
  const { c } = useTheme();
  return (
    <View
      style={[
        {
          backgroundColor: c.card,
          borderColor: c.border,
          borderWidth: 1,
          borderRadius: radius.card,
          overflow: "hidden",
        },
        style,
      ]}
    >
      {children}
    </View>
  );
}

interface ButtonProps {
  label: string;
  onPress: () => void;
  kind?: "primary" | "ghost";
  disabled?: boolean;
  loading?: boolean;
}

export function Button({ label, onPress, kind = "primary", disabled, loading }: ButtonProps) {
  const { c } = useTheme();
  const primary = kind === "primary";
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled === true || loading === true}
      onPress={onPress}
      style={({ pressed }) => ({
        height: 52,
        borderRadius: radius.control,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: primary ? c.primary : c.muted,
        opacity: disabled === true ? 0.45 : pressed ? 0.85 : 1,
      })}
    >
      {loading === true ? (
        <ActivityIndicator color={primary ? c.primaryFg : c.fg} />
      ) : (
        <Text
          style={{ fontFamily: fonts.semibold, fontSize: 15, color: primary ? c.primaryFg : c.fg }}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

interface ChipProps {
  label: string;
  active?: boolean;
  onPress?: () => void;
}

export function Chip({ label, active, onPress }: ChipProps) {
  const { c } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      style={{
        height: 34,
        paddingHorizontal: 14,
        borderRadius: radius.small,
        justifyContent: "center",
        backgroundColor: active === true ? c.fg : c.muted,
      }}
    >
      <Text
        style={{ fontFamily: fonts.semibold, fontSize: 13, color: active === true ? c.bg : c.mute }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

/** A centred message with an optional action — loading errors and empty states. */
export function Notice({ text, action }: { text: string; action?: ReactNode }) {
  return (
    <View style={{ paddingVertical: 48, alignItems: "center", gap: 16 }}>
      <T tone="mute" style={{ textAlign: "center" }}>
        {text}
      </T>
      {action}
    </View>
  );
}
