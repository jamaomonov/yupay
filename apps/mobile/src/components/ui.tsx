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
import { cardShadow, fonts, radius, TOUCH } from "@/theme/tokens";

type Variant = "display" | "title" | "amount" | "h2" | "body" | "label" | "small";
type Tone = "fg" | "mute" | "dim" | "accent" | "ok" | "warn" | "danger";

/**
 * Five sizes — 26, 20, 17, 15, 13 — and two Inter weights. Unbounded is for `display` only:
 * it is wide, and a long screen title in it does not fit the bar.
 */
const VARIANTS: Record<Variant, TextStyle> = {
  display: { fontFamily: fonts.display, fontSize: 26, lineHeight: 32, letterSpacing: -0.5 },
  title: { fontFamily: fonts.semibold, fontSize: 20, lineHeight: 26, letterSpacing: -0.3 },
  amount: {
    fontFamily: fonts.semibold,
    fontSize: 17,
    lineHeight: 22,
    fontVariant: ["tabular-nums"],
  },
  h2: { fontFamily: fonts.semibold, fontSize: 15, lineHeight: 20 },
  body: { fontFamily: fonts.medium, fontSize: 15, lineHeight: 21 },
  label: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
  small: { fontFamily: fonts.medium, fontSize: 13, lineHeight: 18 },
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
  const { c, scheme } = useTheme();
  return (
    <View
      style={[
        {
          backgroundColor: c.card,
          borderColor: c.border,
          borderWidth: 1,
          borderRadius: radius.card,
          ...cardShadow(scheme),
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
  // Disabled is grey, not a faded lime: a washed-out accent reads as broken, grey as «not yet».
  const off = disabled === true && loading !== true;
  const primary = kind === "primary" && !off;
  const fg = off ? c.mute : primary ? c.primaryFg : c.fg;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: off, busy: loading === true }}
      disabled={disabled === true || loading === true}
      onPress={onPress}
      style={({ pressed }) => ({
        height: 52,
        borderRadius: radius.control,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: primary ? c.primary : c.muted,
        opacity: pressed ? 0.85 : 1,
        transform: [{ scale: pressed ? 0.98 : 1 }],
      })}
    >
      {loading === true ? (
        <ActivityIndicator color={fg} />
      ) : (
        <Text style={{ fontFamily: fonts.semibold, fontSize: 15, color: fg }}>{label}</Text>
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
      accessibilityRole="button"
      accessibilityState={{ selected: active === true }}
      onPress={onPress}
      hitSlop={{ top: (TOUCH - 40) / 2, bottom: (TOUCH - 40) / 2 }}
      style={{
        height: 40,
        paddingHorizontal: 16,
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

/** A centred message with an optional icon and action — loading errors and empty states. */
export function Notice({
  text,
  action,
  icon,
}: {
  text: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <View style={{ paddingVertical: 48, alignItems: "center", gap: 16 }}>
      {icon}
      <T tone="mute" style={{ textAlign: "center" }}>
        {text}
      </T>
      {action}
    </View>
  );
}

export type BadgeTone = "ok" | "warn" | "danger" | "mute";

/** A small coloured pill: an order's status at a glance. */
export function Badge({ label, tone }: { label: string; tone: BadgeTone }) {
  const { c } = useTheme();
  const color = tone === "mute" ? c.mute : c[tone];
  const background = tone === "mute" ? c.muted : c[`${tone}Bg`];
  return (
    <View
      style={{
        alignSelf: "flex-start",
        height: 24,
        paddingHorizontal: 8,
        borderRadius: 8,
        justifyContent: "center",
        backgroundColor: background,
      }}
    >
      <Text style={{ fontFamily: fonts.semibold, fontSize: 13, color }}>{label}</Text>
    </View>
  );
}

/** A grey block in the shape of what is loading. */
export function Skeleton({ style }: { style?: StyleProp<ViewStyle> }) {
  const { c } = useTheme();
  return <View style={[{ backgroundColor: c.muted, borderRadius: radius.small }, style]} />;
}
