/**
 * Design tokens for the app (ADR-0100).
 *
 * The dark palette is the web storefront's (`apps/web/src/app/globals.css`); the light one is
 * new. Lime is a fill, never text on white — `accent` is the readable green for links and
 * small highlights in the light theme.
 */

export interface Palette {
  bg: string;
  card: string;
  muted: string;
  border: string;
  fg: string;
  mute: string;
  dim: string;
  primary: string;
  primaryFg: string;
  accent: string;
  selBg: string;
  selBorder: string;
  ok: string;
  okBg: string;
  warn: string;
  warnBg: string;
  danger: string;
  dangerBg: string;
}

export type Scheme = "light" | "dark";

export const palettes: Record<Scheme, Palette> = {
  light: {
    bg: "#F5F6F8",
    card: "#FFFFFF",
    muted: "#EEF0F4",
    border: "#E3E6EC",
    fg: "#0B0D17",
    mute: "#5B6275",
    dim: "#8D93A5",
    primary: "#AAFF33",
    primaryFg: "#000000",
    accent: "#3D7A00",
    selBg: "#F3FFE3",
    selBorder: "#8BD420",
    ok: "#1F9D55",
    okBg: "#E7F7EE",
    warn: "#B26B00",
    warnBg: "#FFF4E0",
    danger: "#D92D20",
    dangerBg: "#FEECEB",
  },
  dark: {
    bg: "#060712",
    card: "#0A0D1A",
    muted: "#141829",
    border: "#1A1F38",
    fg: "#FFFFFF",
    mute: "#9DA8C8",
    dim: "#7982A0",
    primary: "#AAFF33",
    primaryFg: "#000000",
    accent: "#AAFF33",
    selBg: "rgba(170,255,51,0.08)",
    selBorder: "#AAFF33",
    ok: "#4ADE80",
    okBg: "rgba(74,222,128,0.10)",
    warn: "#FFC24D",
    warnBg: "rgba(255,194,77,0.10)",
    danger: "#F97066",
    dangerBg: "rgba(240,68,56,0.12)",
  },
};

export const radius = { control: 14, card: 20, tile: 16, small: 10 } as const;

/** Font family names as registered by `useFonts` in the root layout. */
export const fonts = {
  regular: "Inter_400Regular",
  medium: "Inter_500Medium",
  semibold: "Inter_600SemiBold",
  bold: "Inter_700Bold",
  display: "Unbounded_600SemiBold",
} as const;

export const space = { gutter: 18 } as const;
