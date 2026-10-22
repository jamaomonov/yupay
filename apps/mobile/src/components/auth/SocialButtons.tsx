import type { ReactNode } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import Svg, { Circle, Path } from "react-native-svg";

import type { Provider } from "@/lib/social-state";
import { useTheme } from "@/theme/ThemeProvider";
import { fonts, radius } from "@/theme/tokens";

function TelegramMark() {
  return (
    <Svg width={22} height={22} viewBox="0 0 48 48">
      <Circle cx={24} cy={24} r={20} fill="#29B6F6" />
      <Path
        fill="#FFFFFF"
        d="M33.95 15l-3.746 19.126s-.161.874-1.245.874c-.576 0-.873-.274-.873-.274l-8.114-6.733-3.97-2.001-5.095-1.355s-.907-.262-.907-1.012c0-.625.933-.923.933-.923l21.316-8.468s.651-.235 1.126-.234c.292 0 .625.125.625.5 0 .25-.05.5-.05.5z"
      />
      <Path
        fill="#B0BEC5"
        d="M23 30.505l-3.426 3.374s-.149.115-.348.12a.5.5 0 0 1-.219-.043l.964-5.965L23 30.505z"
      />
      <Path
        fill="#CFD8DC"
        d="M29.897 18.196a.5.5 0 0 0-.701-.093L15 26.6s2.266 6.339 2.611 7.437c.346 1.098.623 1.124.623 1.124l.964-5.965 10.606-9.812a.5.5 0 0 0 .093-.701z"
      />
    </Svg>
  );
}

function GoogleMark() {
  return (
    <Svg width={20} height={20} viewBox="0 0 48 48">
      <Path
        fill="#FFC107"
        d="M43.611 20.083H42V20H24v8h11.303c-1.649 4.657-6.08 8-11.303 8-6.627 0-12-5.373-12-12s5.373-12 12-12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 12.955 4 4 12.955 4 24s8.955 20 20 20 20-8.955 20-20c0-1.341-.138-2.65-.389-3.917z"
      />
      <Path
        fill="#FF3D00"
        d="M6.306 14.691l6.571 4.819C14.655 15.108 18.961 12 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 16.318 4 9.656 8.337 6.306 14.691z"
      />
      <Path
        fill="#4CAF50"
        d="M24 44c5.166 0 9.86-1.977 13.409-5.192l-6.19-5.238A11.91 11.91 0 0 1 24 36c-5.202 0-9.619-3.317-11.283-7.946l-6.522 5.025C9.505 39.556 16.227 44 24 44z"
      />
      <Path
        fill="#1976D2"
        d="M43.611 20.083H42V20H24v8h11.303a12.04 12.04 0 0 1-4.087 5.571l.003-.002 6.19 5.238C36.971 39.205 44 34 44 24c0-1.341-.138-2.65-.389-3.917z"
      />
    </Svg>
  );
}

/** Steam's mark (Simple Icons), one colour so it follows the theme. */
function SteamMark({ color }: { color: string }) {
  return (
    <Svg width={20} height={20} viewBox="0 0 24 24">
      <Path
        fill={color}
        d="M11.979 0C5.678 0 .511 4.86.022 11.037l6.432 2.658c.545-.371 1.203-.59 1.912-.59.063 0 .125.004.188.006l2.861-4.142V8.91c0-2.495 2.028-4.524 4.524-4.524 2.494 0 4.524 2.031 4.524 4.527s-2.03 4.525-4.524 4.525h-.105l-4.076 2.911c0 .052.004.105.004.159 0 1.875-1.515 3.396-3.39 3.396-1.635 0-3.016-1.173-3.331-2.727L.436 15.27C1.862 20.307 6.486 24 11.979 24c6.627 0 11.999-5.373 11.999-12S18.605 0 11.979 0zM7.54 18.21l-1.473-.61c.262.543.714.999 1.314 1.25 1.297.539 2.793-.076 3.332-1.375.263-.63.264-1.319.005-1.949s-.75-1.121-1.377-1.383c-.624-.26-1.29-.249-1.878-.03l1.523.63c.956.4 1.409 1.5 1.009 2.455-.397.957-1.497 1.41-2.454 1.012H7.54zm11.415-9.303c0-1.662-1.353-3.015-3.015-3.015-1.665 0-3.015 1.353-3.015 3.015 0 1.665 1.35 3.015 3.015 3.015 1.663 0 3.015-1.35 3.015-3.015zm-5.273-.005c0-1.252 1.013-2.266 2.265-2.266 1.249 0 2.266 1.014 2.266 2.266 0 1.251-1.017 2.265-2.266 2.265-1.253 0-2.265-1.014-2.265-2.265z"
      />
    </Svg>
  );
}

const NAMES: Record<Provider, string> = { telegram: "Telegram", google: "Google", steam: "Steam" };

function mark(provider: Provider, color: string): ReactNode {
  switch (provider) {
    case "telegram":
      return <TelegramMark />;
    case "google":
      return <GoogleMark />;
    case "steam":
      return <SteamMark color={color} />;
  }
}

interface SocialButtonsProps {
  /** «Войти через {name}» in the buyer's language. */
  label: (name: string) => string;
  busy: Provider | null;
  onPress: (provider: Provider) => void;
}

/** Telegram first: most YuPay accounts were opened through it. Steam for the CS2 buyers. */
export function SocialButtons({ label, busy, onPress }: SocialButtonsProps) {
  const { c } = useTheme();
  return (
    <View style={{ gap: 12 }}>
      {(["telegram", "google", "steam"] as const).map((provider) => (
        <Pressable
          key={provider}
          accessibilityRole="button"
          disabled={busy !== null}
          onPress={() => onPress(provider)}
          style={({ pressed }) => ({
            minHeight: 52,
            borderRadius: radius.control,
            borderWidth: 1,
            borderColor: c.border,
            backgroundColor: c.card,
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            opacity: busy !== null && busy !== provider ? 0.5 : pressed ? 0.8 : 1,
          })}
        >
          {busy === provider ? <ActivityIndicator color={c.fg} /> : mark(provider, c.fg)}
          <Text
            maxFontSizeMultiplier={1.3}
            style={{ fontFamily: fonts.semibold, fontSize: 15, color: c.fg }}
          >
            {label(NAMES[provider])}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}
